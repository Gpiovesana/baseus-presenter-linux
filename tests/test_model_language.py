import copy
from types import SimpleNamespace
from unittest import mock

from test_gui_profiles import GuiTestCase
from app.config import DEFAULT_CONFIG
from app.gui import LanguageLoadThread


class TestModelLanguage(GuiTestCase):
    def model_data(self):
        data = copy.deepcopy(DEFAULT_CONFIG)
        data['ui_language'] = 'en'
        data['models'] = [{'label': 'Palestra', 'path': '/de', 'language': 'de'},
                          {'label': 'Aula', 'path': '/pt', 'language': 'pt'}]
        data['profiles']['Padrão']['audio']['selected_model_path'] = '/de'
        return data

    def test_source_follows_model_and_profile_not_interface(self):
        win = self.make_window(self.model_data())
        self.assertEqual(win.config.get_audio('source_lang'), 'de')
        win.combo_models.setCurrentIndex(win.combo_models.findData('/pt'))
        self.assertEqual(win.config.get_audio('source_lang'), 'pt')
        self.assertEqual(win.config.get('ui_language'), 'en')

    def test_add_persists_language_and_cancel_does_not_add_model(self):
        win = self.make_window()
        with mock.patch('app.gui.QFileDialog.getExistingDirectory', return_value='/de'), \
             mock.patch('app.gui.QInputDialog.getText', return_value=('Palestra', True)), \
             mock.patch('app.gui.QInputDialog.getItem', return_value=('Deutsch (de)', True)):
            win.add_model()
        self.assertEqual(win.config.get('models')[0].get('language'), 'de')
        self.assertEqual(win.config.get_audio('source_lang'), 'de')
        before = win.config.snapshot()
        with mock.patch('app.gui.QFileDialog.getExistingDirectory', return_value='/cancel'), \
             mock.patch('app.gui.QInputDialog.getText', return_value=('Cancelado', True)), \
             mock.patch('app.gui.QInputDialog.getItem', return_value=('', False)):
            win.add_model()
        self.assertEqual(win.config.snapshot(), before)

    def test_old_model_has_no_assumed_source(self):
        data = self.model_data()
        del data['models'][0]['language']
        config = self.make_config(data)
        self.assertIsNone(config.get_audio('source_lang'))

    def test_pending_profile_event_does_not_open_nested_language_dialog(self):
        data = self.model_data()
        del data['models'][0]['language']
        win = self.make_window(data)
        calls = []
        def ask(*args):
            calls.append(True)
            if len(calls) == 1:
                win._ensure_model_language()
            return None
        with mock.patch.object(win, '_ask_model_language', side_effect=ask):
            win._ensure_model_language()
        self.assertEqual(len(calls), 1)

    def test_legacy_prompt_cancel_then_save_language_for_all_profiles(self):
        data = self.model_data()
        del data['models'][0]['language']
        data['profiles']['Outra'] = copy.deepcopy(data['profiles']['Padrão'])
        win = self.make_window(data)
        with mock.patch('app.gui.QInputDialog.getItem', return_value=('', False)):
            win._ensure_model_language()
        self.assertIsNone(win.config.get_audio('source_lang'))
        with mock.patch('app.gui.QInputDialog.getItem', return_value=('Deutsch (de)', True)):
            win._ensure_model_language()
        win.change_profile('Outra')
        self.assertEqual(win.config.get_audio('source_lang'), 'de')
        from app.config import load_config
        self.assertEqual(load_config()['models'][0]['language'], 'de')

    def test_late_catalog_uses_current_model_and_unavailable_target_cannot_download(self):
        win = self.make_window(self.model_data())
        win.combo_models.setCurrentIndex(win.combo_models.findData('/pt'))
        win._on_language_catalog_loaded([('de', 'Portuguese', 'pt'), ('pt', 'German', 'de')])
        enabled = [win.combo_lang.itemData(i) for i in range(win.combo_lang.count())
                   if win.combo_lang.model().item(i).isEnabled()]
        self.assertEqual(enabled, ['de'])
        self.assertEqual(win.config.get_audio('target_lang'), 'en')
        with mock.patch('app.gui.ARGOS_GUI_AVAILABLE', True), \
             mock.patch('app.gui.QMessageBox.question') as question:
            win.check_and_download_lang(win.combo_lang.findData('en'))
        question.assert_not_called()

    def test_audio_uses_model_language_and_unknown_model_preserves_transcript(self):
        from app.audio import AudioThread
        config = self.make_config(self.model_data())
        thread = AudioThread(config)
        thread.is_translating = True
        with mock.patch('app.audio.ARGOS_AVAILABLE', True), \
             mock.patch('app.audio.argostranslate') as argos:
            argos.translate.translate.side_effect = lambda text, source, target: f'{source}:{target}:{text}'
            self.assertEqual(thread._translate_if_needed('Hallo'), 'de:en:Hallo')
            config.set('models', [{'path': '/de', 'label': 'Antigo'}])
            self.assertEqual(thread._translate_if_needed('Hallo'), 'Hallo')

    def test_catalog_refreshes_before_read_and_keeps_all_origins(self):
        thread = LanguageLoadThread()
        received = []
        thread.loaded.connect(received.append)
        state = {'fresh': False}
        def refresh():
            state['fresh'] = True
        def packages():
            if not state['fresh']:
                return []
            return [SimpleNamespace(from_code='de', to_code='pt', to_name='Portuguese')]
        with mock.patch('app.gui.argostranslate') as argos:
            argos.package.update_package_index.side_effect = refresh
            argos.package.get_available_packages.side_effect = packages
            thread.run()
        self.assertEqual(received, [[('de', 'Portuguese', 'pt')]])
