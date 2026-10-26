# Phicomm N1: sources and patch decisions

Date: 2026-10-26. This fork targets the physical Phicomm N1, S905D/GXL, 2 GB RAM.

## Fixed baseline

- CoreELEC `21.3-Omega`: `fc61125e8900ab0c2593a29b615980ed0cd5b939`.
- Vendor kernel 4.9: `50c8e8154c5aba3c7cd8438d04dd5fdd51733e41`.
- Kodi: `acc0fc66bc6af69c31a93c5d17e36900343263b7`.
- Build: `PROJECT=Amlogic-ce DEVICE=Amlogic-ng ARCH=arm N1_BUILD=yes`.
- This is a community USB baseline, not official N1 certification.

## Reviewed community changes

| Source | Decision | Reason / remaining evidence |
|---|---|---|
| [Damenly N1 port](https://github.com/Damenly/coreelec/commit/53b9f488a97ecb5b4c5c9c80234d1499d41ccce4), originally RuralHunter | Port DTB, raw Image, external uInitrd, USB boot and update-file handling | Keep the 21.3 kernel. Register the DTS in the normal kernel dtbs build; package its installed result without recompiling or mutating the kernel from a bootloader package. |
| [Damenly boot cleanup](https://github.com/Damenly/coreelec/commit/5db8e8f1195305fbb1b47bd7e5509dca876f3257) | Port readable USB loop only | First image is USB-only. No saved environment changes, internal partition search or fallback to an unrelated stock DTB. |
| [RuralHunter default settings](https://github.com/Damenly/coreelec/commit/11a6f93fb4954f43533c55ea05c88925a251cabb) | Do not force SMB1 or YCbCr 4:2:2 globally | These are old compatibility defaults, not universal N1 fixes. Evaluate against the actual display/NAS. |
| Driver list/kernel-config changes bundled with the 2023 port | Retain official 21.3 choices | Avoid reverting modern drivers or importing router/netfilter/JRE changes unrelated to the playback baseline. |
| [Damenly 21.0](https://github.com/Damenly/coreelec/releases/tag/21.0-Omega-Phicomm-N1) | Use source as adaptation reference | Author labels image untested and disables installtoemmc; no blanket stability claim. |
| [joyo1](https://www.right.com.cn/forum/thread-8427049-1-1.html) | Track MAC, NTFS, Bluetooth confirm key and audio-after-passthrough as device acceptance items | Published behavior/claims are not an attributable source patch. Do not replace 21.3 components with extracted binaries or copy a fixed MAC from another box. |
| IPTV, Docker, Xiaoya integrations | Leave optional | Not needed to reproduce or diagnose local/NAS playback. |

## Dolby Vision research

- [Experimental P5 build and feedback](https://discourse.coreelec.org/t/dolby-vision-for-all-socs/57985).
- Public repositories: [CoreELEC](https://github.com/doppingkoala/CoreELEC), [Kodi](https://github.com/doppingkoala/xbmc), [common_drivers](https://github.com/doppingkoala/common_drivers).
- `doppingkoala/xbmc:dv-doppingkoala-21.2` = `cd832d4fdf54498d358011c4aa091f83cd50a905`; comparison against the author's `aml-4.9-21.2` shows **one skin change**, not the complete DV implementation. A branch name alone is not proof of usable P5 code.
- `public_dv_pov` = `ce7c6c62d228147b5ebd59548298ac254125e66d`, message `poc`; inspect the actual diff and kernel dependencies before any backport.
- Default public CE fork points at `coreelec-22`, not our NG baseline.
- Still to establish: exact source/commit set corresponding to the December 2025 P5 binary, N1 applicability, and TV-led output vs P5-to-HDR10/SDR color conversion.
- Baseline does not claim P5 correction, native DV output, or FEL reconstruction.

## User's existing USB

Read-only inspection found a kernel build path for CoreELEC 9.2.7 Phicomm N1,
Linux 3.14.29, built 2021-03-16. Both KERNEL and SYSTEM matched their supplied
MD5 files. This is not a boot/playback test or a complete USB backup.
Do not overwrite that working USB while testing this fork.
