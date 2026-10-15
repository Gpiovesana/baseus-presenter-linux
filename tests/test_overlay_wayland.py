import copy
import json
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from app.config import Config, DEFAULT_CONFIG
from app.overlay_wayland import WaylandOverlay
from app.overlay_backend import create_overlay


class TestWaylandOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = Config(copy.deepcopy(DEFAULT_CONFIG))
        self.overlay = WaylandOverlay(self.config)
        self.addCleanup(self.overlay.close)
        self.overlay._send = mock.Mock()

    def test_hardware_slots_send_latest_state_and_clear_serial(self):
        w = self.overlay
        w.set_active(True)
        w.switch_mode()
        w.set_pen_active(True)
        w.pen_clear()
        w.toggle_black_screen()
        self.assertEqual(w.state['mode'], 'LUPA')
        self.assertTrue(w.state['active'])
        self.assertTrue(w.state['pen'])
        self.assertTrue(w.state['black'])
        self.assertEqual(w.state['clear_serial'], 1)
        w.set_active(False)
        w.set_pen_active(False)
        self.assertFalse(w.state['active'])
        self.assertFalse(w.state['pen'])

    def test_subtitle_lifecycle_and_recording_error_messages(self):
        w = self.overlay
        w.set_recording(True)
        self.assertEqual(w.state['subtitle'], '[GRAVANDO]')
        w.show_subtitle('erro de áudio', 10)
        w.set_recording(False)
        self.assertEqual(w.state['subtitle'], '[PAUSADO]')
        w.show_subtitle('x' * 3000)
        self.assertEqual(len(w.state['subtitle']), 2048)
        w.clear_subtitle()
        self.assertEqual(w.state['subtitle'], '')

    def test_profile_refresh_does_not_reset_active_tools(self):
        w = self.overlay
        w.set_active(True)
        self.config.set_visual('laser_size', 50)
        w.update_visual_config()
        self.assertEqual(w.state['visual']['laser_size'], 50)
        self.assertTrue(w.state['active'])
        self.assertEqual(json.loads(w.payload())['protocol'], 1)

    def test_pen_serial_preserves_gesture_boundary_when_updates_coalesce(self):
        w = self.overlay
        w.set_pen_active(True)
        self.assertEqual(w.state['pen_serial'], 1)
        w.set_pen_active(True)
        self.assertEqual(w.state['pen_serial'], 1)
        w.set_pen_active(False)
        w.set_pen_active(True)
        self.assertEqual(w.state['pen_serial'], 2)

    def test_connection_error_is_reported_once_per_outage(self):
        errors = mock.Mock()
        self.overlay.on_error = errors
        self.overlay._set_available(False)
        self.overlay._set_available(False)
        self.assertEqual(errors.call_count, 1)
        self.overlay._set_available(True)
        self.overlay._set_available(False)
        self.assertEqual(errors.call_count, 2)

    def test_recovery_clears_only_the_warning_it_reported(self):
        self.overlay.on_error = mock.Mock()
        self.overlay.on_recovered = mock.Mock()
        self.overlay._set_available(False)
        warning = self.overlay.on_error.call_args.args[0]
        self.overlay._set_available(True)
        self.overlay.on_recovered.assert_called_once_with(warning)

    def test_session_selection_preserves_x11_even_with_qt_override(self):
        with mock.patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11'}), \
                mock.patch('app.overlay.PointerWindow') as x11:
            self.assertIs(create_overlay(self.config), x11.return_value)
        with mock.patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}), \
                mock.patch('app.overlay_wayland.WaylandOverlay') as wayland:
            self.assertIs(create_overlay(self.config), wayland.return_value)
