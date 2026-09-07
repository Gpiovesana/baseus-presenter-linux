"""
Testes de app/gui.py — Etapa 1 da auditoria (#1, #2, #3, #4, #19, #20).

Usa QApplication real em modo offscreen (QT_QPA_PLATFORM=offscreen), pois
MainWindow herda de QMainWindow e cria widgets reais no __init__. Roda sem
hardware/áudio físico — sounddevice.query_devices() pode ou não funcionar no
CI; o try/except no __init__.py da MainWindow já cobre isso.

    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_gui_profiles -v
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
class GuiTestCase(unittest.TestCase):
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

    def make_config(self, data=None):
        return cfg.Config(data if data is not None else copy.deepcopy(cfg.DEFAULT_CONFIG))

    def make_window(self, data=None):
        win = MainWindow(self.make_config(data))
        self.addCleanup(win.deleteLater)
        return win


class TestExcluirPerfil(GuiTestCase):
    """#1: excluir um perfil sobrescrevia outro perfil."""

    def test_perfil_sobrevivente_preserva_seus_proprios_valores(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["profiles"]["A"] = {"visual": {"laser_size": 30}, "audio": {}}
        data["profiles"]["B"] = {"visual": {"laser_size": 80}, "audio": {}}
        data["profiles"].pop("Padrão", None)
        data["active_profile"] = "A"

        win = self.make_window(data)
        # Muda para B e confirma que o slider reflete 80.
        win.change_profile("B")
        self.assertEqual(win.laser_slider.value(), 80)

        # Exclui B (perfil ativo). O sobrevivente deve ser A, com laser=30 —
        # não sobrescrito pelo valor de B que estava nos widgets.
        from PyQt5.QtWidgets import QMessageBox
        with mock.patch("app.gui.QMessageBox.question", return_value=QMessageBox.Yes):
            win.delete_profile()

        self.assertEqual(win.config.snapshot()["active_profile"], "A")
        self.assertEqual(win.laser_slider.value(), 30)
        self.assertEqual(
            win.config.snapshot()["profiles"]["A"]["visual"]["laser_size"], 30)


class TestCarregarPerfilNaoAutoModifica(GuiTestCase):
    """#2: carregar um perfil não deve alterar as próprias configs."""

    def test_legenda_desativada_permanece_desativada_apos_carregar(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["profiles"]["Silencioso"] = {
            "visual": {}, "audio": {"show_subtitles": False, "selected_model_path": ""}
        }
        data["profiles"].pop("Padrão", None)
        data["active_profile"] = "Silencioso"
        data["models"] = [{"label": "M1", "path": "/tmp/m1"}]

        win = self.make_window(data)
        self.assertFalse(win.check_legenda.isChecked())
        # Nada deve ter sido persistido como True por engano.
        self.assertFalse(win.config.get_audio("show_subtitles"))

    def test_loading_widgets_bloqueia_save_indevido(self):
        win = self.make_window()
        win._loading_widgets = True
        antes = win.config.snapshot()
        win.laser_slider.setValue(77)
        win.save_settings()  # chamado "manualmente", simulando disparo indireto
        win._loading_widgets = False
        # Nenhuma gravação deveria ter ocorrido enquanto a flag estava ativa.
        self.assertEqual(win.config.snapshot()["profiles"], antes["profiles"])


class TestAdicionarPrimeiroModelo(GuiTestCase):
    """#3: adicionar o primeiro modelo com catálogo vazio."""

    def test_selected_model_path_nao_e_sobrescrito_para_vazio(self):
        win = self.make_window()
        self.assertEqual(win.config.get("models", []), [])

        with mock.patch("app.gui.QFileDialog.getExistingDirectory", return_value="/tmp/vosk-pt"), \
             mock.patch("app.gui.QInputDialog.getText", return_value=("Vosk PT", True)):
            win.add_model()

        self.assertEqual(win.config.get_audio("selected_model_path"), "/tmp/vosk-pt")
        self.assertEqual(win.combo_models.currentData(), "/tmp/vosk-pt")


class TestTrocaDeModeloEmiteSinal(GuiTestCase):
    """#4: selecionar outro modelo deve emitir model_changed."""

    def test_emite_model_changed_ao_trocar_modelo_existente(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["models"] = [
            {"label": "M1", "path": "/tmp/m1"},
            {"label": "M2", "path": "/tmp/m2"},
        ]
        data["profiles"]["Padrão"]["audio"]["selected_model_path"] = "/tmp/m1"

        win = self.make_window(data)
        recebidos = []
        win.model_changed.connect(lambda: recebidos.append(True))

        idx = win.combo_models.findData("/tmp/m2")
        self.assertGreaterEqual(idx, 0)
        win.combo_models.setCurrentIndex(idx)

        self.assertEqual(len(recebidos), 1)
        self.assertEqual(win.config.get_audio("selected_model_path"), "/tmp/m2")

    def test_nao_emite_ao_recarregar_o_mesmo_modelo(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["models"] = [{"label": "M1", "path": "/tmp/m1"}]
        data["profiles"]["Padrão"]["audio"]["selected_model_path"] = "/tmp/m1"

        win = self.make_window(data)
        recebidos = []
        win.model_changed.connect(lambda: recebidos.append(True))

        win._load_profile_into_widgets()  # simula reload sem troca real
        self.assertEqual(recebidos, [])


class TestRemoverModelo(GuiTestCase):
    """#19: remover modelo restaurava seu caminho no perfil ativo."""

    def test_caminho_removido_nao_e_restaurado(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["models"] = [{"label": "M1", "path": "/tmp/m1"}]
        data["profiles"]["Padrão"]["audio"]["selected_model_path"] = "/tmp/m1"

        win = self.make_window(data)
        self.assertEqual(win.combo_models.currentData(), "/tmp/m1")

        from PyQt5.QtWidgets import QMessageBox
        with mock.patch("app.gui.QMessageBox.question", return_value=QMessageBox.Yes):
            win.delete_model()

        self.assertEqual(win.config.get("models"), [])
        self.assertEqual(win.config.get_audio("selected_model_path"), "")


class TestTrocaDePerfilPersisteImediatamente(GuiTestCase):
    """#20: active_profile precisa ser persistido no disco na hora da troca."""

    def test_active_profile_sobrevive_a_reload_do_disco(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["profiles"]["Aula"] = copy.deepcopy(data["profiles"]["Padrão"])

        win = self.make_window(data)
        win.change_profile("Aula")

        # Simula reinício: relê do disco em vez do objeto Config em memória.
        recarregado = cfg.load_config()
        self.assertEqual(recarregado["active_profile"], "Aula")


if __name__ == "__main__":
    unittest.main(verbosity=2)
