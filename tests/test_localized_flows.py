"""Exercise visible messages in both bundled interface languages."""
import copy
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from app import i18n, gnome_extension, uninstall
from app.audio import AudioThread
from app.config import Config, DEFAULT_CONFIG
from app.overlay import PointerWindow
from app.overlay_wayland import WaylandOverlay


class TestLocalizedFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(i18n.install_translator, self.app, "pt")

    def test_status_subtitles_follow_interface_language_on_both_backends(self):
        for language, labels in (
            ("pt", ("[GRAVANDO]", "[PAUSADO]", "[TRADUÇÃO ON]", "[TRADUÇÃO OFF]")),
            ("en", ("[RECORDING]", "[PAUSED]", "[TRANSLATION ON]", "[TRANSLATION OFF]")),
        ):
            i18n.install_translator(self.app, language)
            for backend in (PointerWindow, WaylandOverlay):
                with self.subTest(language=language, backend=backend.__name__):
                    overlay = backend(Config(copy.deepcopy(DEFAULT_CONFIG)))
                    try:
                        if isinstance(overlay, PointerWindow):
                            overlay.timer.stop()
                        else:
                            overlay._send = mock.Mock()
                        for method, state, expected in (
                            ("set_recording", True, labels[0]),
                            ("set_recording", False, labels[1]),
                            ("set_translating", True, labels[2]),
                            ("set_translating", False, labels[3]),
                        ):
                            getattr(overlay, method)(state)
                            text = (overlay.subtitle_text if isinstance(overlay, PointerWindow)
                                    else overlay.state["subtitle"])
                            self.assertEqual(text, expected)
                    finally:
                        overlay.close()

    def test_new_transcription_filename_and_header_follow_interface_language(self):
        with tempfile.TemporaryDirectory() as directory:
            for language, prefix, header in (
                ("pt", "Aula_", "--- Transcrição Iniciada: "),
                ("en", "Lesson_", "--- Transcription Started: "),
            ):
                with self.subTest(language=language):
                    i18n.install_translator(self.app, language)
                    config = Config(copy.deepcopy(DEFAULT_CONFIG))
                    config.set("save_dir", directory)
                    audio = AudioThread(config)
                    audio.model = object()
                    audio.set_recording(True)
                    self.assertTrue(audio.is_recording)
                    path = Path(audio.txt_path)
                    self.assertTrue(path.name.startswith(prefix), path.name)
                    self.assertTrue(path.read_text().startswith(header))

    def test_gnome_warnings_follow_interface_language(self):
        for language, expected in (
            ("pt", "Os efeitos Wayland requerem GNOME 46."),
            ("en", "Wayland effects require GNOME 46."),
        ):
            with self.subTest(language=language):
                i18n.install_translator(self.app, language)
                with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
                    self.assertTrue(gnome_extension.prepare_wayland_extension().startswith(expected))
        i18n.install_translator(self.app, "en")
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}), \
                mock.patch.object(gnome_extension.subprocess, "run", side_effect=FileNotFoundError("gnome-shell")):
            warning = gnome_extension.prepare_wayland_extension()
            self.assertIn("Could not prepare the GNOME extension:", warning)
            self.assertIn("gnome-shell", warning)

    def test_standalone_uninstaller_requires_the_word_shown_in_each_language(self):
        with tempfile.TemporaryDirectory() as directory:
            for language, word in (("pt", "desinstalar"), ("en", "uninstall")):
                for answer in (word.upper(), word.title(), "", "yes", word + " now",
                               "uninstall" if language == "pt" else "desinstalar"):
                    with self.subTest(language=language, answer=answer), \
                            mock.patch.object(i18n, "_translator", None), \
                            mock.patch.object(i18n, "_language", language), \
                            mock.patch.object(uninstall, "configure_standalone"), \
                            mock.patch.object(uninstall, "validate_installation"), \
                            mock.patch.object(uninstall, "UninstallProgress"), \
                            mock.patch.object(uninstall, "remove_installation") as remove, \
                            mock.patch("builtins.input", return_value=answer) as prompt, \
                            mock.patch("sys.stdout", new_callable=io.StringIO), \
                            mock.patch("sys.stdin.isatty", return_value=False):
                        self.assertEqual(uninstall.main([directory]), 0)
                        self.assertIn(word, prompt.call_args.args[0].lower())
                        if answer.lower() == word:
                            remove.assert_called_once()
                        else:
                            remove.assert_not_called()
