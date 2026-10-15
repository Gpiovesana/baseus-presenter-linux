import copy
import unittest
from unittest.mock import patch
from app import audio
from app.config import DEFAULT_CONFIG


class TestTranslationTiming(unittest.TestCase):
    def test_duration_and_queue_depth_are_measured_without_logging_text(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                worker = audio.AudioThread(copy.deepcopy(DEFAULT_CONFIG))
                worker.is_translating = True
                worker.q.put(b'audio')
                with patch.object(audio, 'ARGOS_AVAILABLE', True), \
                     patch.object(audio, 'argostranslate') as argos, \
                     patch.object(audio.time, 'perf_counter', side_effect=[10.0, 10.125]), \
                     patch.object(audio.log, 'debug') as debug:
                    argos.translate.translate.return_value = 'translated'
                    if fails:
                        argos.translate.translate.side_effect = ValueError('failure')
                    result = worker._translate_if_needed('private transcript')
                self.assertEqual(result, 'private transcript' if fails else 'translated')
                self.assertEqual(debug.call_count, 1)
                template, *values = debug.call_args.args
                message = template % tuple(values)
                self.assertIn('duration_ms=125.000', message)
                self.assertIn('queue_depth=1', message)
                self.assertIn('success=False' if fails else 'success=True', message)
                self.assertNotIn('private transcript', message)

    def test_disabled_translation_does_not_measure_a_nonexistent_call(self):
        worker = audio.AudioThread(copy.deepcopy(DEFAULT_CONFIG))
        with patch.object(audio.time, 'perf_counter') as clock:
            self.assertEqual(worker._translate_if_needed('text'), 'text')
        clock.assert_not_called()
