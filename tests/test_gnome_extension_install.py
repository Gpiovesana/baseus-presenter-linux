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

class TestAutomaticPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict('os.environ', {
            'XDG_CURRENT_DESKTOP': 'zorin:GNOME',
            'XDG_DATA_HOME': self.temp.name,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.runner = mock.patch('app.gnome_extension.subprocess.run')
        self.run = self.runner.start()
        self.addCleanup(self.runner.stop)
        def run(args, **kwargs):
            from subprocess import CompletedProcess
            output = 'GNOME Shell 46.0' if args[0] == 'gnome-shell' else ''
            if args[0] == 'gdbus':
                output = "(':1.20',)"
            if args[:2] == ['gsettings', 'get']:
                output = "['another@extension']"
            return CompletedProcess(args, 0, output, '')
        self.run.side_effect = run

    def test_install_uses_xdg_and_second_start_needs_no_logout(self):
        from app.gnome_extension import prepare_wayland_extension
        self.assertIn('sessão', prepare_wayland_extension())
        self.assertTrue((Path(self.temp.name) / 'gnome-shell/extensions' / UUID / 'renderer.js').is_file())
        self.assertIn('sessão', prepare_wayland_extension())
        original = self.run.side_effect
        def next_session(args, **kwargs):
            result = original(args, **kwargs)
            if args[0] == 'gdbus':
                result.stdout = "(':1.42',)"
            return result
        self.run.side_effect = next_session
        self.assertIsNone(prepare_wayland_extension())

    def test_unsupported_shell_does_not_install(self):
        from app.gnome_extension import prepare_wayland_extension
        self.run.return_value = mock.Mock(stdout='GNOME Shell 47.0', returncode=0)
        self.run.side_effect = None
        self.assertIn('46', prepare_wayland_extension())
        self.assertFalse((Path(self.temp.name) / 'gnome-shell').exists())

    def test_other_compositor_does_not_run_commands(self):
        from app.gnome_extension import prepare_wayland_extension
        with mock.patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': 'KDE'}):
            self.assertIn('GNOME', prepare_wayland_extension())
        self.run.assert_not_called()

    def test_missing_commands_returns_actionable_warning(self):
        from app.gnome_extension import prepare_wayland_extension
        self.run.side_effect = FileNotFoundError('gnome-shell')
        self.assertIn('preparar', prepare_wayland_extension())

    def test_undiscovered_extension_preserves_other_enabled_extensions(self):
        from app.gnome_extension import prepare_wayland_extension
        original = self.run.side_effect
        def run(args, **kwargs):
            result = original(args, **kwargs)
            if args[0] == 'gnome-extensions':
                result.returncode = 1
            return result
        self.run.side_effect = run
        self.assertIn('sessão', prepare_wayland_extension())
        writes = [call.args[0] for call in self.run.call_args_list
                  if call.args[0][:2] == ['gsettings', 'set']]
        self.assertEqual(len(writes), 1)
        self.assertIn('another@extension', writes[0][-1])
        self.assertIn(UUID, writes[0][-1])

    def test_damaged_existing_metadata_warns_without_overwriting(self):
        from app.gnome_extension import prepare_wayland_extension
        destination = Path(self.temp.name) / 'gnome-shell/extensions' / UUID
        destination.mkdir(parents=True)
        for metadata in ('{}', '[]', 'null', '{broken'):
            with self.subTest(metadata=metadata):
                (destination / 'metadata.json').write_text(metadata)
                warning = prepare_wayland_extension()
                self.assertIn('preparar', warning)
                self.assertEqual((destination / 'metadata.json').read_text(), metadata)

    def test_reload_warning_and_internal_errors_are_translated(self):
        from app import i18n
        from app.gnome_extension import prepare_wayland_extension
        with mock.patch.object(i18n, '_translator', None), \
                mock.patch.object(i18n, '_language', 'en'):
            self.assertIn('log out and back in', prepare_wayland_extension())
            original = self.run.side_effect
            def unavailable_shell(args, **kwargs):
                result = original(args, **kwargs)
                if args[0] == 'gdbus':
                    result.returncode = 1
                return result
            self.run.side_effect = unavailable_shell
            warning = prepare_wayland_extension()
            self.assertIn('GNOME Shell is not available in this session', warning)
            self.assertIn('Slide navigation remains available.', warning)
