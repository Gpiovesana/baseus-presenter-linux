"""Preview only the 3D controls: no presenter, updater, extension or shared settings."""
import logging
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Configure this process before any GUI imports, keeping the installed app's log intact.
from app import logger
logger._configured=True
logging.getLogger('app').addHandler(logging.StreamHandler())

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from app.gui_visuals import Device


def main():
    app=QApplication(sys.argv)
    window=QWidget()
    window.setWindowTitle('Baseus DEV — prévia 3D isolada')
    layout=QVBoxLayout(window)
    hint=QLabel('Scroll: zoom onde aponta. Segure o botão esquerdo e arraste: pelo centro para virar, pelas bordas para inclinar. Botões abaixo: focar o controle. Duplo clique: restaurar.')
    hint.setWordWrap(True)
    layout.addWidget(hint)
    device=Device()
    device.selected.connect(device.select)
    layout.addWidget(device)
    window.resize(850,750)
    window.show()
    return app.exec_()


if __name__=='__main__':
    raise SystemExit(main())
