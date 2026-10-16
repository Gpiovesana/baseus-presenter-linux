"""Model-language prompts must not outlive their window's Qt widgets."""
import copy
from unittest import mock

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent

from app import config as cfg, gui
from test_gui_profiles import GuiTestCase


class TestModelPromptLifecycle(GuiTestCase):
    def make_legacy_window(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data['models'] = [{'label': 'Legacy', 'path': '/tmp/vosk-legacy'}]
        data['profiles']['Padrão']['audio']['selected_model_path'] = '/tmp/vosk-legacy'
        win = gui.MainWindow(self.make_config(data))
        self.addCleanup(lambda: sip.delete(win) if not sip.isdeleted(win) else None)
        return win

    def test_deleting_parent_during_dialog_does_not_touch_deleted_widgets(self):
        win = self.make_legacy_window()
        with mock.patch.object(win, '_ask_model_language',
                               side_effect=lambda *args: sip.delete(win)), \
                mock.patch.object(win.config, 'save') as save:
            win._ensure_model_language()
            save.assert_not_called()
        self.assertIsNone(win.config.get_audio('source_lang'))

    def test_pending_prompt_is_cancelled_when_window_is_deleted(self):
        with mock.patch.object(gui.MainWindow, '_ask_model_language') as ask:
            win = self.make_legacy_window()
            win.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self._app.processEvents()
            ask.assert_not_called()
