import json
from PyQt5.QtWidgets import QTabWidget
from test_gui_profiles import GuiTestCase
from app import i18n


class TestGuiLanguage(GuiTestCase):
    def test_english_widgets_keep_profile_and_audio_values(self):
        i18n.install_translator(self._app, "en")
        self.addCleanup(i18n.install_translator, self._app, "pt")
        win = self.make_window()
        self.assertEqual(win.btn_check_update.text(), "Check for Updates")
        self.assertEqual(win.findChild(QTabWidget).tabText(2), "General")
        self.assertEqual(win.combo_profiles.currentText(), "Padrão")
        audio_before = win.config.snapshot()["profiles"]["Padrão"]["audio"]
        win.combo_ui_language.setCurrentIndex(win.combo_ui_language.findData("pt"))
        self.assertEqual(win.config.get("ui_language"), "pt")
        self.assertEqual(win.config.snapshot()["profiles"]["Padrão"]["audio"], audio_before)
        with open(self.config_file, encoding="utf-8") as stream:
            self.assertEqual(json.load(stream)["ui_language"], "pt")
        # Changing the preference takes effect on restart, not halfway through a window.
        self.assertEqual(win.btn_check_update.text(), "Check for Updates")

    def test_missing_qm_uses_english_catalog_without_network(self):
        from unittest import mock
        with mock.patch("PyQt5.QtCore.QTranslator.load", return_value=False):
            i18n.install_translator(self._app, "en")
        self.addCleanup(i18n.install_translator, self._app, "pt")
        win = self.make_window()
        self.assertEqual(win.btn_check_update.text(), "Check for Updates")
