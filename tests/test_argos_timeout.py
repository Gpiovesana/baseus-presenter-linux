"""
Testes de app/gui.py — Etapa 4 da auditoria (#25).

Verifica que as operações de rede do Argos rodam sob um timeout de socket e
que o valor global é sempre restaurado — inclusive quando a operação falha.

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -p "test_argos_timeout.py" -v
"""
import logging
import os
import socket
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

try:
    from PyQt5.QtWidgets import QApplication
    from app import gui as gui_mod
    QT_AVAILABLE = True
except Exception:  # pragma: no cover
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 indisponível neste ambiente")
class TestSocketTimeoutHelper(unittest.TestCase):
    """O context manager precisa aplicar e restaurar o timeout global."""

    def setUp(self):
        self.original = socket.getdefaulttimeout()
        self.addCleanup(socket.setdefaulttimeout, self.original)

    def test_aplica_timeout_dentro_do_bloco(self):
        with gui_mod.socket_timeout(7):
            self.assertEqual(socket.getdefaulttimeout(), 7)

    def test_restaura_valor_anterior_ao_sair(self):
        socket.setdefaulttimeout(3)
        with gui_mod.socket_timeout(30):
            self.assertEqual(socket.getdefaulttimeout(), 30)
        self.assertEqual(socket.getdefaulttimeout(), 3)

    def test_restaura_valor_mesmo_com_excecao(self):
        """O finally não pode deixar o timeout vazando para o resto do app."""
        socket.setdefaulttimeout(5)
        with self.assertRaises(RuntimeError):
            with gui_mod.socket_timeout(60):
                raise RuntimeError("falha simulada")
        self.assertEqual(socket.getdefaulttimeout(), 5)

    def test_restaura_none_corretamente(self):
        """None (sem timeout) é o default do Python e deve ser preservado."""
        socket.setdefaulttimeout(None)
        with gui_mod.socket_timeout(10):
            self.assertEqual(socket.getdefaulttimeout(), 10)
        self.assertIsNone(socket.getdefaulttimeout())


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 indisponível neste ambiente")
class TestTimeoutsConfigurados(unittest.TestCase):
    def test_constantes_sao_valores_razoaveis(self):
        self.assertGreater(gui_mod.ARGOS_INDEX_TIMEOUT_S, 0)
        self.assertGreater(gui_mod.ARGOS_DOWNLOAD_TIMEOUT_S, 0)
        # O download (~30MB) precisa de mais folga que a leitura do índice.
        self.assertGreater(
            gui_mod.ARGOS_DOWNLOAD_TIMEOUT_S, gui_mod.ARGOS_INDEX_TIMEOUT_S)


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 indisponível neste ambiente")
class TestLanguageLoadThreadUsaTimeout(unittest.TestCase):
    _app = None

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original = socket.getdefaulttimeout()
        self.addCleanup(socket.setdefaulttimeout, self.original)

    def test_get_available_packages_roda_sob_timeout(self):
        observado = {}

        def fake_get_available_packages():
            observado["timeout"] = socket.getdefaulttimeout()
            return []

        thread = gui_mod.LanguageLoadThread()
        with mock.patch.object(gui_mod, "argostranslate") as mock_argos:
            mock_argos.package.get_available_packages = fake_get_available_packages
            thread.run()  # chamado direto, sem start()

        self.assertEqual(observado["timeout"], gui_mod.ARGOS_INDEX_TIMEOUT_S)
        self.assertEqual(socket.getdefaulttimeout(), self.original)

    def test_falha_de_rede_emite_failed_e_restaura_timeout(self):
        thread = gui_mod.LanguageLoadThread()
        falhas = []
        thread.failed.connect(lambda msg: falhas.append(msg))

        with mock.patch.object(gui_mod, "argostranslate") as mock_argos:
            mock_argos.package.get_available_packages.side_effect = socket.timeout("timeout")
            thread.run()

        self.assertEqual(len(falhas), 1)
        self.assertEqual(socket.getdefaulttimeout(), self.original)


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 indisponível neste ambiente")
class TestPackageInstallThreadUsaTimeout(unittest.TestCase):
    _app = None

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original = socket.getdefaulttimeout()
        self.addCleanup(socket.setdefaulttimeout, self.original)

    def test_index_e_download_usam_timeouts_distintos(self):
        observado = {}

        def fake_update_index():
            observado["index"] = socket.getdefaulttimeout()

        class FakePkg:
            from_code = "pt"
            to_code = "en"

            def download(self):
                observado["download"] = socket.getdefaulttimeout()
                return "/tmp/fake.argosmodel"

        thread = gui_mod.PackageInstallThread("pt", "en")
        resultados = []
        thread.finished.connect(lambda ok, msg: resultados.append((ok, msg)))

        with mock.patch.object(gui_mod, "argostranslate") as mock_argos:
            mock_argos.package.update_package_index = fake_update_index
            mock_argos.package.get_available_packages.return_value = [FakePkg()]
            mock_argos.package.install_from_path.return_value = None
            thread.run()

        self.assertEqual(observado["index"], gui_mod.ARGOS_INDEX_TIMEOUT_S)
        self.assertEqual(observado["download"], gui_mod.ARGOS_DOWNLOAD_TIMEOUT_S)
        self.assertEqual(resultados, [(True, "Instalação concluída!")])
        self.assertEqual(socket.getdefaulttimeout(), self.original)

    def test_timeout_de_rede_reporta_mensagem_amigavel(self):
        thread = gui_mod.PackageInstallThread("pt", "en")
        resultados = []
        thread.finished.connect(lambda ok, msg: resultados.append((ok, msg)))

        with mock.patch.object(gui_mod, "argostranslate") as mock_argos:
            mock_argos.package.update_package_index.side_effect = socket.timeout("estourou")
            thread.run()

        self.assertEqual(len(resultados), 1)
        ok, msg = resultados[0]
        self.assertFalse(ok)
        self.assertIn("Tempo de conexão esgotado", msg)
        self.assertEqual(socket.getdefaulttimeout(), self.original)

    def test_pacote_inexistente_nao_tenta_baixar(self):
        thread = gui_mod.PackageInstallThread("pt", "xx")
        resultados = []
        thread.finished.connect(lambda ok, msg: resultados.append((ok, msg)))

        with mock.patch.object(gui_mod, "argostranslate") as mock_argos:
            mock_argos.package.update_package_index.return_value = None
            mock_argos.package.get_available_packages.return_value = []
            thread.run()

        self.assertEqual(len(resultados), 1)
        self.assertFalse(resultados[0][0])
        mock_argos.package.install_from_path.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
