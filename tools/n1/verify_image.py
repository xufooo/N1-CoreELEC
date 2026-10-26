#!/usr/bin/env python3
"""Check actual packed N1 firmware; this is not a device boot/playback test."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile


def run(*args):
    return subprocess.check_output(args)


def verify(target):
    images = list(target.glob('*Phicomm_N1.img.gz'))
    archives = list(target.glob('*.tar'))
    if len(images) != 1 or len(archives) != 1:
        raise ValueError(f'Expected one N1 image and one update archive: {images}, {archives}')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        image = tmp / 'disk.img'
        with gzip.open(images[0], 'rb') as src, image.open('wb') as dst:
            import shutil
            shutil.copyfileobj(src, dst)
        with image.open('rb') as src:
            mbr = src.read(512)
        if mbr[510:512] != b'\x55\xaa':
            raise ValueError('Missing MBR signature')
        offset = struct.unpack_from('<I', mbr, 446 + 8)[0] * 512
        fat = f'{image}@@{offset}'
        for name in ('kernel.img', 'SYSTEM', 'uInitrd', 'dtb.img', 'boot.ini', 's905_autoscript'):
            run('mcopy', '-i', fat, f'::{name}', str(tmp / name))
        boot = (tmp / 'boot.ini').read_text()
        if '@' in boot or 'boot=UUID=' not in boot or 'disk=UUID=' not in boot:
            raise ValueError('Unresolved or non-UUID N1 boot configuration')
        kernel = (tmp / 'kernel.img').read_bytes()
        if kernel[56:60] != b'ARM\x64' or len(kernel) >= 0x2000000:
            raise ValueError('Not a raw arm64 kernel or overlaps N1 ramdisk load address')
        run('dumpimage', '-l', str(tmp / 'uInitrd'))
        run('dumpimage', '-l', str(tmp / 's905_autoscript'))
        dt_id = run('fdtget', '-t', 's', str(tmp / 'dtb.img'), '/', 'coreelec-dt-id').decode().strip()
        if dt_id != 'meson_gxl_s905d_phicomm_n1':
            raise ValueError(f'Unexpected DTB: {dt_id}')
        release = run('unsquashfs', '-cat', str(tmp / 'SYSTEM'), 'etc/os-release').decode()
        if '21.3-Omega-N1-r1' not in release:
            raise ValueError(f'Unexpected system version: {release}')
        # NG has no ntfs3 kernel driver: the final image must use ntfs-3g.
        listing = run('unsquashfs', '-ll', str(tmp / 'SYSTEM'), 'usr/sbin/mount.ntfs').decode()
        if '-> /usr/bin/ntfs-3g' not in listing:
            raise ValueError(f'Wrong NTFS helper in final image: {listing}')
        run('unsquashfs', '-cat', str(tmp / 'SYSTEM'), 'usr/bin/ntfs-3g')
        hwdb = run('unsquashfs', '-cat', str(tmp / 'SYSTEM'),
                   'usr/lib/udev/hwdb.d/70-local-keyboard.hwdb').decode()
        if 'evdev:input:b0005v0416p0300*\n KEYBOARD_KEY_c0041=enter' not in hwdb:
            raise ValueError('Missing built-in YYYKQ remote confirm-key mapping')
        with tarfile.open(archives[0]) as archive:
            names = archive.getnames()
            for suffix in ('/target/KERNEL', '/target/SYSTEM', '/3rdparty/bootloader/uInitrd',
                           '/3rdparty/bootloader/s905_autoscript', '/3rdparty/bootloader/Phicomm_N1_boot.ini',
                           '/3rdparty/bootloader/Phicomm_N1_dtb.img'):
                if not any(n.endswith(suffix) for n in names):
                    raise ValueError(f'Update archive missing {suffix}')
        checksums = []
        for path in (images[0], archives[0]):
            with path.open('rb') as src:
                digest = hashlib.file_digest(src, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else None
            if digest is None:
                sha = hashlib.sha256()
                with path.open('rb') as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b''):
                        sha.update(chunk)
                digest = sha.hexdigest()
            checksums.append(f'{digest}  {path.name}\n')
        (target / 'SHA256SUMS.sha256').write_text(''.join(checksums))
        Path('output/firmware-verification.json').write_text(json.dumps({
            'packed_image_verified': True, 'dt_id': dt_id,
            'device_boot_tested': False, 'playback_tested': False,
        }, indent=2) + '\n')
    print('Packed N1 image and update archive verified. Device tests still required.')


if __name__ == '__main__':
    verify(Path(sys.argv[1] if len(sys.argv) > 1 else 'target'))
