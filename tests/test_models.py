import copy
import unittest
from unittest.mock import patch, MagicMock

from app.config import Config, DEFAULT_CONFIG
from app import models


class TestModels(unittest.TestCase):
    def setUp(self):
        self.config = Config(copy.deepcopy(DEFAULT_CONFIG))
        self.config.set('ui_language', 'en')

    def test_add_replaces_same_path_and_selects_it_without_changing_ui(self):
        models.add_model(self.config, '/vosk', 'Old', 'pt')
        models.add_model(self.config, '/vosk', 'New', 'de')
        self.assertEqual(self.config.get('models'), [{'path':'/vosk','label':'New','language':'de'}])
        self.assertEqual(self.config.get_audio('source_lang'), 'de')
        self.assertEqual(self.config.get('ui_language'), 'en')

    def test_remove_unselects_all_profiles_but_preserves_other_models(self):
        models.add_model(self.config, '/other', 'Other', 'fr')
        models.add_model(self.config, '/vosk', 'Voice', 'pt')
        with self.config.mutate() as data:
            data['profiles']['Second'] = copy.deepcopy(data['profiles']['Padrão'])
        models.remove_model(self.config, '/vosk')
        for profile in self.config.get('profiles').values():
            self.assertEqual(profile['audio']['selected_model_path'], '')
        self.assertEqual(self.config.get('models')[0]['path'], '/other')

    def test_legacy_language_is_global_and_keeps_label(self):
        self.config.set('models', [{'path':'/vosk','label':'Legacy'}])
        models.set_model_language(self.config, '/vosk', 'es')
        self.assertEqual(models.find_model(self.config, '/vosk'),
                         {'path':'/vosk','label':'Legacy','language':'es'})
        models.set_model_language(self.config, '/missing', 'it')
        self.assertEqual(models.find_model(self.config, '/missing')['language'], 'it')

    def test_installed_translation_requires_pair(self):
        source, target = MagicMock(code='pt'), MagicMock(code='en')
        with patch.object(models, 'argostranslate') as argos:
            argos.translate.get_installed_languages.return_value = [source]
            self.assertFalse(models.has_translation('pt', 'en'))
            argos.translate.get_installed_languages.return_value = [source, target]
            source.get_translation.return_value = object()
            self.assertTrue(models.has_translation('pt', 'en'))
            source.get_translation.return_value = None
            self.assertFalse(models.has_translation('pt', 'en'))
