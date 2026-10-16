"""Tema da GUI aprovada."""
STYLE = """
QWidget { background: #181b20; color: #e6eaf1; font-family: 'DejaVu Sans'; font-size: 13px; }
QFrame#header { background: #15181c; border-bottom: 1px solid #303640; }
QFrame#sidebar, QFrame#details { background: #1e2229; }
QFrame#sidebar { border-right: 1px solid #303640; }
QFrame#sidebar QPushButton { padding: 12px 8px; font-size: 12px; }
QFrame#details { border-left: 1px solid #303640; }
QFrame#profiles { background: #1e2229; border-bottom: 1px solid #303640; }
QComboBox { background: #252b34; border: 1px solid #45566d; border-radius: 7px; padding: 9px 12px; }
QComboBox QAbstractItemView { background: #252b34; selection-background-color: #233b58; }
QLabel { background: transparent; }
QLabel#muted { color: #9aa6b6; font-size: 12px; }
QLabel#section { color: #8b9bb0; font-size: 10px; font-weight: bold; }
QLabel#heading { font-size: 23px; font-weight: bold; }
QLabel#title { font-size: 20px; font-weight: bold; }
QPushButton { padding: 12px 14px; border: 1px solid #37404d; border-radius: 8px; background: #252b34; text-align: left; }
QPushButton:hover { background: #303b4b; border-color: #6887af; }
QPushButton:checked { background: #233b58; color: #b5d6ff; border-color: #548fdb; }
QPushButton:focus { border: 2px solid #98bdff; }
QPushButton:disabled { color: #788390; border: none; background: transparent; }
QSlider::groove:horizontal { background: #364150; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #69a4f7; border-radius: 2px; }
QSlider::handle:horizontal { background: #c1d9ff; width: 14px; margin: -5px 0; border-radius: 7px; }
"""
