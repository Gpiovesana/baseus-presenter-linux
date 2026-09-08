"""Valida a integração do botão físico com a gravação validada pelo áudio."""
import copy
import io
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
import baseus_app
from app.audio import AudioThread
from app.config import Config, DEFAULT_CONFIG
from app.hardware import HardwareReader
from app.overlay import PointerWindow


class TestRecordingWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_clique_apos_falha_usa_estado_real_e_preserva_aviso(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Config(copy.deepcopy(DEFAULT_CONFIG))
            config.set("save_dir", directory)
            audio = AudioThread(config)
            hardware = HardwareReader(config=config)
            overlay = PointerWindow(config)
            self.addCleanup(overlay.deleteLater)

            ready_path = os.path.join(directory, "startup-ready")

            def exercise():
                with open(ready_path, encoding="utf-8") as stream:
                    self.assertEqual(stream.read(), "")
                self.app.processEvents()
                with open(ready_path, encoding="utf-8") as stream:
                    self.assertEqual(stream.read(), str(os.getpid()))
                hardware.record_toggled.emit(True)
                self.assertFalse(audio.is_recording)
                self.assertFalse(overlay.is_recording)
                self.assertIn("ausente", overlay.subtitle_text)
                audio.model = object()
                # O hardware alterna seu booleano mesmo quando a primeira
                # tentativa falhou. Ainda assim, o próximo clique deve gravar.
                hardware.record_toggled.emit(False)
                self.assertTrue(audio.is_recording)
                self.assertTrue(overlay.is_recording)
                audio._fail_active_recording("falha de escrita")
                self.assertFalse(overlay.is_recording)
                self.assertEqual(overlay.subtitle_text, "falha de escrita")
                return 0

            with mock.patch.dict(os.environ, {"BASEUS_UPDATE_READY_FILE": ready_path}), \
                 mock.patch.object(baseus_app, "acquire_single_instance_lock", return_value=(io.StringIO(), "unused")), \
                 mock.patch.object(baseus_app, "QApplication") as app_type, \
                 mock.patch.object(baseus_app, "Config", return_value=config), \
                 mock.patch.object(baseus_app, "HardwareReader", return_value=hardware), \
                 mock.patch.object(baseus_app, "AudioThread", return_value=audio), \
                 mock.patch.object(baseus_app, "PointerWindow", return_value=overlay), \
                 mock.patch.object(baseus_app, "MainWindow"), \
                 mock.patch.object(baseus_app, "TrayIcon"), \
                 mock.patch.object(baseus_app, "UpdateChecker"), \
                 mock.patch.object(hardware, "start"), \
                 mock.patch.object(audio, "start"), \
                 mock.patch.object(overlay, "show"):
                app_type.return_value.exec_.side_effect = exercise
                with self.assertRaises(SystemExit) as result:
                    baseus_app.main()
                self.assertEqual(result.exception.code, 0)
