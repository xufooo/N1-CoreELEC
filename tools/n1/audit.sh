#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p output sources/n1-audit .work/n1-audit
exec > >(tee output/audit.log) 2>&1
python3 tools/n1/test_packages.py -v
kernel_sha=50c8e8154c5aba3c7cd8438d04dd5fdd51733e41
archive="$PWD/sources/n1-audit/linux-${kernel_sha}.tar.gz"
if [ ! -f "$archive" ]; then
  curl --fail --location --retry 3 \
    "https://codeload.github.com/CoreELEC/linux-amlogic/tar.gz/${kernel_sha}" -o "${archive}.tmp"
  mv "${archive}.tmp" "$archive"
fi
printf '%s  %s\n' 9f030d7beac6cb11fd59127e35c5f348875d8f3c68c0de76ee68fe47ca3aa238 "$archive" | sha256sum -c -
kernel_dir="$PWD/.work/n1-audit/linux-amlogic-${kernel_sha}"
test ! -e "$kernel_dir" || { echo 'Use a fresh audit source directory.' >&2; exit 1; }
tar -xzf "$archive" -C .work/n1-audit
python3 tools/n1/audit_sources.py "$kernel_dir"
cpp -nostdinc -undef -D__DTS__ -x assembler-with-cpp \
  -I "$kernel_dir/include" -I "$kernel_dir/arch/arm64/boot/dts/amlogic" \
  "$kernel_dir/arch/arm64/boot/dts/amlogic/coreelec-gxl/meson_gxl_s905d_phicomm_n1.dts" \
  > output/n1.dts.preprocessed
dtc -I dts -O dtb -o output/n1.dtb output/n1.dts.preprocessed
test "$(fdtget -t s output/n1.dtb / coreelec-dt-id)" = meson_gxl_s905d_phicomm_n1
mkimage -A arm64 -O linux -T script -C none \
  -d projects/Amlogic-ce/devices/Amlogic-ng/bootloader/scripts/s905_autoscript.src \
  output/s905_autoscript
dumpimage -l output/s905_autoscript
git rev-parse HEAD > output/audit-commit.txt
printf '%s\n' 'Source/package checks and actual DTB/autoscript compilation passed.'
printf '%s\n' 'This is not a kernel/Kodi/firmware build or device playback test.'
