import os
import tempfile
from pathlib import Path
from unittest import mock
from test_gui_profiles import GuiTestCase
from app import gui


class TestGuiUpdate(GuiTestCase):
    def test_update_choice_defaults_to_current_state_and_returns_selection(self):
        win = self.make_window()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, XDG_CONFIG_HOME=directory), \
                mock.patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.No):
            entry = Path(directory) / "autostart/baseus-presenter.desktop"
            entry.parent.mkdir()
            for previous in (False, True):
                entry.unlink(missing_ok=True)
                if previous:
                    entry.write_text("[Desktop Entry]\nType=Application\n")
                def accept(box):
                    self.assertEqual(box.checkBox().isChecked(), previous)
                    box.checkBox().setChecked(not previous)
                    return gui.QMessageBox.Yes
                with mock.patch.object(gui.QMessageBox, "exec_", accept):
                    self.assertEqual(win.prompt_update("2.1.0"), (True, not previous))
                self.assertEqual(entry.exists(), previous)
            with mock.patch.object(gui.QMessageBox, "exec_", return_value=gui.QMessageBox.No):
                self.assertEqual(win.prompt_update("2.1.0"), (False, True))

    def test_autostart_disabled_by_desktop_settings_is_unchecked(self):
        win = self.make_window()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            entry = Path(directory) / "autostart/baseus-presenter.desktop"
            entry.parent.mkdir()
            for setting in ("Hidden=true", "X-GNOME-Autostart-enabled=false"):
                entry.write_text("[Desktop Entry]\n" + setting + "\n")
                with mock.patch.object(gui.QMessageBox, "exec_", return_value=gui.QMessageBox.No):
                    self.assertEqual(win.prompt_update("2.1.0"), (False, False))
