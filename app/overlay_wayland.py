"""Asynchronous state bridge to the GNOME Shell overlay (no Qt surface)."""
import json

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtDBus import (QDBusConnection, QDBusMessage, QDBusPendingCallWatcher,
                         QDBusPendingReply)

from .config import Config
from .i18n import tr
from .logger import get_logger

log = get_logger(__name__)
SERVICE = 'org.gnome.Shell'
PATH = '/org/gnome/Shell/Extensions/BaseusPresenter'
INTERFACE = 'org.gnome.Shell.Extensions.BaseusPresenter1'
MODES = ('LASER', 'LUPA', 'SPOTLIGHT')


class WaylandOverlay(QObject):
    def __init__(self, config, on_error=None, on_recovered=None):
        super().__init__()
        self.config = config if isinstance(config, Config) else Config(config)
        self.on_error = on_error
        self.on_recovered = on_recovered
        self._warning_message = None
        self.available = None
        self._closed = False
        self._pending = None
        self._dirty = False
        self.is_recording = False
        self.is_translating = False
        self.state = dict(protocol=1, active=False, mode='LASER', pen=False, pen_serial=0,
                          clear_serial=0, black=False, subtitle='', visual={})
        self.subtitle_timer = QTimer(self)
        self.subtitle_timer.setSingleShot(True)
        self.subtitle_timer.timeout.connect(self.clear_subtitle)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(self._send)
        self.update_visual_config()

    def payload(self):
        return json.dumps(self.state, ensure_ascii=False)

    def show(self):
        self.heartbeat.start()
        self._send()

    def _set_available(self, available):
        if self.available == available:
            return
        self.available = available
        if available:
            log.info('Overlay GNOME conectado.')
            if self._warning_message and self.on_recovered:
                self.on_recovered(self._warning_message)
            self._warning_message = None
        else:
            message = tr('Overlay Wayland indisponível. Ative a extensão Baseus Presenter '
                         'no GNOME. Consulte docs/wayland.md; a navegação de slides continua disponível.')
            log.warning(message)
            self._warning_message = message
            if self.on_error:
                self.on_error(message)

    def _send(self):
        if self._closed:
            return
        if self._pending is not None:
            self._dirty = True
            return
        self._dirty = False
        message = QDBusMessage.createMethodCall(SERVICE, PATH, INTERFACE, 'Update')
        message.setArguments([self.payload()])
        pending = QDBusConnection.sessionBus().asyncCall(message, 1000)
        self._pending = QDBusPendingCallWatcher(pending, self)
        self._pending.finished.connect(self._finished)

    def _finished(self, watcher):
        self._pending = None
        reply = QDBusPendingReply(watcher).reply()
        success = reply.type() != QDBusMessage.ErrorMessage and reply.arguments() == [True]
        watcher.deleteLater()
        if self._closed:
            return
        self._set_available(success)
        if self._dirty and success:
            self._send()

    def _change(self, **values):
        self.state.update(values)
        self._send()

    def set_active(self, active):
        self._change(active=bool(active))

    def switch_mode(self):
        self._change(mode=MODES[(MODES.index(self.state['mode']) + 1) % len(MODES)])

    def set_pen_active(self, active):
        active = bool(active)
        if active and not self.state['pen']:
            self.state['pen_serial'] += 1
        self._change(pen=active)

    def pen_clear(self):
        self._change(clear_serial=self.state['clear_serial'] + 1)

    def toggle_black_screen(self):
        self._change(black=not self.state['black'])

    def show_subtitle(self, text, duration=5000):
        self._change(subtitle=str(text)[:2048])
        self.subtitle_timer.start(max(1, int(duration)))

    def clear_subtitle(self):
        self._change(subtitle='')

    def set_recording(self, state):
        if self.is_recording != state:
            self.is_recording = state
            self.show_subtitle('[GRAVANDO]' if state else '[PAUSADO]', 2000)

    def set_translating(self, state):
        self.is_translating = state
        self.show_subtitle('[TRADUÇÃO ON]' if state else '[TRADUÇÃO OFF]', 2000)

    def update_visual_config(self):
        defaults = dict(laser_size=30, laser_color='#FF0000', pincel_color='#FF0000',
                        lupa_size=250, lupa_shape='circular', spotlight_size=300,
                        spotlight_opacity=160)
        self.state['visual'] = {key: self.config.get_visual(key, value)
                                for key, value in defaults.items()}
        self._send()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.heartbeat.stop()
        self.subtitle_timer.stop()
        message = QDBusMessage.createMethodCall(SERVICE, PATH, INTERFACE, 'Release')
        # Same connection preserves ordering after an outstanding Update.
        QDBusConnection.sessionBus().asyncCall(message, 1000)
