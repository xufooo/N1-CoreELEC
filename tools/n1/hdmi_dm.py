#!/usr/bin/env python3
"""Offline structural preflight for doppingkoala's HDMI DM byte format.

This is not an RPU decoder, pixel reshaper, HDMI transmitter, or proof of
Dolby Vision output. Input must already be standalone, uncompressed DM data;
raw HEVC/RPU, compressed DM and use-prev-RPU inputs require conversion/state
outside this tool. It never reads or writes device sysfs.

Format references (fixed version, not a general HDMI-DM standard):
https://github.com/doppingkoala/dovi_tool/commit/d4ad4ba7e6f5acef6c7321dac0139992a082cd8f
  dolby_vision/src/rpu/{vdr_dm_data,extension_metadata/blocks/*}.rs
https://github.com/doppingkoala/common_drivers/blob/eb85e7bde788a2b06c4ba808b1c4046f56a00de7/drivers/media/video_sink/dv_injection.c

The private 0xFF marker and HEVC 0x7C01 wrapper emitted by the modified
libdovi are NOT part of the DM block handed to the packetizer. Extension
lengths below are serialized HDMI byte widths, not raw-RPU bit widths.
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

MAX_DM_BYTES = 594
BASE_BYTES = 71  # 70-byte fields, then one-byte extension count

# name, byte width, signed; matches VdrDmData::write in the pinned fork.
BASE_FIELDS = (
    [(f"ycc_to_rgb_coef{i}", 2, True) for i in range(9)]
    + [(f"ycc_to_rgb_offset{i}", 4, False) for i in range(3)]
    + [(f"rgb_to_lms_coef{i}", 2, True) for i in range(9)]
    + [("signal_eotf", 2, False), ("signal_eotf_param0", 2, False),
       ("signal_eotf_param1", 2, False), ("signal_eotf_param2", 4, False)]
    + [(name, 1, False) for name in (
        "signal_bit_depth", "signal_color_space", "signal_chroma_format",
        "signal_full_range_flag")]
    + [(name, 2, False) for name in (
        "source_min_pq", "source_max_pq", "source_diagonal")]
)

# These are byte-stream layouts from the fork's write() methods.
BLOCK_FIELDS = {
    1: ("min_pq", "max_pq", "avg_pq"),
    2: ("target_max_pq", "trim_slope", "trim_offset", "trim_power",
        "trim_chroma_weight", "trim_saturation_gain", "ms_weight"),
    3: ("min_pq_offset", "max_pq_offset", "avg_pq_offset"),
    4: ("anchor_pq", "anchor_power"),
    5: ("active_area_left_offset", "active_area_right_offset",
        "active_area_top_offset", "active_area_bottom_offset"),
    6: ("max_display_mastering_luminance", "min_display_mastering_luminance",
        "max_content_light_level", "max_frame_average_light_level"),
}
BLOCK_LENGTHS = {level: {2 * len(fields)} for level, fields in BLOCK_FIELDS.items()}
BLOCK_LENGTHS.update({8: {13, 15, 17, 23, 29}, 9: {1}, 10: {6, 22},
                      11: {4}, 254: {2}, 255: {6}})
# Extended L9 is deliberately unsupported: the pinned fork declares 18
# serialized bytes but its write() emits 17. Do not guess or zero-pad it.


class DMError(ValueError):
    """The input is outside the supported standalone HDMI-DM contract."""


def _block_values(level, data):
    if level in BLOCK_FIELDS:
        values = {}
        for i, name in enumerate(BLOCK_FIELDS[level]):
            values[name] = int.from_bytes(data[2*i:2*i+2], "big",
                                         signed=(level == 2 and name == "ms_weight"))
        return values
    if level == 8:
        values = {"target_display_index": data[0]}
        names = ("trim_slope", "trim_offset", "trim_power", "trim_chroma_weight",
                 "trim_saturation_gain", "ms_weight", "target_mid_contrast", "clip_trim")
        words = min((len(data) - 1) // 2, 8)
        # The vector fields start after byte 17; they are individual bytes.
        for i, name in enumerate(names[:words]):
            values[name] = int.from_bytes(data[1+2*i:3+2*i], "big")
        for i, value in enumerate(data[17:23]):
            values[f"saturation_vector_field{i}"] = value
        for i, value in enumerate(data[23:29]):
            values[f"hue_vector_field{i}"] = value
        return values
    if level == 9:
        return {"source_primary_index": data[0]}
    if level == 10:
        values = {"target_display_index": data[0],
                  "target_max_pq": int.from_bytes(data[1:3], "big"),
                  "target_min_pq": int.from_bytes(data[3:5], "big"),
                  "target_primary_index": data[5]}
        primaries = ("red_x", "red_y", "green_x", "green_y", "blue_x", "blue_y",
                     "white_x", "white_y")
        for i in range((len(data) - 6) // 2):
            values[f"target_primary_{primaries[i]}"] = int.from_bytes(data[6+2*i:8+2*i], "big")
        return values
    if level == 11:
        return {"content_type": data[0], "whitepoint": data[1] & 15,
                "reference_mode_flag": bool(data[1] & 16),
                "reserved_byte2": data[2], "reserved_byte3": data[3]}
    if level == 254:
        return {"dm_mode": data[0], "dm_version_index": data[1]}
    return dict(zip(("dm_run_mode", "dm_run_version", "dm_debug0", "dm_debug1",
                     "dm_debug2", "dm_debug3"), data))


def parse_dm(data, *, compressed=False, use_prev_rpu=False):
    """Validate framing and return decoded fields; no inferred missing state.

    compressed/use_prev_rpu are explicit provenance flags for callers that
    possess source-RPU context. The bytes alone cannot prove its absence.
    Values are decoded, not certified as valid creative/display metadata.
    """
    if compressed or use_prev_rpu:
        raise DMError("compressed/use-prev-RPU metadata needs prior-frame state; unsupported")
    if not isinstance(data, bytes):
        raise DMError("expected bytes containing an already converted HDMI DM block")
    if data.startswith((b"\x00\x00\x00\x01", b"\x00\x00\x01", b"\x7c\x01")):
        raise DMError("raw HEVC/RPU wrapper is not HDMI DM; convert and strip its wrapper first")
    if not BASE_BYTES <= len(data) <= MAX_DM_BYTES:
        raise DMError(f"standalone uncompressed DM requires {BASE_BYTES}..{MAX_DM_BYTES} bytes")
    result = {"affected_dm_metadata_id": data[0] >> 4,
              "current_dm_metadata_id": data[0] & 15,
              "scene_refresh_flag": data[1]}
    pos = 2
    for name, width, signed in BASE_FIELDS:
        result[name] = int.from_bytes(data[pos:pos+width], "big", signed=signed)
        pos += width
    assert pos == 70
    if not 8 <= result["signal_bit_depth"] <= 16:
        raise DMError("invalid signal_bit_depth; raw RPU is not a standalone HDMI DM block")
    count = data[70]
    pos = BASE_BYTES
    extensions = []
    for index in range(count):
        if pos + 5 > len(data):
            raise DMError(f"extension {index}: truncated five-byte header")
        length = int.from_bytes(data[pos:pos+4], "big")
        level = data[pos+4]
        pos += 5
        if level not in BLOCK_LENGTHS or length not in BLOCK_LENGTHS[level]:
            raise DMError(f"extension {index}: unsupported HDMI level {level} length {length}")
        if pos + length > len(data):
            raise DMError(f"extension {index}: truncated payload (requires {length} bytes)")
        payload = data[pos:pos+length]
        extensions.append({"level": level, "length": length,
                           "data_hex": payload.hex(), "fields": _block_values(level, payload)})
        pos += length
    if pos != len(data):
        raise DMError(f"{len(data)-pos} trailing bytes after declared extensions")
    result["extensions"] = extensions
    return result


def strip_level6(data):
    """Remove L6 in an already validated DM block; preserve every other byte."""
    info = parse_dm(data)
    blocks = [b for b in info["extensions"] if b["level"] != 6]
    payload = data[:70] + bytes([len(blocks)])
    for block in blocks:
        body = bytes.fromhex(block["data_hex"])
        payload += struct.pack(">IB", len(body), block["level"]) + body
    parse_dm(payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="local binary HDMI DM file (not RPU)")
    parser.add_argument("--hex-input", action="store_true", help="input file contains hexadecimal DM text")
    parser.add_argument("--compressed", action="store_true", help="declare compressed source (rejected)")
    parser.add_argument("--use-prev-rpu", action="store_true", help="declare prior-RPU dependence (rejected)")
    parser.add_argument("--strip-level6", type=Path, metavar="OUTPUT", help="write L6-filtered binary DM to a NEW local file")
    args = parser.parse_args(argv)
    try:
        data = args.input.read_bytes()
        if args.hex_input:
            data = bytes.fromhex(data.decode("ascii"))
        info = parse_dm(data, compressed=args.compressed, use_prev_rpu=args.use_prev_rpu)
        if args.strip_level6:
            with args.strip_level6.open("xb") as output:
                output.write(strip_level6(data))
        print(json.dumps({"format": "doppingkoala-hdmi-dm-d4ad4ba7", "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest(), "metadata": info,
                          "scope": "structural check only; no RPU conversion or pixel reshaping"}, indent=2))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"hdmi_dm: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
