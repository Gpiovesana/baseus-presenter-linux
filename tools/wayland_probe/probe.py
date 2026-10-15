#!/usr/bin/env python3
"""Disposable Qt surface/cursor probe. Does not change the production overlay."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess


def classify_backend(session, platform):
    if platform.startswith('wayland'):
        return 'wayland-native'
    if platform == 'xcb':
        return {'wayland': 'xwayland', 'x11': 'x11'}.get(session, 'unknown')
    return platform or 'unknown'


def package_versions():
    try:
        result = subprocess.run(
            ['dpkg-query', '-W', '-f=${Package}=${Version}\n', 'gnome-shell',
             'mutter*', 'kwin-wayland', 'xdg-desktop-portal*', 'libqt5wayland*'],
            text=True, capture_output=True, timeout=5)
        return result.stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('xcb', 'wayland', 'offscreen'))
    parser.add_argument('--overlay', action='store_true', help='Show disposable surfaces for manual testing')
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('--seconds must be between 1 and 300')
    if args.backend:
        os.environ['QT_QPA_PLATFORM'] = args.backend
    # Backend selection must precede QApplication creation.
    from PyQt5.QtCore import Qt, QTimer, PYQT_VERSION_STR, qVersion
    from PyQt5.QtGui import QCursor, QPainter, QColor, QPen
    from PyQt5.QtWidgets import QApplication, QWidget
    app = QApplication([])
    platform = app.platformName()
    report = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'session': os.environ.get('XDG_SESSION_TYPE', ''),
        'desktop': os.environ.get('XDG_CURRENT_DESKTOP', ''),
        'qt_platform': platform, 'qt': qVersion(), 'pyqt': PYQT_VERSION_STR,
        'classification': classify_backend(os.environ.get('XDG_SESSION_TYPE', ''), platform),
        'packages': package_versions(), 'screens': [], 'cursor_samples': [],
        'app_received_focus': False, 'screen_changes': [],
        'manual_results': {key: 'not-tested' for key in
                           ('above_fullscreen', 'click_through', 'no_focus_theft',
                            'global_cursor_correct', 'mixed_scales', 'monitor_disconnect')},
    }
    def screen_info(screen):
        geometry = screen.geometry()
        return {'name': screen.name(), 'geometry': [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                'dpr': screen.devicePixelRatio(), 'logical_dpi': screen.logicalDotsPerInch(),
                'physical_dpi': screen.physicalDotsPerInch()}
    report['screens'] = [screen_info(screen) for screen in app.screens()]
    windows = []

    class Surface(QWidget):
        def __init__(self, screen):
            flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            flags |= Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
            if platform == 'xcb':
                flags |= Qt.X11BypassWindowManagerHint
            super().__init__(None, flags)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.NoFocus)
            self.screen_name = screen.name()
            self.setGeometry(screen.geometry())
            self.show()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setPen(QPen(QColor('#ff00cc'), 4))
            painter.drawRect(self.rect().adjusted(8, 8, -8, -8))
            cursor = self.mapFromGlobal(QCursor.pos())
            painter.drawEllipse(cursor, 24, 24)
            painter.drawText(30, 45, f'BASEUS PROBE | {platform} | {self.screen_name}')
            painter.drawText(30, 70, f'Qt cursor: {QCursor.pos().x()}, {QCursor.pos().y()}')

    if args.overlay:
        windows = [Surface(screen) for screen in app.screens()]
    def removed(screen):
        report['screen_changes'].append({'removed': screen.name()})
        for window in windows:
            if window.screen_name == screen.name():
                window.close()
    def added(screen):
        report['screen_changes'].append({'added': screen_info(screen)})
        if args.overlay:
            windows.append(Surface(screen))
    app.screenRemoved.connect(removed)
    app.screenAdded.connect(added)
    def sample():
        cursor = QCursor.pos()
        report['cursor_samples'].append([cursor.x(), cursor.y()])
        report['app_received_focus'] |= app.focusWindow() is not None
        for window in windows:
            if window.isVisible():
                window.update()
    timer = QTimer()
    timer.timeout.connect(sample)
    timer.start(100)
    app.setQuitOnLastWindowClosed(False)
    QTimer.singleShot(args.seconds * 1000 if args.overlay else 100, app.quit)
    app.exec_()
    report['unique_cursor_positions'] = len({tuple(point) for point in report['cursor_samples']})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
