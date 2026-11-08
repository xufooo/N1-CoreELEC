#!/usr/bin/env python3
"""Independent checker for the kernel packetizer output.

Deliberately does NOT reuse `dv_injection_pack_bytes` logic: the rules are
re-derived from the reference implementation (NUM_BYTES_PER_PACKET=128,
CRC_OFFSET=124, PIXELS_PER_PKT=1024, 1 bit per pixel, header byte values
0x00/0x40/0x80/0xC0) and the module source is treated as the thing under test.

Checked per packet set:
  * packet type bytes follow the 00 / 40..80.. / C0 sequence
  * the first packet carries the total DM size as BE16 at [3..4]
  * byte 2 is zero and byte 1 equals dm[0]
  * concatenated payloads equal the DM exactly (no padding inside payload)
  * everything after the payload up to offset 124 is zero padding
  * CRC-32/MPEG-2 over [0..123] equals the BE32 stored at [124..127]
  * decoding one bit per pixel from the emitted pixel words reproduces the
    packet bytes (the pixel array is the real injection surface)

CRC-32/MPEG-2: poly 0x04C11DB7, init 0xFFFFFFFF, refin=false, refout=false,
xorout=0x00000000. Two independent implementations (bitwise and table) are
cross-checked, and the published check value crc(b"123456789") == 0x0376E6E7
is asserted, together with `!= zlib.crc32`.
"""
import argparse
import json
import struct
import sys
import zlib

POLY = 0x04C11DB7
INIT = 0xFFFFFFFF
CHECK = 0x0376E6E7
PACKET_BYTES = 128
CRC_OFFSET = 124
PIXELS_PER_PKT = 1024


def crc32_mpeg2_bitwise(data):
    crc = INIT
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ POLY) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def _make_table():
    table = []
    for i in range(256):
        crc = i << 24
        for _ in range(8):
            crc = ((crc << 1) ^ POLY) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
        table.append(crc)
    return table


TABLE = _make_table()


def crc32_mpeg2_table(data):
    crc = INIT
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ TABLE[((crc >> 24) ^ byte) & 0xFF]
    return crc


def self_test():
    assert crc32_mpeg2_bitwise(b'123456789') == CHECK, 'bitwise CRC self-test failed'
    assert crc32_mpeg2_table(b'123456789') == CHECK, 'table CRC self-test failed'
    assert zlib.crc32(b'123456789') & 0xFFFFFFFF != CHECK, 'CRC is not CRC-32/MPEG-2'


def check(packets, dm, pixel_words=None, odd=0xFFFFFFFF, even=0xFF000000):
    """Return (ok, list_of_problems, stats)."""
    problems = []
    stats = {}
    n = len(packets) // PACKET_BYTES
    stats['num_pkts'] = n
    if n == 0 or len(packets) % PACKET_BYTES:
        return False, ['packet buffer size %d is not a positive multiple of %d'
                       % (len(packets), PACKET_BYTES)], stats

    payload = bytearray()
    for i in range(n):
        pkt = packets[i * PACKET_BYTES:(i + 1) * PACKET_BYTES]
        first = i == 0
        last = i == n - 1
        want = 0x00 if (first and last) else (0x40 if first else (0xC0 if last else 0x80))
        if pkt[0] != want:
            problems.append('pkt%d type 0x%02x != 0x%02x' % (i, pkt[0], want))
        if pkt[1] != dm[0]:
            problems.append('pkt%d byte1 0x%02x != dm[0] 0x%02x' % (i, pkt[1], dm[0]))
        if pkt[2] != 0:
            problems.append('pkt%d byte2 0x%02x != 0' % (i, pkt[2]))
        if first:
            declared = (pkt[3] << 8) | pkt[4]
            stats['declared_size'] = declared
            if declared != len(dm):
                problems.append('pkt0 declared size %d != dm %d' % (declared, len(dm)))
            body = pkt[5:CRC_OFFSET]
        else:
            body = pkt[3:CRC_OFFSET]
        used = min(len(body), len(dm) - len(payload))
        if used < 0:
            used = 0
        payload += body[:used]
        extra = body[used:]
        if any(extra):
            problems.append('pkt%d has non-zero bytes after payload' % i)
        stored = struct.unpack('>I', pkt[CRC_OFFSET:CRC_OFFSET + 4])[0]
        calc = crc32_mpeg2_table(pkt[:CRC_OFFSET])
        if calc != stored:
            problems.append('pkt%d crc 0x%08x != 0x%08x' % (i, calc, stored))
        if calc != crc32_mpeg2_bitwise(pkt[:CRC_OFFSET]):
            problems.append('pkt%d crc implementations disagree' % i)

    if bytes(payload) != bytes(dm[:len(payload)]):
        first_diff = next((k for k in range(min(len(payload), len(dm)))
                           if payload[k] != dm[k]), None)
        problems.append('payload != dm (first diff at %s)' % first_diff)
    stats['payload_len'] = len(payload)
    if len(payload) != len(dm):
        problems.append('payload length %d != dm %d' % (len(payload), len(dm)))

    if pixel_words is not None:
        need = n * PIXELS_PER_PKT
        if len(pixel_words) != need:
            problems.append('pixel words %d != %d' % (len(pixel_words), need))
        else:
            decoded = bytearray()
            for i in range(n):
                chunk = pixel_words[i * PIXELS_PER_PKT:(i + 1) * PIXELS_PER_PKT]
                acc = 0
                bitpos = 0
                for word in chunk:
                    if word == odd:
                        bit = 1
                    elif word == even:
                        bit = 0
                    else:
                        problems.append('pkt%d has pixel 0x%08x that is neither pattern'
                                        % (i, word))
                        bit = 0
                    acc = (acc << 1) | bit
                    bitpos += 1
                    if bitpos % 8 == 0:
                        decoded.append(acc & 0xFF)
                        acc = 0
                if bitpos % 8:
                    decoded.append(acc & 0xFF)
            if bytes(decoded) != packets:
                problems.append('pixel decode does not reproduce packet bytes')
            stats['pixel_decoded_bytes'] = len(decoded)

    return not problems, problems, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--packets', required=True)
    ap.add_argument('--dm', required=True)
    ap.add_argument('--pixels')
    ap.add_argument('--odd', default='0xFFFFFFFF')
    ap.add_argument('--even', default='0xFF000000')
    args = ap.parse_args()
    self_test()
    packets = open(args.packets, 'rb').read()
    dm = open(args.dm, 'rb').read()
    words = None
    if args.pixels:
        raw = open(args.pixels, 'rb').read()
        words = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
    ok, problems, stats = check(packets, dm, words,
                                int(args.odd, 0), int(args.even, 0))
    print(json.dumps({'ok': ok, 'problems': problems[:20], 'stats': stats}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
