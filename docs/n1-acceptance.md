# N1 acceptance

Record each level separately; a CI check must not mark a device check passed.

1. Source and configuration: fixed upstream commits, readable patches, no upstream
   version downgrade, only N1 image selected.
2. Real compilation: compiler/linker finish, disk/time evidence retained.
3. Packed firmware: raw arm64 kernel, correct N1 DTB, uInitrd and autoscript,
   resolved per-image UUIDs, SYSTEM version, matching update archive and hashes.
4. N1 USB boot: correct model/kernel/version, both USB ports/keyboard where
   applicable, DHCP and unique Ethernet/Wi-Fi MACs, Wi-Fi and Bluetooth, remote
   confirmation key, NTFS disk, cold boot/reboot. Test updates only between this
   fork's USB versions after an independent backup; no legacy 9.2 in-place claim.
5. Baseline playback: H.264/HEVC SDR, HDR10, automatic refresh rate, long NAS
   playback, seek, pause/resume, subtitles, passthrough and sound after exit.
6. DV experiment: obtain MediaInfo and display model/capability first. Test P5,
   P8.1 and P7 MEL separately. Compare color to a known-correct decoder/output,
   verify clipping/black level, subtitle/OSD, seek and A/V sync. A TV's DV logo
   alone is not proof of correct reshaping or image quality. P7 FEL remains out
   of the initial target.

Current device/display checks: **not performed**. The user's original USB has
not been modified. Do not publish this as a verified playback release.
