#!/usr/bin/env python3
"""Check actual packed N1 firmware; this is not a device boot/playback test."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tarfile
import argparse
import tempfile


def run(*args):
    return subprocess.check_output(args)


def verify(target, image_only=False):
    images = list(target.glob('*.img.gz'))
    archives = list(target.glob('*.tar'))
    expected_archives = 0 if image_only else 1
    if len(images) != 1 or len(archives) != expected_archives:
        raise ValueError(f'Expected one N1 image and {expected_archives} update archives: {images}, {archives}')
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
        if not image_only:
            with tarfile.open(archives[0]) as archive:
                names = archive.getnames()
                for suffix in ('/target/KERNEL', '/target/SYSTEM', '/3rdparty/bootloader/uInitrd',
                               '/3rdparty/bootloader/s905_autoscript', '/3rdparty/bootloader/Phicomm_N1_boot.ini',
                               '/3rdparty/bootloader/Phicomm_N1_dtb.img'):
                    if not any(n.endswith(suffix) for n in names):
                        raise ValueError(f'Update archive missing {suffix}')
        checksums = []
        for path in [images[0], *archives]:
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
            'update_archive_requested': not image_only,
            'device_boot_tested': False, 'playback_tested': False,
        }, indent=2) + '\n')
    print('Packed N1 delivery verified. Device tests still required.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', nargs='?', type=Path, default=Path('target'))
    parser.add_argument('--image-only', action='store_true')
    args = parser.parse_args()
    verify(args.target, image_only=args.image_only)
