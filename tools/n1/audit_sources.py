#!/usr/bin/env python3
"""Apply the selected NG kernel patch stack and verify inspected source paths."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
KERNEL = Path(sys.argv[1]).resolve()
DEVICE = ROOT / 'projects/Amlogic-ce/devices/Amlogic-ng'

# Order matches scripts/unpack for the NG project's package override. No
# 'default' kernel patches are selected because PKG_PATCH_DIRS=amlogic-4.9.
dirs = [ROOT / 'projects/Amlogic-ce/packages/linux/patches',
        ROOT / 'projects/Amlogic-ce/packages/linux/patches/amlogic-4.9',
        ROOT / 'projects/Amlogic-ce/patches/linux',
        ROOT / 'projects/Amlogic-ce/patches/linux/arm',
        ROOT / 'projects/Amlogic-ce/patches/linux/amlogic-4.9',
        DEVICE / 'patches/linux/amlogic-4.9',
        DEVICE / 'patches/linux']
patches = [p for d in dirs for p in sorted(d.glob('*.patch'))]
applied = []
for patch in patches:
    subprocess.run(['patch', '-p1', '-t', '-N', '-i', str(patch)], cwd=KERNEL, check=True)
    applied.append(str(patch.relative_to(ROOT)))

wifi = (KERNEL / 'drivers/amlogic/wifi/wifi_dt.c').read_text()
eth = (KERNEL / 'drivers/net/ethernet/stmicro/stmmac/stmmac_platform.c').read_text()
if '__setup("mac_wifi=", mac_addr_set)' not in wifi or '__setup("mac=", mac_addr_set)' not in eth:
    raise ValueError('Expected factory MAC command-line consumers missing')
if (KERNEL / 'fs/ntfs3').exists():
    raise ValueError('NTFS source assumption changed: re-audit mount helper choice')
hwdb = (ROOT / 'packages/sysutils/systemd/hwdb.d/70-local-keyboard.hwdb').read_text()
if 'evdev:input:b0005v0416p0300*\n KEYBOARD_KEY_c0041=enter' not in hwdb:
    raise ValueError('Missing upstream YYYKQ confirmation mapping')
report = {'patches_applied': applied, 'factory_mac_consumers_present': True,
          'yyykq_mapping_already_upstream': True, 'ng_kernel_has_ntfs3': False,
          'kernel_compiled': False, 'device_tested': False}
(ROOT / 'output').mkdir(exist_ok=True)
(ROOT / 'output/source-audit.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
