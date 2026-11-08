#!/usr/bin/env python3
"""Rebuild the Dolby Vision DM byte string from a fork RPU JSON dump.

This is a *port* of the pinned fork's serializer
(`dolby_vision/src/rpu/vdr_dm_data.rs` + `extension_metadata/*`) kept as a
diagnostic: in the CI run the authoritative bytes come from the fork binary
itself, and this port exists so that a disagreement can be localised to a
field instead of only "bytes differ".

Layout (fork semantics, evidence recorded in the OV host-chain notes):

    [0]       affected_dm_metadata_id(4) current_dm_metadata_id(4)
    [1]       scene_refresh_flag(8)
    [2..69]   9 x s16 ycc_to_rgb_coef, 3 x u32 ycc_to_rgb_offset,
              9 x s16 rgb_to_lms_coef, signal_eotf(16) param0(16) param1(16)
              param2(32) -- written only when the RPU header says the DM is
              NOT compressed (`header.reserved_zero_3bits != 1`)
    [70..73]  signal_bit_depth(8) signal_color_space(8) signal_chroma_format(8)
              signal_full_range_flag(8)
    [74..79]  source_min_pq(16) source_max_pq(16) source_diagonal(16)
    [80]      total_num_ext_blocks(8)
    then      per extension block: BE32 declared length, 1 byte level, payload

`DECLARED` maps the number of payload bytes the fork actually writes to the
length it declares in the BE32 header. Most levels declare their real size;
level 6 declares 8 for a 6-byte payload, and level 9 declares 18 while writing
only 17 bytes -- the mismatch that the kernel table rejects today.

The DM does *not* carry CMv2.9/CMv4.0 terminator blocks: a 136-byte profile 5
DM is exactly 71 + (5+6) + (5+14) + (5+4) + (5+8) + (5+8) with five blocks.
"""
import json
import struct
import sys

# level -> {payload bytes written by the fork: length declared in the BE32}
DECLARED = {
    1: {6: 6},
    2: {14: 14},
    4: {4: 4},
    5: {8: 8},
    6: {6: 8},
    9: {1: 1, 17: 18},
    10: {2: 6, 18: 22},
    11: {0: 4},
    254: {0: 2},
    255: {0: 6},
}

# How many padding bytes each level needs to reach its declared length.
PADDING = {6: 2, 11: 4, 254: 2, 255: 6}

FIXED_PART = 71


class UnsupportedLevel(Exception):
    """The frame carries an extension block this port does not serialise."""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def s16(v):
    if v < -32768 or v > 32767:
        raise ValueError('s16 out of range: %d' % v)
    return struct.pack('>h', v)


def u16(v):
    if v < 0 or v > 0xFFFF:
        raise ValueError('u16 out of range: %d' % v)
    return struct.pack('>H', v)


def u32(v):
    return struct.pack('>I', v)


def is_compressed(rpu):
    return rpu.get('header', {}).get('reserved_zero_3bits', 0) == 1


def build_fixed(rpu):
    """The 71-byte fixed part every DM starts with."""
    dm = rpu['vdr_dm_data']
    out = bytearray()
    out.append(((dm['affected_dm_metadata_id'] & 0xF) << 4) |
               (dm['current_dm_metadata_id'] & 0xF))
    out.append(dm['scene_refresh_flag'] & 0xFF)

    if not is_compressed(rpu):
        for i in range(9):
            out += s16(dm['ycc_to_rgb_coef%d' % i])
        for i in range(3):
            out += u32(dm['ycc_to_rgb_offset%d' % i])
        for i in range(9):
            out += s16(dm['rgb_to_lms_coef%d' % i])
        out += u16(dm['signal_eotf'])
        out += u16(dm['signal_eotf_param0'])
        out += u16(dm['signal_eotf_param1'])
        out += u32(dm['signal_eotf_param2'])

    out.append(dm['signal_bit_depth'] & 0xFF)
    out.append(dm['signal_color_space'] & 0xFF)
    out.append(dm['signal_chroma_format'] & 0xFF)
    out.append(dm['signal_full_range_flag'] & 0xFF)
    out += u16(dm['source_min_pq'])
    out += u16(dm['source_max_pq'])
    out += u16(dm['source_diagonal'])
    if len(out) != FIXED_PART:
        raise ValueError('fixed part is %d bytes, expected %d' % (len(out), FIXED_PART))
    return bytes(out)


def block_payload(level, block):
    """Serialise one extension block payload the way the fork does."""
    if level == 1:
        return u16(block['min_pq']) + u16(block['max_pq']) + u16(block['avg_pq'])
    if level == 2:
        out = (u16(block.get('target_max_pq', 0)) + u16(block.get('trim_slope', 0)) +
               u16(block.get('trim_offset', 0)) + u16(block.get('trim_power', 0)) +
               u16(block.get('trim_chroma_weight', 0)) +
               u16(block.get('trim_saturation_gain', 0)) +
               s16(block.get('ms_weight', 0)))
        return out
    if level == 4:
        return struct.pack('>HH', block.get('anchor_pq', 0), block.get('anchor_power', 0))
    if level == 5:
        return (u16(block.get('active_area_left_offset', 0)) +
                u16(block.get('active_area_right_offset', 0)) +
                u16(block.get('active_area_top_offset', 0)) +
                u16(block.get('active_area_bottom_offset', 0)))
    if level == 6:
        return (u16(block.get('max_display_mastering_luminance', 0)) +
                u16(block.get('min_display_mastering_luminance', 0)) +
                u16(block.get('max_content_light_level', 0)))
    if level == 9:
        out = bytearray([block.get('source_primary_index', 0) & 0xFF])
        if block.get('length', 1) == 17:
            for v in block['display_primaries_x']:
                out += u16(v)
            for v in block['display_primaries_y']:
                out += u16(v)
            out += u16(block['white_point_x'])
            out += u16(block['white_point_y'])
            out += u16(block['max_display_mastering_luminance'])
            out += u16(block['min_display_mastering_luminance'])
        return bytes(out)
    if level == 10:
        length = block.get('length', 0)
        out = bytearray(u16(length))
        if length == 16:
            out += u32(block['target_display_index'])
            out += u16(block['target_max_pq'])
            out += u16(block['target_min_pq'])
            out += u16(block['target_primary_index'])
        return bytes(out)
    raise UnsupportedLevel('level %s is not serialised by this port' % level)


def block_table(rpu):
    """[(level, declared_length, payload_len)] as the fork should emit them."""
    table = []
    for block in rpu['vdr_dm_data']['ext_metadata_blocks']:
        level = block['level']
        if level not in DECLARED:
            raise UnsupportedLevel('level %s is not serialised by this port' % level)
        payload = block_payload(level, block)
        declared = DECLARED[level].get(len(payload))
        if declared is None:
            raise UnsupportedLevel('level %d payload %d bytes has no known declared '
                                   'length' % (level, len(payload)))
        table.append((level, declared, len(payload)))
    return table


def build(rpu):
    """Return the DM bytes for one fork RPU dict (serde JSON form)."""
    out = bytearray(build_fixed(rpu))
    table = block_table(rpu)
    if len(table) > 255:
        raise ValueError('too many extension blocks')
    out.append(len(table) & 0xFF)
    for level, declared, plen in table:
        out += u32(declared)
        out.append(level & 0xFF)
        out += block_payload(level, _find_block(rpu, level, plen))
        out += b'\x00' * PADDING.get(level, 0)
    return bytes(out)


def _find_block(rpu, level, plen):
    for block in rpu['vdr_dm_data']['ext_metadata_blocks']:
        if block['level'] == level and len(block_payload(level, block)) == plen:
            return block
    raise UnsupportedLevel('block level %d payload %d disappeared' % (level, plen))


def build_or_none(rpu):
    try:
        return build(rpu)
    except UnsupportedLevel:
        return None


def main():
    if len(sys.argv) < 2:
        print('usage: build_dm.py <rpu.json> [frame_index]', file=sys.stderr)
        return 2
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    frames = data['frames'] if isinstance(data, dict) else data
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    sys.stdout.buffer.write(build(frames[idx]['rpu']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
