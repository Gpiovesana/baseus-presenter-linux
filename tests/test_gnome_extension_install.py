import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.gnome_extension import FILES, UUID, install_extension


class TestGnomeExtensionInstall(unittest.TestCase):
    def test_install_update_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).resolve().parents[1] / 'extensions' / UUID
            dest = Path(directory) / 'extensions' / UUID
            self.assertIsNone(install_extension(source, dest))
            for name in FILES:
                self.assertEqual((dest / name).read_bytes(), (source / name).read_bytes())
            self.assertIsNone(install_extension(source, dest))
            (dest / 'renderer.js').write_text('old renderer')
            backup = install_extension(source, dest)
            self.assertEqual(backup.parent, Path(directory) / 'baseus-extension-backups')
            self.assertEqual((backup / 'renderer.js').read_text(), 'old renderer')

    def test_wrong_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).resolve().parents[1] / 'extensions' / UUID
            dest = Path(directory) / 'extensions' / UUID
            dest.mkdir(parents=True)
            (dest / 'metadata.json').write_text(json.dumps({'uuid': 'other'}))
            with self.assertRaises(ValueError):
                install_extension(source, dest)
            self.assertEqual(json.loads((dest / 'metadata.json').read_text())['uuid'], 'other')

    def test_failed_replace_restores_existing_version(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).resolve().parents[1] / 'extensions' / UUID
            dest = Path(directory) / 'extensions' / UUID
            install_extension(source, dest)
            (dest / 'renderer.js').write_text('previous version')
            with mock.patch('app.gnome_extension.os.replace', side_effect=OSError('simulated')):
                with self.assertRaises(OSError):
                    install_extension(source, dest)
            self.assertEqual((dest / 'renderer.js').read_text(), 'previous version')
