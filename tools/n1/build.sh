#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
case "${1:-image}" in
  image|toolchain) target=${1:-image};;
  kernel) target=kernel;;
  *) echo 'Use image, toolchain or kernel' >&2; exit 2;;
esac
test "$(uname -s)" = Linux || { echo 'Build requires a Linux host.' >&2; exit 1; }
test "$(id -u)" != 0 || { echo 'Do not build as root.' >&2; exit 1; }

export PROJECT=Amlogic-ce DEVICE=Amlogic-ng ARCH=arm N1_BUILD=yes
export CCACHE_DIR="$PWD/.ccache" AUTOREMOVE=yes
export THREADCOUNT=2 CONCURRENCY_MAKE_LEVEL=4 CONCURRENCY_LOAD=6
export CUSTOM_VERSION=21.3-Omega-N1-r1
export BUILDER_NAME=xufooo BUILDER_VERSION="$(git rev-parse --short=12 HEAD)"
mkdir -p output .coreelec
printf '%s\n' 'CCACHE_CACHE_SIZE="2G"' > .coreelec/options

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
    'variant': 'baseline', 'dolby_vision_patches': True,
    'kernel_compiled': os.environ.get('BUILD_TARGET') in ('kernel', 'image'),
    'dolby_vision_patch_stack': ['linux-20-tv-led-dolby-vision-injection.patch'],
    'dolby_vision_variant': 'tv-led', 'dolby_vision_device_tested': False,
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
else
  make image 2>&1 | tee output/build.log
fi
