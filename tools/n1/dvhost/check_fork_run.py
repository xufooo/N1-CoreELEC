#!/usr/bin/env python3
"""Sanity-check the fork probe run before trusting the verification groups.

The probe writes one FRAME line per RPU it parsed and one FIXTURE line per
input file. Missing inputs, a fork that fails to parse everything, or a
profile-7 fixture where the conversion silently changed nothing would all make
the later groups meaningless, so they are checked here.

Exits non-zero when the run cannot support a verdict.
"""
import argparse
import collections
import sys


def parse(log_path):
    frames = []
    fixtures = []
    errors = []
    for line in open(log_path, encoding='utf-8'):
        parts = line.split()
        if not parts:
            continue
        kv = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
        kind = parts[0]
        if kind == 'FRAME':
            if 'parse_error' in kv or 'convert_error' in kv or 'write_' in ' '.join(kv):
                errors.append(line.strip())
            else:
                frames.append(kv)
        elif kind == 'FIXTURE':
            fixtures.append(kv)
        elif kind == 'SUMMARY':
            fixtures_page = kv
    return frames, fixtures, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', required=True)
    ap.add_argument('--out')
    ap.add_argument('--min-fixtures', type=int, default=3)
    ap.add_argument('--min-frames', type=int, default=10)
    args = ap.parse_args()

    frames, fixtures, errors = parse(args.log)
    problems = []

    per_fixture = collections.Counter(f['fixture'] for f in frames)
    profiles = collections.Counter(f['profile_in'] for f in frames)
    converted = sum(1 for f in frames if f.get('converted') == '1')

    print('parsed frames: %d in %d fixtures' % (len(frames), len(per_fixture)))
    for name, n in sorted(per_fixture.items()):
        print('  %-46s %4d frames  profiles=%s'
              % (name, n, sorted({f['profile_in'] for f in frames if f['fixture'] == name})))
    print('profile histogram: %s' % dict(sorted(profiles.items())))
    print('frames converted by the Kodi branch: %d' % converted)

    if len(errors):
        print('\nprobe errors (%d, first 10):' % len(errors))
        for line in errors[:10]:
            print('  ' + line)

    if len(per_fixture) < args.min_fixtures:
        problems.append('only %d fixtures produced frames (want >= %d)'
                        % (len(per_fixture), args.min_fixtures))
    if len(frames) < args.min_frames:
        problems.append('only %d frames parsed (want >= %d)' % (len(frames), args.min_frames))

    # The chain only exercises real work if a profile 7 fixture converted.
    control = [f for f in frames if f.get('ctl_rpu_len', '-') not in ('-', '')]
    changed = [f for f in control if f.get('ctl_rpu_len') != f.get('rpu_len')]
    if not control:
        problems.append('no profile 7 frame was converted, so the To81 branch is untested')
    elif not changed:
        problems.append('profile 7 conversion did not change any frame length')
    print('profile 7 controls: %d, lengths changed: %d' % (len(control), len(changed)))

    if problems:
        print('\nPROBE RUN UNUSABLE:')
        for p in problems:
            print('  - ' + p)
        return 1
    print('\nprobe run accepted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
