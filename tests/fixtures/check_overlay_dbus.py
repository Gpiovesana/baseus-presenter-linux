"""Run through dbus-run-session; asserts real QtDBus transport, not rendering."""
import copy
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication
from app.config import Config, DEFAULT_CONFIG
import app.overlay_wayland as bridge

app = QApplication([])
bridge.SERVICE = 'org.baseus.OverlayTest'


def pump(milliseconds=300):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec_()


with tempfile.TemporaryDirectory() as directory:
    events_path = Path(directory) / 'events.jsonl'
    server = subprocess.Popen(['/usr/bin/python3',
        str(Path(__file__).with_name('overlay_dbus_service.py')), str(events_path)],
        stdout=subprocess.PIPE, text=True)
    overlay = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(server.stdout, selectors.EVENT_READ)
            assert selector.select(5), 'Private service did not become ready'
        assert server.stdout.readline().strip() == 'READY'
        errors = []
        overlay = bridge.WaylandOverlay(Config(copy.deepcopy(DEFAULT_CONFIG)), errors.append)
        overlay.show()
        overlay.set_active(True)
        overlay.set_pen_active(True)
        overlay.set_active(False)  # Last state must survive an outstanding call.
        pump()
        assert overlay.available is True, errors
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        assert events[-1]['state']['active'] is False
        assert events[-1]['state']['pen'] is True
        overlay.close()
        pump()
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        assert events[-1]['method'] == 'Release'
        overlay = bridge.WaylandOverlay(Config(copy.deepcopy(DEFAULT_CONFIG)), errors.append)
        overlay.show()
        pump()
        assert overlay.available is True
        server.terminate()
        server.wait(timeout=3)
        overlay._send()
        pump()
        assert overlay.available is False
        assert len(errors) == 1
        overlay._send()
        pump()
        assert len(errors) == 1
        overlay.close()
        print('PASS: QtDBus asynchronous reply, coalescing, Release, service loss, one warning, close.')
    finally:
        if overlay:
            overlay.close()
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=3)
