# DV metadata host verification

Host-only (no device, no kernel image) verification of the Dolby Vision
metadata path used by the N1 TV-led injection patch:

```
UHD RPU (upstream test asset)
    -> pinned dovi_tool fork  (parse -> Kodi-equivalent convert -> write)
    -> Kodi DM conversion patch semantics (profile 7 -> To81, others untouched)
    -> DM bytes
    -> kernel dv_injection_validate_metadata / pack_bytes / expand_pixels
    -> 128-byte packets -> 1 bit per pixel injection words
    -> independent checker (CRC-32/MPEG-2, padding, type sequence, pixel decode)
```

Everything runs in `.github/workflows/dv-metadata-host-verify.yml`
(`workflow_dispatch` only, so pushing never starts a firmware build).

## Pieces

| file | role |
|---|---|
| `forkprobe/` | Rust crate that links the pinned fork and drives it exactly like the Kodi patch does |
| `split_kernel_patch.py` | extracts `dv_injection.c` out of the repository patch |
| `extract_kernel_harness.py` | generates a host harness that calls the *real* kernel helpers, copying every `#define DV_INJ_*` and the packet-type enum from that source |
| `build_dm.py` | Python port of the fork's DM serializer, used only to localise a disagreement |
| `verify_packets.py` | independent packet/CRC/pixel checker (re-derives the rules from the reference implementation) |
| `check_fork_run.py` | refuses a fork run that parsed nothing or converted no profile-7 frame |
| `run_verify.py` | orchestrates the groups G1..G6 and writes `summary.json` / `verify.log` |

## What a green run does and does not mean

Established: the fork's own bytes are internally consistent (`0xFF || DM`,
`7C 01` + escaping round trip), the kernel accepts and packetises the DM the
Kodi patch actually produces, packet boundaries and CRCs match an independent
implementation, and the pixel words reproduce the packets.

Not established: that a TV accepts these pixels, that the HDMI link carries
them, or that the OSD canvas write reaches the wire. Those need the device.

## Known defect recorded by G5

The fork writes a 17-byte level-9 block while declaring 18; the kernel table
only accepts 1. Both current behaviours are reported as `KNOWN_DEFECT`, not as
passes. Fixing it needs a paired producer + kernel change, not a one-sided
relaxation.
