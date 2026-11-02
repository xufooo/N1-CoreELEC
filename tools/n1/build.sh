#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
case "${1:-image}" in
  image|toolchain) target=${1:-image};;
  kernel) target=kernel;;
  *) echo 'Use image, toolchain or kernel' >&2; exit 2;;
esac
export N1_REQUESTED_TARGET="$target"
test "$(uname -s)" = Linux || { echo 'Build requires a Linux host.' >&2; exit 1; }
test "$(id -u)" != 0 || { echo 'Do not build as root.' >&2; exit 1; }

export PROJECT=Amlogic-ce DEVICE=Amlogic-ng ARCH=arm N1_BUILD=yes
export N1_IMAGE_ONLY=yes
export CCACHE_DIR="$PWD/.ccache" AUTOREMOVE=yes
export THREADCOUNT=2 CONCURRENCY_MAKE_LEVEL=4 CONCURRENCY_LOAD=6
export CUSTOM_VERSION=21.3-Omega-N1-r1
export BUILDER_NAME=N1 BUILDER_VERSION="$(git rev-parse --short=12 HEAD)"
mkdir -p output .coreelec
printf '%s\n' 'CCACHE_CACHE_SIZE="2G"' > .coreelec/options

# Run the bounded host regressions before spending time on cross compilation.
python3 -m unittest discover -s tools/n1 -p 'test_*.py' -v 2>&1 | tee output/preflight-tests.log

python3 - <<'PY'
import json, os, pathlib, subprocess
commit = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
manifest = {
    'upstream_tag': '21.3-Omega',
    'upstream_commit': 'fc61125e8900ab0c2593a29b615980ed0cd5b939',
    'source_commit': commit,
    'kernel_commit': '50c8e8154c5aba3c7cd8438d04dd5fdd51733e41',
    'kodi_commit': 'acc0fc66bc6af69c31a93c5d17e36900343263b7',
    'project': 'Amlogic-ce', 'device': 'Amlogic-ng', 'board': 'Phicomm_N1',
    'variant': 'baseline-with-default-off-dv-experiment', 'dolby_vision_patches': True,
    'build_target': os.environ['N1_REQUESTED_TARGET'],
    'update_archive_requested': False,
    'build_status': 'running', 'kernel_compiled': False,
    'dolby_vision_patch_stack': ['linux-20-tv-led-dolby-vision-injection.patch'],
    'dolby_vision_variant': 'manual-hdmi-dm-injection-experiment',
    'dolby_vision_p5_reshaping': False,
    'dolby_vision_automatic_frame_metadata': False,
    'dolby_vision_device_tested': False,
    'device_boot_tested': False, 'playback_tested': False,
}
pathlib.Path('output/source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
PY

start=$(date +%s)
(
  while :; do
    date -u +%FT%TZ
    df -Pk .
    free -m
    sleep 60
  done
) > output/resources.log &
monitor_pid=$!
finish() {
  result=$?
  trap - EXIT
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
  printf 'exit_code=%s\nelapsed_seconds=%s\n' "$result" "$(( $(date +%s) - start ))" > output/result.txt
  N1_BUILD_RESULT="$result" python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path('output/source-manifest.json')
manifest = json.loads(path.read_text())
passed = os.environ['N1_BUILD_RESULT'] == '0'
manifest['build_status'] = 'success' if passed else 'failed'
manifest['kernel_compiled'] = passed and manifest['build_target'] in ('kernel', 'image')
path.write_text(json.dumps(manifest, indent=2) + '\n')
PY
  # Preserve the detailed package errors without archiving source/object trees.
  if [ -d build.CoreELEC-Amlogic-ng.arm-21/.threads ]; then
    tar -czf output/package-logs.tar.gz -C build.CoreELEC-Amlogic-ng.arm-21 .threads
  fi
  exit "$result"
}
trap finish EXIT
if [ "$target" = toolchain ]; then
  ./scripts/build toolchain 2>&1 | tee output/build.log
elif [ "$target" = kernel ]; then
  # Fast validation of the kernel patch stack: build only the NG kernel
  # package (and its dependencies), not the whole image.
  ./scripts/build linux 2>&1 | tee output/build.log
  # Publish the kernel image so it can be dropped straight onto
  # /flash/kernel.img on the device instead of reflashing a full image.
  kernel_img=$(find build.CoreELEC-Amlogic-ng.arm-21 -type f \
      \( -path "*/.image/Image*" -o -path "*/arch/arm64/boot/Image*" \) \
      2>/dev/null | head -1 || true)
  if [ -n "${kernel_img:-}" ]; then
    echo "kernel image: ${kernel_img}" | tee -a output/build.log
    cp "$kernel_img" output/kernel.img
    (cd output && md5sum -t kernel.img > kernel.img.md5)
  else
    echo "ERROR: kernel build produced no publishable Image" | tee -a output/build.log
    exit 1
  fi
else
  make image 2>&1 | tee output/build.log
fi
