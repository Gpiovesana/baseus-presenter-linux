import unittest
from tools.wayland_probe.probe import classify_backend


class TestWaylandProbe(unittest.TestCase):
    def test_session_and_loaded_backend_are_not_interchangeable(self):
        self.assertEqual(classify_backend('wayland', 'wayland'), 'wayland-native')
        self.assertEqual(classify_backend('wayland', 'wayland-egl'), 'wayland-native')
        self.assertEqual(classify_backend('wayland', 'xcb'), 'xwayland')
        self.assertEqual(classify_backend('x11', 'xcb'), 'x11')
        self.assertEqual(classify_backend('', 'xcb'), 'unknown')
        self.assertEqual(classify_backend('wayland', 'offscreen'), 'offscreen')
