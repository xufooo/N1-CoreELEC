#!/usr/bin/env python3
"""Host-only contract tests. No device access or firmware build is performed."""

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hdmi_dm import DMError, parse_dm, strip_level6

# Public HDMI tunnel capture, provided by doppingkoala on 2024-07-19:
# https://github.com/quietvoid/dovi_tool/issues/303#issuecomment-2237841066
# Exact 181-byte DM payload, not extracted from any user's private media/logs.
CAPTURE = bytes.fromhex(
    "00012000031f06912000fc5b04432000010bea57000000000800000008000000"
    "42b9fea3fea3fea342b9fea3fea3fea342b9ffff00000000000000000c020101"
    "00070c07002a09000000060100070c0708000000000e020821072b07f406b4"
    "0800080008000000000e020b2308b108060a3e0800080008000000000e020c07"
    "08b308090b0e0800080008000000000404047c0488000000060308000800063c"
    "000000010902000000040b0000000000000002fe0002"
)


class HDMIDMTests(unittest.TestCase):
    def test_public_capture_all_blocks_and_base_fields(self):
        self.assertEqual(len(CAPTURE), 181)
        self.assertEqual(hashlib.sha256(CAPTURE).hexdigest(),
                         "1dac69a2b6dc8070a8f009a45c59a8875efe742792b7679ed078f238d5fce91f")
        dm = parse_dm(CAPTURE)
        self.assertEqual(dm["signal_bit_depth"], 12)
        self.assertEqual(dm["signal_color_space"], 2)
        self.assertEqual(dm["signal_chroma_format"], 1)
        self.assertEqual(dm["signal_full_range_flag"], 1)
        self.assertEqual((dm["source_min_pq"], dm["source_max_pq"], dm["source_diagonal"]),
                         (7, 3079, 42))
        self.assertEqual(dm["ycc_to_rgb_coef4"], -933)
        self.assertEqual([(b["level"], b["length"]) for b in dm["extensions"]],
                         [(1, 6), (2, 14), (2, 14), (2, 14), (4, 4),
                          (3, 6), (9, 1), (11, 4), (254, 2)])
        self.assertEqual(dm["extensions"][0]["fields"],
                         {"min_pq": 7, "max_pq": 3079, "avg_pq": 2048})
        self.assertEqual(dm["extensions"][-1]["fields"],
                         {"dm_mode": 0, "dm_version_index": 2})

    def test_capture_no_level6_is_byte_exact(self):
        self.assertEqual(strip_level6(CAPTURE), CAPTURE)

    def test_strip_level6_preserves_all_other_bytes_and_counts(self):
        l6 = struct.pack(">IB4H", 8, 6, 1000, 1, 1500, 400)
        with_l6 = CAPTURE[:70] + bytes([10]) + CAPTURE[71:] + l6
        self.assertEqual(parse_dm(with_l6)["extensions"][-1]["fields"], {
            "max_display_mastering_luminance": 1000,
            "min_display_mastering_luminance": 1,
            "max_content_light_level": 1500,
            "max_frame_average_light_level": 400,
        })
        self.assertEqual(strip_level6(with_l6), CAPTURE)

    def test_every_truncation_of_capture_is_rejected(self):
        for length in range(len(CAPTURE)):
            with self.subTest(length=length), self.assertRaises(DMError):
                parse_dm(CAPTURE[:length])

    def test_raw_rpu_and_annex_b_are_rejected(self):
        # HEVC UNSPEC62 wrapper, Annex-B variants and bare RPU prefix.
        for prefix in (b"\x7c\x01\x19", b"\0\0\0\1\x7c\x01\x19",
                       b"\0\0\1\x7c\x01\x19", bytes.fromhex("190809004061b6506e700003")):
            with self.subTest(prefix=prefix.hex()), self.assertRaises(DMError):
                parse_dm(prefix + bytes(235 - len(prefix)))

    def test_compressed_and_previous_frame_are_explicitly_rejected(self):
        for kwargs in ({"compressed": True}, {"use_prev_rpu": True}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(DMError, "prior-frame state"):
                parse_dm(CAPTURE, **kwargs)

    def test_trailing_bytes_and_wrong_count_are_rejected(self):
        for bad in (CAPTURE + b"\0", CAPTURE[:70] + b"\x08" + CAPTURE[71:],
                    CAPTURE[:70] + b"\x0a" + CAPTURE[71:]):
            with self.assertRaises(DMError):
                parse_dm(bad)

    def test_raw_rpu_block_width_and_unknown_blocks_are_rejected(self):
        for length, level in ((5, 1), (6, 99), (18, 9)):
            bad = CAPTURE[:70] + b"\x01" + struct.pack(">IB", length, level) + bytes(length)
            with self.subTest(level=level, length=length), self.assertRaises(DMError):
                parse_dm(bad)

    def test_minimal_uncompressed_base_and_invalid_bit_depth(self):
        base = CAPTURE[:70] + b"\0"
        self.assertEqual(parse_dm(base)["extensions"], [])
        for depth in (0, 7, 17, 255):
            bad = bytearray(base)
            bad[60] = depth
            with self.subTest(depth=depth), self.assertRaises(DMError):
                parse_dm(bytes(bad))

    def test_oversized_input_is_rejected(self):
        with self.assertRaises(DMError):
            parse_dm(CAPTURE + bytes(595 - len(CAPTURE)))

    def test_cli_hex_input_and_existing_output_refusal(self):
        script = Path(__file__).with_name("hdmi_dm.py")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "capture.hex"
            output = Path(tmp) / "filtered.bin"
            source.write_text(CAPTURE.hex())
            command = [sys.executable, str(script), str(source), "--hex-input",
                       "--strip-level6", str(output)]
            first = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(first.stdout)["bytes"], 181)
            self.assertEqual(output.read_bytes(), CAPTURE)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), CAPTURE)


if __name__ == "__main__":
    unittest.main()
