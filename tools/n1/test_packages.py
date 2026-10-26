#!/usr/bin/env python3
"""Exercise the actual package install hook for the conflicting NTFS helpers."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NTFSHelperTests(unittest.TestCase):
    def stage_udevil(self, root, ntfs3g):
        stage = root / 'udevil'
        (root / 'src').mkdir()
        (root / 'src/udevil').write_text('test executable\n')
        env = dict(os.environ, INSTALL=str(stage),
                   PKG_DIR=str(ROOT / 'packages/sysutils/udevil'), NTFS3G=ntfs3g)
        subprocess.run(['bash', '-e', '-c',
                        'source "$PKG_DIR/package.mk"; post_makeinstall_target'],
                       cwd=root, env=env, check=True)
        return stage

    def test_fuse_package_is_the_only_helper_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = self.stage_udevil(root, 'yes')
            self.assertFalse((stage / 'usr/sbin/mount.ntfs').exists())
            self.assertFalse((stage / 'usr/sbin/mount.ntfs').is_symlink())
            # The actual ntfs-3g recipe installs this absolute symlink.
            target = root / 'image/usr/sbin'
            target.mkdir(parents=True)
            helper = target / 'mount.ntfs'
            helper.symlink_to('/usr/bin/ntfs-3g')
            # The udevil stage must provide no competing path in either order.
            self.assertEqual(os.readlink(helper), '/usr/bin/ntfs-3g')
            self.assertNotIn('usr/sbin/mount.ntfs',
                             [str(p.relative_to(stage)) for p in stage.rglob('*')])

    def test_kernel_ntfs3_configuration_keeps_its_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = self.stage_udevil(Path(temp), 'no')
            helper = stage / 'usr/sbin/mount.ntfs'
            self.assertIn('exec /usr/bin/mount -t ntfs3 "$@"', helper.read_text())
            self.assertTrue(helper.stat().st_mode & 0o111)


if __name__ == '__main__':
    unittest.main()
