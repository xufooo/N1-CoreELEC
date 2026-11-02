#!/usr/bin/env python3
"""Exercise the real release-tar staging block without building a firmware."""
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ImageDeliveryTests(unittest.TestCase):
    def stage(self, n1, image_only, mode):
        source = (ROOT / 'scripts/image').read_text()
        block = source.split('  # Remove any previously created release tarballs\n', 1)[1]
        block = block.split('  # Create image files if requested\n', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            stage = target / 'sample'
            stage.mkdir(parents=True)
            (stage / 'payload').write_bytes(b'image staging must survive')
            tools = root / 'bin'
            tools.mkdir()
            if not shutil.which('sha256sum'):
                shim = tools / 'sha256sum'
                shim.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n')
                shim.chmod(0o755)
            env = dict(os.environ, TARGET_IMG=str(target), IMAGE_NAME='sample',
                       N1_BUILD=n1, N1_IMAGE_ONLY=image_only, N1_TEST_MODE=mode,
                       PATH=str(tools) + os.pathsep + os.environ['PATH'])
            subprocess.run(['bash', '-e', '-c', 'set -- "$N1_TEST_MODE"\n' + block],
                           cwd=root, env=env, check=True)
            self.assertEqual((stage / 'payload').read_bytes(), b'image staging must survive')
            archive = target / 'sample.tar'
            if n1 == 'yes' and image_only == 'yes' and mode == 'mkimage':
                self.assertFalse(archive.exists())
                self.assertFalse((target / 'sample.tar.sha256').exists())
            else:
                with tarfile.open(archive) as opened:
                    self.assertEqual(opened.extractfile('sample/payload').read(),
                                     b'image staging must survive')
                self.assertTrue((target / 'sample.tar.sha256').exists())

    def test_n1_image_only_keeps_staging_without_update_archive(self):
        self.stage('yes', 'yes', 'mkimage')

    def test_non_n1_release_behavior_is_preserved(self):
        self.stage('no', 'yes', 'mkimage')

    def test_explicit_release_and_legacy_n1_keep_update_archive(self):
        self.stage('yes', 'yes', 'release')
        self.stage('yes', '', 'mkimage')


if __name__ == '__main__':
    unittest.main()
