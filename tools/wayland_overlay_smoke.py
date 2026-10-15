#!/usr/bin/env python3
"""Exercise the integrated renderer without hardware, audio or saved settings."""
import argparse
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from app.config import Config, DEFAULT_CONFIG
from app.overlay_wayland import WaylandOverlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 120:
        parser.error('--seconds must be 30..120')
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors = []

    def failed(message):
        errors.append(message)
        print(message, file=sys.stderr, flush=True)
        app.quit()

    overlay = WaylandOverlay(Config(DEFAULT_CONFIG), on_error=failed)
    app.aboutToQuit.connect(overlay.close)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    overlay.show()
    phases = [('LASER', False), ('LUPA', False), ('SPOTLIGHT', False),
              ('LASER', True), ('LASER', False), ('LASER', False)]
    retained = []
    interval = args.seconds * 1000 // len(phases)

    def phase(index):
        mode, pen = phases[index]
        overlay.pen_clear() if index == 4 else None
        overlay._change(mode=mode, active=index < 3, pen=pen, black=index == 5)
        if index == 4:
            overlay.show_subtitle('Baseus Wayland — teste de legenda', interval)
        print(f'Phase {index + 1}/6: {mode}, pen={pen}, black={index == 5}', flush=True)

    for index in range(len(phases)):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda i=index: phase(i))
        timer.start(index * interval)
        retained.append(timer)
    QTimer.singleShot(args.seconds * 1000, app.quit)
    app.exec_()
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
