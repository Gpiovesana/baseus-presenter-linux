from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('gjs'), 'GJS is required for renderer tests')
class TestGnomeCursor(unittest.TestCase):
    def test_cursor_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ['gjs', str(root / 'tests/fixtures/renderer-cursor-test.js'), str(root)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
