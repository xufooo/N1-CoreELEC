#!/usr/bin/env python3
"""Port of the pinned fork's DM serialiser, for localising disagreements.

Only used by G2 of ``run_verify.py``: when this port and the fork bytes agree,
a later failure is more likely to be in the kernel side than in the DM the
fork produced. Every unsupported block is reported as "not modelled" instead
of being guessed.

Reference:
  dolby_vision/src/rpu/vdr_dm_data.rs             (fixed part, block count)
  dolby_vision/src/rpu/extension_metadata/mod.rs  (BE32 declared length, level)
  dolby_vision/src/rpu/extension_metadata/blocks/level*.rs  (payload, write_bytes_size)
"""

import json
import struct
import sys

# Fixed part before the total_num_ext_blocks byte: 2 ids + (68 coefficient and
# signalling bytes) + 3 mastering-display values, when the DM is not compressed.
FIXED_PART = 70

# The fork writes a different number of payload bytes than it declares for some
# levels, because it pads them: DECLARED[level][written_bytes] = declared_bytes.
DECLARED = {
    1: {6: 6},
    2: {14: 14},
    3: {6: 6},
    4: {4: 4},
    5: {8: 8},
    6: {8: 8},
    8: {13: 13, 15: 15, 17: 17, 23: 23, 29: 29},
    9: {1: 1, 17: 18},
    10: {6: 6, 22: 22},
    11: {4: 4},
    254: {2: 2},
    255: {6: 6},
}

# Zero padding the fork appends after a payload. Empty: every modelled level
# writes exactly the number of bytes it declares.
PADDING = {}


class UnsupportedLevel(Exception):
    """A block this port does not model; the caller must not treat it as a mismatch."""


def u16(value):
    return struct.pack('>H', value & 0xFFFF)


def s16(value):
    return struct.pack('>h', max(-32768, min(32767, value)))


def u32(value):
    return struct.pack('>I', value & 0xFFFFFFFF)


def is_compressed(rpu):
    dm = rpu.get('vdr_dm_data', {})
    if 'compressed' in dm:
        return bool(dm['compressed'])
    return rpu.get('header', {}).get('reserved_zero_3bits', 0) == 1


def build_fixed(rpu):
    """The fixed part, ending just before the extension block count."""
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
        raise UnsupportedLevel('fixed part is %d bytes, expected %d'
                               % (len(out), FIXED_PART))
    return bytes(out)


def block_payload(level, block):
    """Serialise one extension block payload the way the fork writes it."""
    if level == 1:
        return u16(block['min_pq']) + u16(block['max_pq']) + u16(block['avg_pq'])
    if level == 2:
        return (u16(block.get('target_max_pq', 0)) + u16(block.get('trim_slope', 0)) +
                u16(block.get('trim_offset', 0)) + u16(block.get('trim_power', 0)) +
                u16(block.get('trim_chroma_weight', 0)) +
                u16(block.get('trim_saturation_gain', 0)) +
                s16(block.get('ms_weight', 0)))
    if level == 3:
        return (u16(block.get('min_pq_offset', 0)) + u16(block.get('max_pq_offset', 0)) +
                u16(block.get('avg_pq_offset', 0)))
    if level == 4:
        return u16(block.get('anchor_pq', 0)) + u16(block.get('anchor_power', 0))
    if level == 5:
        return (u16(block.get('active_area_left_offset', 0)) +
                u16(block.get('active_area_right_offset', 0)) +
                u16(block.get('active_area_top_offset', 0)) +
                u16(block.get('active_area_bottom_offset', 0)))
    if level == 6:
        return (u16(block.get('max_display_mastering_luminance', 0)) +
                u16(block.get('min_display_mastering_luminance', 0)) +
                u16(block.get('max_content_light_level', 0)) +
                u16(block.get('max_frame_average_light_level', 0)))
    if level == 8:
        length = block.get('length', 10)
        out = bytearray([block.get('target_display_index', 0) & 0xFF])
        for name in ('trim_slope', 'trim_offset', 'trim_power', 'trim_chroma_weight',
                     'trim_saturation_gain', 'ms_weight'):
            out += u16(block.get(name, 0))
        if length > 10:
            out += u16(block.get('target_mid_contrast', 0))
        if length > 12:
            out += u16(block.get('clip_trim', 0))
        if length > 13:
            for i in range(6):
                out.append(block.get('saturation_vector_field%d' % i, 0) & 0xFF)
        if length > 19:
            for i in range(6):
                out.append(block.get('hue_vector_field%d' % i, 0) & 0xFF)
        return bytes(out)
    if level == 10:
        length = block.get('length', 5)
        out = bytearray([block.get('target_display_index', 0) & 0xFF])
        out += u16(block.get('target_max_pq', 0))
        out += u16(block.get('target_min_pq', 0))
        out.append(block.get('target_primary_index', 0) & 0xFF)
        if length > 5:
            for name in ('target_primary_red_x', 'target_primary_red_y',
                         'target_primary_green_x', 'target_primary_green_y',
                         'target_primary_blue_x', 'target_primary_blue_y',
                         'target_primary_white_x', 'target_primary_white_y'):
                out += u16(block.get(name, 0))
        return bytes(out)
    if level == 11:
        wp = block.get('whitepoint', 0)
        if block.get('reference_mode_flag'):
            wp += 16
        return bytes([block.get('content_type', 0) & 0xFF, wp & 0xFF,
                      block.get('reserved_byte2', 0) & 0xFF,
                      block.get('reserved_byte3', 0) & 0xFF])
    if level == 254:
        return bytes([block.get('dm_mode', 0) & 0xFF, block.get('dm_version_index', 0) & 0xFF])
    if level == 255:
        return bytes([block.get('dm_run_mode', 0) & 0xFF, block.get('dm_run_version', 0) & 0xFF,
                      block.get('dm_debug0', 0) & 0xFF, block.get('dm_debug1', 0) & 0xFF,
                      block.get('dm_debug2', 0) & 0xFF, block.get('dm_debug3', 0) & 0xFF])
    if level == 9:
        if block.get('length', 1) > 1:
            raise UnsupportedLevel('level 9 declares 18 bytes but the fork writes 17')
        out = bytearray([block.get('source_primary_index', 0) & 0xFF])
        if block.get('length', 1) > 1:
            for name in ('source_primary_red_x', 'source_primary_red_y',
                         'source_primary_green_x', 'source_primary_green_y',
                         'source_primary_blue_x', 'source_primary_blue_y',
                         'source_primary_white_x', 'source_primary_white_y'):
                out += u16(block.get(name, 0))
        return bytes(out)
    raise UnsupportedLevel('level %d payload is not serialised by this port' % level)


def blocks_of(rpu):
    """[(level, block)] from either the serde map shape or a flat list."""
    blocks = []
    for entry in rpu['vdr_dm_data'].get('ext_metadata_blocks') or []:
        if isinstance(entry, dict) and 'level' in entry:
            blocks.append((int(entry['level']), entry))
            continue
        for key, value in entry.items():
            if not key.startswith('Level'):
                raise UnsupportedLevel('unexpected block key %r' % key)
            blocks.append((int(key[len('Level'):]), value))
    if not blocks:
        dm = rpu['vdr_dm_data']
        for name in ('cmv29_metadata', 'cmv40_metadata'):
            for entry in (dm.get(name) or {}).get('ext_metadata_blocks') or []:
                for key, value in entry.items():
                    if not key.startswith('Level'):
                        raise UnsupportedLevel('unexpected block key %r' % key)
                    blocks.append((int(key[len('Level'):]), value))
    return blocks


def build(rpu):
    """Return the DM bytes the fork should emit for one serde RPU dict."""
    out = bytearray(build_fixed(rpu))
    table = []
    for level, block in blocks_of(rpu):
        payload = block_payload(level, block)
        if level not in DECLARED:
            raise UnsupportedLevel('level %d is not serialised by this port' % level)
        declared = DECLARED[level].get(len(payload))
        if declared is None:
            raise UnsupportedLevel('level %d payload %d bytes has no known declared length'
                                   % (level, len(payload)))
        table.append((level, declared, payload))
    if len(table) > 255:
        raise UnsupportedLevel('too many extension blocks')
    out.append(len(table) & 0xFF)
    for level, declared, payload in table:
        out += u32(declared)
        out.append(level & 0xFF)
        out += payload
        out += b'\x00' * PADDING.get(level, 0)
    return bytes(out)


def build_or_none(rpu):
    try:
        return build(rpu)
    except (UnsupportedLevel, KeyError):
        return None


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Build DM bytes from a fork RPU JSON dump')
    ap.add_argument('--json', required=True, help='dovi_tool export JSON (list or {"frames": [...]})')
    ap.add_argument('--out', help='write the first modelled DM here')
    args = ap.parse_args()
    data = json.load(open(args.json, encoding='utf-8'))
    frames = data.get('frames') if isinstance(data, dict) else data
    lens = {}
    for frame in frames:
        dm = build_or_none(frame)
        if dm is None:
            continue
        lens[len(dm)] = lens.get(len(dm), 0) + 1
    print('modelled DM lengths: %s' % sorted(lens.items()))
    if args.out and frames:
        dm = build_or_none(frames[0])
        if dm:
            open(args.out, 'wb').write(dm)
            print('wrote %s (%d bytes)' % (args.out, len(dm)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
