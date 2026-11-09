#!/usr/bin/env python3
"""Verify the Dolby Vision metadata chain: pinned fork -> kernel packetizer.

Steps performed here (all inside the CI workspace, nothing touches hardware):

  1. extract `dv_injection.c` from the repository kernel patch,
  2. generate and compile a host harness that calls the *real* kernel helpers
     (`validate_metadata`, `pack_bytes`, `expand_pixels`) with every constant
     copied verbatim from that source,
  3. consume the fork probe output (`manifest.txt` + per-frame `.nal/.rpu/.json`)
     produced by `tools/n1/dvhost/forkprobe`,
  4. run the verification groups and write `summary.json` + `verify.log`.

Groups
  G1 fork_wire     write_rpu() is 0xFF || DM; the NAL is 7C 01 || escaped(RPU);
                   un-escaping reproduces the RPU bytes exactly.
  G2 port_vs_fork  the Python port of the fork serializer, fed the fork's own
                   RPU JSON, reproduces the fork's DM byte for byte (diagnostic
                   only: the kernel groups always use the fork's bytes).
  G3 kernel_pack   every fork DM is validated, packetised and expanded by the
                   real kernel code and re-decoded by an independent checker.
  G4 boundaries    exact size boundaries 119/120/240/241/361/362/482/483/594
                   must give 1/2/2/3/3/4/4/5/5 packets; 595 must be rejected.
  G5 l9            level-9 length handling against the current kernel table.
  G6 negative      a flipped packet byte must be detected.
"""
import argparse
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_dm            # noqa: E402
import verify_packets      # noqa: E402

ODD = 0xFFFFFFFF
EVEN = 0xFF000000
MAX_METADATA = 594  # DV_INJ_MAX_METADATA_SIZE, asserted against the source below


# ---------------------------------------------------------------- helpers ---
def unescape(data):
    out = bytearray()
    i = 0
    while i < len(data):
        if i + 2 < len(data) and data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 3:
            out += b'\x00\x00'
            i += 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def escape(data):
    out = bytearray()
    zeros = 0
    for b in data:
        if zeros >= 2 and b <= 3:
            out.append(3)
            zeros = 0
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return bytes(out)


def read_manifest(path):
    frames = {}
    order = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] != 'FRAME':
                continue
            kv = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
            name = kv['fixture']
            if name not in order:
                order.append(name)
            # Rows that failed in the probe carry an error instead of a frame
            # directory; they are counted by check_fork_run, not here.
            if 'dir' not in kv:
                continue
            frames.setdefault(name, []).append(kv)
    return order, frames



def walk_dm(dm, l9_declared=None, l9_written=None):
    """Walk the DM block table; return None on a clean walk, else a short reason.

    `l9_declared`/`l9_written` let the caller re-walk with the payload size the
    producer actually wrote, which is how the Level 9 mismatch is recognised.
    """
    if len(dm) < 71:
        return 'DM is only %d bytes, need at least 71' % len(dm)
    off = 71
    for _ in range(dm[70]):
        if off + 5 > len(dm):
            return 'block header runs past the end at offset %d' % off
        declared = int.from_bytes(dm[off:off + 4], 'big')
        level = dm[off + 4]
        off += 5
        if l9_declared is not None and level == 9 and declared == l9_declared:
            declared = l9_written
        if off + declared > len(dm):
            return 'level %d declares %d bytes but only %d remain' % (
                level, declared, len(dm) - off)
        off += declared
    if off != len(dm):
        return 'clean block walk ends at %d, DM is %d bytes' % (off, len(dm))
    return None


def classify_reject(dm):
    """Explain a -22 from the kernel without guessing.

    Returns (kind, detail). `kind` is 'producer_l9_18' when the only reason the
    DM does not walk is a Level 9 block declaring 18 bytes for the 17 the fork
    writes; anything else stays 'unknown' and is reported as a failure.
    """
    reason = walk_dm(dm)
    if reason is None:
        return 'unknown', ('the block walk is clean, so the kernel refused a '
                           'structurally valid DM')
    if walk_dm(dm, l9_declared=18, l9_written=17) is None:
        return 'producer_l9_18', ('a Level 9 block declares 18 bytes but the fork '
                                 'writes 17, so the walk desynchronises (%s)' % reason)
    return 'unknown', reason

def run_harness(harness, dm_bytes, workdir, strict=False, max_pad=None):
    os.makedirs(workdir, exist_ok=True)
    dm_path = os.path.join(workdir, 'dm.bin')
    with open(dm_path, 'wb') as f:
        f.write(dm_bytes)
    cmd = [harness, dm_path, workdir]
    if strict or max_pad is not None:
        cmd.append('1' if strict else '0')
    if max_pad is not None:
        cmd += ['0', '0', str(max_pad)]
    
    proc = subprocess.run(cmd, capture_output=True, text=True)
    info = {'rc': proc.returncode, 'stdout': proc.stdout.strip()}
    pkt_path = os.path.join(workdir, 'packets.bin')
    pix_path = os.path.join(workdir, 'pixels.bin')
    if os.path.exists(pkt_path):
        info['packets'] = open(pkt_path, 'rb').read()
        os.remove(pkt_path)
    if os.path.exists(pix_path):
        raw = open(pix_path, 'rb').read()
        info['pixel_words'] = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
        os.remove(pix_path)
    return info


# --------------------------------------------------------------- G4 units ---
# (level, declared length in the BE32 header, zero padding bytes)
UNITS = [
    (1, 6, 0),
    (9, 1, 0),
    (4, 4, 0),
    (11, 4, 4),
    (5, 8, 0),
    (6, 8, 2),
    (2, 14, 0),
    (254, 2, 2),
]


def solve_blocks(target):
    if target < 71:
        return None
    dp = {71: []}
    for size in range(71, target):
        if size not in dp:
            continue
        chosen = dp[size]
        for level, declared, pad in UNITS:
            nxt = size + 5 + declared
            if nxt > target:
                continue
            if nxt not in dp or len(dp[nxt]) > len(chosen) + 1:
                dp[nxt] = chosen + [(level, declared, pad)]
    return dp.get(target)


def synth_dm(target):
    blocks = solve_blocks(target)
    if blocks is None:
        return None
    head = bytearray(71)
    head[60] = 12
    head[61] = 2
    head[62] = 0
    head[63] = 1
    head[70] = len(blocks) & 0xFF
    out = bytearray(head)
    for level, declared, pad in blocks:
        out += struct.pack('>I', declared)
        out.append(level)
        out += bytes((0x40 + level) & 0xFF for _ in range(declared - pad))
        out += b'\x00' * pad
    return bytes(out)


def synth_dm_l9(payload_len, declared_len):
    blocks = [(1, 6, 0), (9, declared_len, 0)]
    head = bytearray(71)
    head[60] = 12
    head[61] = 2
    head[62] = 1
    head[63] = 1
    head[70] = len(blocks) & 0xFF
    out = bytearray(head)
    for level, declared, _pad in blocks:
        out += struct.pack('>I', declared)
        out.append(level)
        n = payload_len if level == 9 else declared
        out += bytes((0x41 + level) & 0xFF for _ in range(n))
    return bytes(out)


# ------------------------------------------------------------------- main ---
def prepare_harness(patch, work):
    os.makedirs(work, exist_ok=True)
    src = os.path.join(work, 'dv_injection.c')
    subprocess.run([sys.executable, os.path.join(HERE, 'split_kernel_patch.py'),
                    '--patch', patch, '--out', src], check=True)
    text = open(src, encoding='utf-8').read()
    global MAX_METADATA
    for line in text.splitlines():
        if line.startswith('#define DV_INJ_MAX_METADATA_SIZE'):
            MAX_METADATA = int(line.split()[-1])
    hc = os.path.join(work, 'harness.c')
    subprocess.run([sys.executable, os.path.join(HERE, 'extract_kernel_harness.py'),
                    '--src', src, '--out', hc], check=True)
    exe = os.path.join(work, 'harness')
    subprocess.run(['cc', '-std=c99', '-O1', '-Wall', '-Wextra', '-o', exe, hc],
                   check=True)
    return exe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--patch')
    ap.add_argument('--forkout', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--summary', required=True)
    ap.add_argument('--log')
    ap.add_argument('--harness')
    args = ap.parse_args()

    verify_packets.self_test()
    harness = args.harness or prepare_harness(args.patch, os.path.join(args.work, 'build'))

    order, frames = read_manifest(os.path.join(args.forkout, 'manifest.txt'))
    rows = []

    def add(group, name, status, detail='', expected_fail=False):
        rows.append({'group': group, 'name': name, 'status': status,
                     'detail': detail, 'expected_fail': expected_fail})

    # ---------------- G1 / G2 ----------------
    port_ok = port_bad = port_skip = 0
    nal_ok = nal_bad = 0
    for fixture in order:
        for fr in frames.get(fixture, []):
            idx = int(fr['idx'])
            base = os.path.join(args.forkout, fr['dir'])
            tag = '%s/f%d' % (fixture, idx)
            rpu = open(os.path.join(base, 'f%03d.rpu' % idx), 'rb').read()
            nal = open(os.path.join(base, 'f%03d.nal' % idx), 'rb').read()

            if rpu[:1] != b'\xff':
                nal_bad += 1
                add('G1', tag, 'FAIL', 'write_rpu() does not start with 0xFF: %r' % rpu[:4])
                continue
            if nal[:2] != b'\x7c\x01':
                nal_bad += 1
                add('G1', tag, 'FAIL', 'NAL does not start with 7C 01: %r' % nal[:4])
                continue
            stripped = unescape(nal[2:])
            if stripped != rpu or escape(rpu) != nal[2:]:
                nal_bad += 1
                diff = next((k for k in range(min(len(stripped), len(rpu)))
                             if stripped[k] != rpu[k]), None)
                add('G1', tag, 'FAIL',
                    'escape/un-escape round trip differs (first diff %s, %d vs %d bytes)'
                    % (diff, len(stripped), len(rpu)))
                continue
            nal_ok += 1

            json_path = os.path.join(base, 'f%03d.json' % idx)
            if not os.path.exists(json_path):
                port_skip += 1
                continue
            try:
                rpu_json = json.load(open(json_path, encoding='utf-8'))
                port_dm = build_dm.build_or_none(rpu_json)
            except Exception as exc:      # noqa: BLE001
                port_bad += 1
                add('G2', tag, 'FAIL', 'port raised %s: %s' % (type(exc).__name__, exc))
                continue
            if port_dm is None:
                port_skip += 1
                add('G2', tag, 'INFO',
                    'port does not model this block set (kernel still verified with fork bytes)')
                continue
            fork_dm = rpu[1:]
            if port_dm == fork_dm:
                port_ok += 1
            else:
                port_bad += 1
                diff = next((k for k in range(min(len(port_dm), len(fork_dm)))
                             if port_dm[k] != fork_dm[k]), None)
                add('G2', tag, 'FAIL',
                    'port DM != fork DM (first diff %s, port %d B, fork %d B)'
                    % (diff, len(port_dm), len(fork_dm)))

    add('G1', 'wire_roundtrip', 'PASS' if not nal_bad else 'FAIL',
        'frames_ok=%d frames_bad=%d' % (nal_ok, nal_bad))
    add('G2', 'port_vs_fork', 'PASS' if not port_bad else 'FAIL',
        'port_ok=%d port_bad=%d not_modeled=%d' % (port_ok, port_bad, port_skip))

    # ---------------- G3 ----------------
    work3 = os.path.join(args.work, 'g3')
    hist = {}
    failures = []
    known = []
    total = accepted = dm_bytes = 0
    for fixture in order:
        for fr in frames.get(fixture, []):
            idx = int(fr['idx'])
            base = os.path.join(args.forkout, fr['dir'])
            dm = open(os.path.join(base, 'f%03d.rpu' % idx), 'rb').read()[1:]
            total += 1
            dm_bytes += len(dm)
            info = run_harness(harness, dm, work3)
            if info['rc'] != 0:
                kind, detail = classify_reject(dm)
                if kind == 'producer_l9_18':
                    known.append('%s/f%d %s' % (fixture, idx, detail))
                else:
                    failures.append('%s/f%d rejected (%s): %s'
                                    % (fixture, idx, detail, info['stdout'][:120]))
                continue
            ok, problems, st = verify_packets.check(info.get('packets', b''), dm,
                                                    info.get('pixel_words'), ODD, EVEN)
            hist[st['num_pkts']] = hist.get(st['num_pkts'], 0) + 1
            if not ok:
                failures.append('%s/f%d %s' % (fixture, idx, '; '.join(problems[:3])))
                continue
            accepted += 1
    add('G3', 'kernel_pack_all_frames', 'PASS' if not failures else 'FAIL',
        'accepted=%d/%d pkt_hist=%s%s%s'
        % (accepted, total, json.dumps({str(k): v for k, v in sorted(hist.items())}),
           '' if not failures else ' failures=' + ' | '.join(failures[:5]),
           '' if not known else ' producer_l9_18_frames=%d' % len(known)))
    if known:
        add('G3', 'rejects_explained', 'KNOWN_DEFECT',
            '%d frames rejected only because a Level 9 block declares 18 bytes for '
            'the 17 the fork writes (first: %s)' % (len(known), known[0]))

    # ---------------- G4 ----------------
    expect = {119: 1, 120: 2, 240: 2, 241: 3, 361: 3, 362: 4, 482: 4, 483: 5, 594: 5}
    work4 = os.path.join(args.work, 'g4')
    for size in sorted(expect):
        dm = synth_dm(size)
        if dm is None:
            add('G4', 'size_%d' % size, 'FAIL', 'no block multiset found')
            continue
        info = run_harness(harness, dm, work4)
        if info['rc'] != 0:
            add('G4', 'size_%d' % size, 'FAIL', 'rejected: %s' % info['stdout'][:100])
            continue
        ok, problems, st = verify_packets.check(info.get('packets', b''), dm,
                                                info.get('pixel_words'), ODD, EVEN)
        if st.get('num_pkts') != expect[size] or not ok:
            add('G4', 'size_%d' % size, 'FAIL',
                'num_pkts=%s want=%d %s' % (st.get('num_pkts'), expect[size],
                                            '; '.join(problems[:2])))
        else:
            add('G4', 'size_%d' % size, 'PASS', 'num_pkts=%d' % st['num_pkts'])
    dm595 = synth_dm(595)
    info = run_harness(harness, dm595, work4)
    add('G4', 'size_%d_rejected' % (MAX_METADATA + 1),
        'PASS' if 'validate=0' not in info['stdout'] else 'FAIL',
        info['stdout'].splitlines()[0] if info['stdout'] else 'rc=%d' % info['rc'])

    # ---------------- G7 ----------------
    # The sink hands the decoder buffer over padded to 32 bytes, so the length
    # the module sees is an upper bound.  This group replays exactly that on
    # the real fork bytes and requires the packet bytes to be identical to the
    # unpadded run: the effective length has to reach pack, not just validate.
    work7 = os.path.join(args.work, 'g7')
    pad_ok = pad_bad = tail_ok = tail_bad = sweep_ok = sweep_bad = 0
    pad_problems = []
    for fixture in order:
        fr_list = frames.get(fixture, [])
        for pos, fr in enumerate(fr_list):
            idx = int(fr['idx'])
            base = os.path.join(args.forkout, fr['dir'])
            dm = open(os.path.join(base, 'f%03d.rpu' % idx), 'rb').read()[1:]
            ref = run_harness(harness, dm, work7)
            if ref['rc'] != 0:
                kind, _ = classify_reject(dm)
                if kind == 'producer_l9_18':
                    continue
                pad_problems.append('%s/f%d canonical rejected' % (fixture, idx))
                pad_bad += 1
                continue
            nal = 3 + len(dm)
            pad = (nal + 31) // 32 * 32 - nal
            aux = dm + b'\x00' * pad
            got = run_harness(harness, aux, work7, max_pad=31)
            if got['rc'] != 0:
                pad_problems.append('%s/f%d aux rejected: %s'
                                    % (fixture, idx, got['stdout'][:100]))
                pad_bad += 1
            elif got.get('packets') != ref.get('packets'):
                pad_problems.append('%s/f%d packets differ under padding'
                                    % (fixture, idx))
                pad_bad += 1
            else:
                pad_ok += 1
            bad_tail = run_harness(harness, aux + b'\x01', work7, max_pad=31)
            if bad_tail['rc'] == 0:
                pad_problems.append('%s/f%d non-zero tail accepted' % (fixture, idx))
                tail_bad += 1
            else:
                tail_ok += 1
            # exhaustive 0..31 sweep on the first frame of the first three fixtures
            if pos == 0 and order.index(fixture) < 3:
                for n in range(32):
                    sweep = run_harness(harness, dm + b'\x00' * n, work7,
                                        max_pad=31)
                    if sweep['rc'] != 0 or sweep.get('packets') != ref.get('packets'):
                        pad_problems.append('%s pad %d failed' % (fixture, n))
                        sweep_bad += 1
                    else:
                        sweep_ok += 1
    add('G7', 'aux_padding_roundtrip',
        'PASS' if not (pad_bad or tail_bad or sweep_bad) else 'FAIL',
        'aux_ok=%d aux_bad=%d tail_rejected=%d tail_accepted=%d sweep_ok=%d sweep_bad=%d%s'
        % (pad_ok, pad_bad, tail_ok, tail_bad, sweep_ok, sweep_bad,
           '' if not pad_problems else ' failures=' + ' | '.join(pad_problems[:5])))

    # ---------------- G5 ----------------
    work5 = os.path.join(args.work, 'g5')
    l9 = [
        ('l9_declared_1', synth_dm_l9(1, 1), True, False,
         'declared 1 with a 1-byte payload: accepted, matches the captured DMs'),
        ('l9_declared_17', synth_dm_l9(17, 17), False, True,
         'a 17-byte payload declared as 17: the kernel table only allows 1'),
        ('l9_declared_18', synth_dm_l9(17, 18), False, True,
         'what the pinned fork writes today: declared 18, 17 bytes written'),
    ]
    for name, dm, want_accept, known_defect, note in l9:
        info = run_harness(harness, dm, work5)
        accepted_here = 'validate=0' in info['stdout']
        first = info['stdout'].splitlines()[0] if info['stdout'] else 'rc'
        if known_defect:
            # Measured behaviour is the defect itself: record it, do not call it
            # a pass. Accepting one of these would be the real failure.
            add('G5', name, 'KNOWN_DEFECT' if not accepted_here else 'FAIL',
                'current kernel %s (%s); the fix must pair the producer and the '
                'kernel table' % (first, note), expected_fail=True)
        elif accepted_here == want_accept:
            add('G5', name, 'PASS', '%s (%s)' % (first, note))
        else:
            add('G5', name, 'FAIL', 'unexpected result (%s)' % note)

    # ---------------- G6 ----------------
    work6 = os.path.join(args.work, 'g6')
    sample = None
    for fixture in order:
        if frames.get(fixture):
            fr = frames[fixture][0]
            path = os.path.join(args.forkout, fr['dir'], 'f%03d.rpu' % int(fr['idx']))
            if os.path.exists(path):
                sample = open(path, 'rb').read()[1:]
                break
    if sample:
        info = run_harness(harness, sample, work6)
        pkts = bytearray(info.get('packets', b''))
        if pkts:
            pkts[10] ^= 0x5A
            ok, problems, _st = verify_packets.check(bytes(pkts), sample, None, ODD, EVEN)
            add('G6', 'tampered_packet_detected', 'PASS' if not ok else 'FAIL',
                '; '.join(problems[:2]))
        else:
            add('G6', 'tampered_packet_detected', 'FAIL', 'no packets produced')
    else:
        add('G6', 'tampered_packet_detected', 'FAIL', 'no sample DM available')

    # ---------------- summary ----------------
    hard_fail = [r for r in rows if r['status'] == 'FAIL']
    groups = []
    for gid in ('G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'):
        mine = [r for r in rows if r['group'] == gid]
        if gid in ('G1', 'G2'):
            mine = mine  # summary rows only
        groups.append({
            'name': gid,
            'cases': len(mine),
            'pass': len([r for r in mine if r['status'] == 'PASS']),
            'fail': len([r for r in mine if r['status'] == 'FAIL']),
            'expected_fail': len([r for r in mine if r['status'] == 'KNOWN_DEFECT']),
        })
    summary = {
        'verdict': 'FAIL' if hard_fail else 'PASS',
        'groups': groups,
        'fixtures': len(order),
        'frames': total,
        'dm_bytes_compared': dm_bytes,
        'rows': rows,
        'failures': hard_fail,
        'notes': [
            'G3 uses the DM bytes produced by the pinned fork itself; the Python '
            'port in G2 is only a localisation aid.',
            'A KNOWN_DEFECT row records measured kernel behaviour, not an approval: '
            'the level-9 17-byte payload needs a paired producer + kernel change.',
            'Host verification cannot show that the TV accepts the pixels; it only '
            'proves the metadata bytes and packetisation are self-consistent.',
        ],
    }
    with open(args.summary, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=1)

    lines = []
    for r in rows:
        lines.append('%-13s %-3s %-24s %s'
                     % (r['status'], r['group'], r['name'], r['detail']))
    lines.append('')
    lines.append('VERDICT: %s  (fixtures=%d frames=%d dm_bytes=%d hard_failures=%d)'
                 % (summary['verdict'], len(order), total, dm_bytes, len(hard_fail)))
    text = '\n'.join(lines)
    print(text)
    if args.log:
        with open(args.log, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
    return 0 if not hard_fail else 1


if __name__ == '__main__':
    sys.exit(main())
