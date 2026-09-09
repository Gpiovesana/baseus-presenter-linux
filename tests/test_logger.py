"""
Testes de app/logger.py — Etapa 2 da auditoria (#29).

O bug: cada get_logger(name) criava seu PRÓPRIO RotatingFileHandler para o
mesmo arquivo. Quando um handler rotacionava, os outros continuavam com o
descritor do inode antigo (depois removido), perdendo mensagens recentes.

    python3 -m unittest discover -s tests -p "test_logger.py" -v
"""
import glob
import importlib
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LoggerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.log_path = os.path.join(self.tmpdir.name, "baseus.log")

        # Recarrega o módulo com LOG_DIR/LOG_PATH redirecionados e o estado
        # de configuração zerado.
        import app.logger as logger_mod
        self.logger_mod = importlib.reload(logger_mod)
        self.logger_mod.LOG_DIR = self.tmpdir.name
        self.logger_mod.LOG_PATH = self.log_path
        self.logger_mod._configured = False

        root = logging.getLogger(self.logger_mod._ROOT_LOGGER_NAME)
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()

        self.addCleanup(self._cleanup_handlers)
        logging.disable(logging.NOTSET)  # os testes precisam do log ativo

    def _cleanup_handlers(self):
        root = logging.getLogger(self.logger_mod._ROOT_LOGGER_NAME)
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        logging.disable(logging.CRITICAL)


class TestHandlerUnico(LoggerTestCase):
    """#29: só pode existir UM handler de arquivo no processo."""

    def test_multiplos_loggers_compartilham_um_unico_file_handler(self):
        self.logger_mod.get_logger("app.audio")
        self.logger_mod.get_logger("app.gui")
        self.logger_mod.get_logger("app.hardware")
        self.logger_mod.get_logger("Main")

        root = logging.getLogger(self.logger_mod._ROOT_LOGGER_NAME)
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        self.assertEqual(
            len(file_handlers), 1,
            f"esperado exatamente 1 RotatingFileHandler, achei {len(file_handlers)}")

    def test_loggers_filhos_nao_tem_handlers_proprios(self):
        child = self.logger_mod.get_logger("app.audio")
        self.assertEqual(child.handlers, [])
        self.assertTrue(child.propagate)

    def test_nome_sem_prefixo_e_normalizado_para_filho_de_app(self):
        logger = self.logger_mod.get_logger("Main")
        self.assertEqual(logger.name, "app.Main")

    def test_nome_com_prefixo_e_preservado(self):
        logger = self.logger_mod.get_logger("app.hardware")
        self.assertEqual(logger.name, "app.hardware")


class TestRotacaoNaoPerdeMensagens(LoggerTestCase):
    """
    Reproduz o cenário do achado: vários loggers escrevendo enquanto o
    arquivo rotaciona. Com o handler único, nenhuma mensagem pode ficar
    órfã num inode removido.
    """

    def test_mensagem_recente_sobrevive_a_rotacao(self):
        # Handler com limite minúsculo para forçar várias rotações.
        root = logging.getLogger(self.logger_mod._ROOT_LOGGER_NAME)
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()

        handler = logging.handlers.RotatingFileHandler(
            self.log_path, maxBytes=500, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.logger_mod._configured = True

        a = self.logger_mod.get_logger("app.audio")
        b = self.logger_mod.get_logger("app.gui")

        # Gera tráfego suficiente para rotacionar várias vezes.
        for i in range(200):
            a.info(f"audio linha {i} " + "x" * 20)
            b.info(f"gui linha {i} " + "y" * 20)

        marcador = "MARCADOR-FINAL-UNICO"
        a.info(marcador)
        handler.flush()

        # O marcador deve estar em algum dos arquivos vivos (atual ou backup).
        conteudo = ""
        for caminho in glob.glob(self.log_path + "*"):
            with open(caminho, encoding="utf-8", errors="replace") as f:
                conteudo += f.read()

        self.assertIn(
            marcador, conteudo,
            "mensagem recente foi perdida na rotação (inode órfão)")


class TestResilienciaDeIO(LoggerTestCase):
    """O logger não deve derrubar o app se não puder escrever em disco."""

    def test_falha_ao_criar_diretorio_nao_levanta(self):
        self.logger_mod._configured = False
        root = logging.getLogger(self.logger_mod._ROOT_LOGGER_NAME)
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()

        with mock.patch.object(self.logger_mod.os, "makedirs",
                               side_effect=OSError("sem permissão")), \
             mock.patch("builtins.print"):  # silencia o aviso do fallback
            logger = self.logger_mod.get_logger("app.audio")  # não deve levantar

        # Deve continuar utilizável (console handler).
        logger.setLevel(logging.CRITICAL + 1)  # evita poluir a saída do teste
        logger.info("ainda funciona")
        logger.setLevel(logging.DEBUG)
        stream_handlers = [
            h for h in root.handlers if isinstance(h, logging.StreamHandler)
        ]
        self.assertGreaterEqual(len(stream_handlers), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
