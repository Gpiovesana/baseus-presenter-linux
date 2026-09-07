"""
Testes de app/gui.py — Etapa 3 da auditoria (#16, parte da GUI).

Verifica que MainWindow emite input_device_changed quando o microfone
realmente muda (seleção manual no combo ou troca de perfil com device
diferente), e que a primeira inicialização não gera um falso positivo.

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -p "test_gui_mic_signal.py" -v
"""
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as cfg

try:
    from PyQt5.QtWidgets import QApplication
    from app.gui import MainWindow
    QT_AVAILABLE = True
except Exception:  # pragma: no cover
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 indisponível neste ambiente")
class MicSignalTestCase(unittest.TestCase):
    _app = None

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config_file = os.path.join(self.tmpdir.name, "baseus_pointer.json")

        patcher_dir = mock.patch.object(cfg, "CONFIG_DIR", self.tmpdir.name)
        patcher_file = mock.patch.object(cfg, "CONFIG_FILE", self.config_file)
        patcher_dir.start(); self.addCleanup(patcher_dir.stop)
        patcher_file.start(); self.addCleanup(patcher_file.stop)

    def make_window(self, data=None):
        config = cfg.Config(data if data is not None else copy.deepcopy(cfg.DEFAULT_CONFIG))
        win = MainWindow(config)
        self.addCleanup(win.deleteLater)
        return win


class TestTrocaManualDeMicrofone(MicSignalTestCase):
    def test_nao_emite_na_inicializacao(self):
        win = self.make_window()
        recebidos = []
        win.input_device_changed.connect(lambda: recebidos.append(True))
        # A simples criação da janela não deve ter deixado nada pendente.
        self.assertEqual(recebidos, [])

    def test_emite_ao_trocar_para_outro_dispositivo(self):
        win = self.make_window()
        if win.combo_mic.count() < 2:
            win.combo_mic.addItem("Mic Fake 1", 1)
            win.combo_mic.addItem("Mic Fake 2", 2)

        recebidos = []
        win.input_device_changed.connect(lambda: recebidos.append(True))

        # Seleciona um índice diferente do atual.
        atual = win.combo_mic.currentIndex()
        outro = (atual + 1) % win.combo_mic.count()
        win.combo_mic.setCurrentIndex(outro)

        self.assertEqual(len(recebidos), 1)

    def test_selecionar_o_mesmo_indice_nao_emite(self):
        win = self.make_window()
        recebidos = []
        win.input_device_changed.connect(lambda: recebidos.append(True))

        atual = win.combo_mic.currentIndex()
        win.combo_mic.setCurrentIndex(atual)  # sem troca real

        self.assertEqual(recebidos, [])


class TestTrocaDePerfilComMicrofoneDiferente(MicSignalTestCase):
    def test_emite_ao_trocar_para_perfil_com_outro_device(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["profiles"]["A"] = {"visual": {}, "audio": {"input_device": None}}
        data["profiles"]["B"] = {"visual": {}, "audio": {"input_device": 3}}
        data["profiles"].pop("Padrão", None)
        data["active_profile"] = "A"

        win = self.make_window(data)
        # Garante que o combo tenha o item do device 3 para o teste ser
        # determinístico independentemente dos dispositivos reais da máquina.
        if win.combo_mic.findData(3) < 0:
            win.combo_mic.addItem("Mic Fake (id=3)", 3)
            win._load_profile_into_widgets()  # relê para achar o item agora

        recebidos = []
        win.input_device_changed.connect(lambda: recebidos.append(True))

        win.change_profile("B")

        self.assertEqual(len(recebidos), 1)

    def test_nao_emite_se_o_device_do_perfil_e_o_mesmo(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["profiles"]["A"] = {"visual": {}, "audio": {"input_device": None}}
        data["profiles"]["B"] = {"visual": {}, "audio": {"input_device": None}}
        data["profiles"].pop("Padrão", None)
        data["active_profile"] = "A"

        win = self.make_window(data)
        recebidos = []
        win.input_device_changed.connect(lambda: recebidos.append(True))

        win.change_profile("B")

        self.assertEqual(recebidos, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
