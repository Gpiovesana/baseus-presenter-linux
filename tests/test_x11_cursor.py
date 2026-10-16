"""Verify XFixes reference ownership without hiding the user's real cursor."""
import unittest
from unittest.mock import Mock, patch
from app.x11_cursor import X11Cursor


class CursorOwnership(unittest.TestCase):
    def test_idempotent_hide_and_close_release_each_root(self):
        cursor = X11Cursor.__new__(X11Cursor)
        cursor._display = 1
        cursor._hidden = False
        cursor._roots = [10, 20]
        cursor._x = Mock()
        cursor._fixes = Mock()
        cursor.set_hidden(True)
        cursor.set_hidden(True)
        self.assertEqual(cursor._fixes.XFixesHideCursor.call_count, 2)
        cursor.close()
        cursor.close()
        self.assertEqual(cursor._fixes.XFixesShowCursor.call_count, 2)
        cursor._x.XCloseDisplay.assert_called_once_with(1)

    def test_missing_library_is_nonfatal(self):
        with patch('app.x11_cursor.C.CDLL', side_effect=OSError('missing')):
            cursor = X11Cursor()
        cursor.set_hidden(True)
        cursor.close()
        self.assertIsNone(cursor._display)
