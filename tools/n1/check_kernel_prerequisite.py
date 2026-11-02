#!/usr/bin/env python3
"""Fail closed if an image's prerequisite did not build the same kernel sources."""
import json
import re
import subprocess
import sys
from pathlib import Path

# Packaging/CI-only changes may follow a kernel build. Runtime source,
# configuration, package recipe and patch selection must still match.
PATHS = (
    'projects/Amlogic-ce/packages/linux',
    'projects/Amlogic-ce/devices/Amlogic-ng/patches/linux',
    'projects/Amlogic-ce/devices/Amlogic-ng/linux/linux.aarch64.conf',
    'projects/Amlogic-ce/devices/Amlogic-ng/options',
    'scripts/build', 'scripts/unpack',
)


def check(run, manifest):
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        raise ValueError('Prerequisite kernel run has not succeeded')
    revision = run.get('head_sha', '')
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Invalid prerequisite source revision')
    if (manifest.get('source_commit') != revision or
            manifest.get('build_target') != 'kernel' or
            manifest.get('build_status') != 'success' or
            manifest.get('kernel_compiled') is not True):
        raise ValueError('Prerequisite evidence is not a successful kernel build')
    for path in PATHS:
        old = subprocess.check_output(['git', 'rev-parse', f'{revision}:{path}'])
        current = subprocess.check_output(['git', 'rev-parse', f'HEAD:{path}'])
        if old != current:
            raise ValueError(f'Kernel input changed after prerequisite: {path}')
    return revision


if __name__ == '__main__':
    revision = check(json.loads(Path(sys.argv[1]).read_text()),
                     json.loads(Path(sys.argv[2]).read_text()))
    print(f'Prerequisite kernel build passed for unchanged kernel inputs: {revision}')
