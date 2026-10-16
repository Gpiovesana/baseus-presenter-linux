import tempfile
import unittest
from pathlib import Path
from tools.wayland_probe import cursor_support


class TestCursorProbe(unittest.TestCase):
    def test_metadata_must_be_advertised_not_silently_embedded(self):
        self.assertEqual(cursor_support.require_metadata_mode(7), 4)
        self.assertEqual(cursor_support.require_metadata_mode(4), 4)
        for modes in (0, 1, 2, 3):
            with self.assertRaises(ValueError):
                cursor_support.require_metadata_mode(modes)

    def test_summary_distinguishes_video_from_cursor_and_keeps_stream_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'cursor.jsonl'
            path.write_text('''{"event":"format","width":1920,"height":1080}
{"event":"cursor","id":1,"x":10,"y":20,"time_ms":100}
{"event":"cursor","id":1,"x":30,"y":40,"time_ms":200}
{"event":"cursor","id":0,"x":0,"y":0,"time_ms":300}
{"event":"stats","buffers":50,"cursor_buffers":20,"valid_cursor_buffers":18}
''')
            result = cursor_support.summarize(path)
            self.assertEqual(result['unique_positions'], 2)
            self.assertEqual(result['buffers'], 50)
            self.assertEqual(result['valid_cursor_buffers'], 18)
            self.assertEqual(result['coordinate_space'], 'stream; not desktop-global')

    def test_video_without_cursor_is_not_reported_as_successful_tracking(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'cursor.jsonl'
            path.write_text('{"event":"stats","buffers":50,"cursor_buffers":0,"valid_cursor_buffers":0}\n')
            self.assertEqual(cursor_support.summarize(path)['unique_positions'], 0)
            path.write_text('{"event":"cursor"')
            self.assertEqual(cursor_support.summarize(path)['malformed_lines'], 1)
