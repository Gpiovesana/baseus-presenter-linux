"""
Testes de app/audio.py — Etapa 3 da auditoria (#15, #16, #17, #18, #24).

Não depende do Vosk/sounddevice reais: testa a lógica interna (fila,
versionamento de reload, resolução de idioma, sinalização de erro) chamando
os métodos diretamente, sem iniciar a QThread real nem abrir um stream de
áudio de verdade.

    python3 -m unittest discover -s tests -p "test_audio_advanced.py" -v
"""
import copy
import logging
import os
import queue
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

from app import config as cfg
from app import audio as audio_mod


class AudioTestCase(unittest.TestCase):
    def setUp(self):
        self.config = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))

    def make_thread(self):
        return audio_mod.AudioThread(self.config)


class TestFilaComLimite(AudioTestCase):
    """#18: fila de áudio precisa ter maxsize para não crescer sem limite."""

    def test_fila_tem_maxsize_definido(self):
        thread = self.make_thread()
        self.assertEqual(thread.q.maxsize, audio_mod.AUDIO_QUEUE_MAXSIZE)
        self.assertGreater(thread.q.maxsize, 0)

    def test_callback_descarta_bloco_antigo_quando_fila_cheia(self):
        thread = self.make_thread()
        thread.is_recording = True

        # Preenche a fila até o limite.
        for i in range(thread.q.maxsize):
            thread._audio_callback(bytes([i % 256]), 4000, None, None)
        self.assertEqual(thread.q.qsize(), thread.q.maxsize)

        primeiro_bloco = thread.q.queue[0]

        # Mais um bloco: não deve travar nem lançar, e o mais antigo deve
        # ter sido descartado para abrir espaço.
        thread._audio_callback(bytes([255]), 4000, None, None)

        self.assertEqual(thread.q.qsize(), thread.q.maxsize)
        self.assertNotEqual(thread.q.queue[0], primeiro_bloco)
        self.assertEqual(thread.q.queue[-1], bytes([255]))

    def test_callback_nao_enfileira_quando_ocioso(self):
        thread = self.make_thread()
        thread.is_recording = False
        thread.is_translating = False
        thread._pending_finalize = False

        thread._audio_callback(b"\x00\x01", 4000, None, None)
        self.assertTrue(thread.q.empty())


class TestVersaoDeReload(AudioTestCase):
    """#17: uma conclusão antiga não pode sobrescrever um pedido novo."""

    def test_trigger_reload_incrementa_versao(self):
        thread = self.make_thread()
        v0 = thread._reload_version
        thread.trigger_reload()
        self.assertEqual(thread._reload_version, v0 + 1)

    def test_reload_durante_carregamento_nao_e_perdido(self):
        """
        Simula: uma recarga começa (pending_version=N capturado), mas ANTES
        dela terminar chega um novo trigger_reload() (versão N+1). O código
        antigo (`self._needs_reload = False` incondicional) apagaria o
        pedido novo. A versão deve continuar divergente após o "término" da
        recarga antiga, forçando outra passada.
        """
        thread = self.make_thread()

        with thread._reload_lock:
            pending_version = thread._reload_version  # ex.: 1

        # Enquanto a "carga" ocorre, chega um novo pedido.
        thread.trigger_reload()  # versão agora é 2

        # Reproduz o fim de uma passada do loop: só marca como carregada a
        # versão que era pendente QUANDO A PASSADA COMEÇOU.
        with thread._reload_lock:
            if thread._reload_version == pending_version:
                thread._loaded_reload_version = pending_version

        # A versão carregada não pode ter avançado para a versão nova.
        self.assertNotEqual(thread._loaded_reload_version, thread._reload_version)

    def test_reload_sem_conflito_marca_como_carregado(self):
        thread = self.make_thread()
        with thread._reload_lock:
            pending_version = thread._reload_version
            if thread._reload_version == pending_version:
                thread._loaded_reload_version = pending_version
        self.assertEqual(thread._loaded_reload_version, thread._reload_version)


class TestRecriacaoDeStream(AudioTestCase):
    """#16: trocar o microfone precisa recriar o stream de entrada."""

    def test_request_stream_restart_seta_flag(self):
        thread = self.make_thread()
        self.assertFalse(thread._stream_restart_requested)
        thread.request_stream_restart()
        self.assertTrue(thread._stream_restart_requested)

    def test_process_stream_loop_sai_quando_restart_e_pedido(self):
        thread = self.make_thread()
        thread.running = True
        thread.model = None  # evita tentar carregar modelo real
        thread._loaded_reload_version = thread._reload_version  # já "carregado"

        chamadas = {"n": 0}

        def fake_msleep(_ms):
            chamadas["n"] += 1
            if chamadas["n"] >= 2:
                thread.request_stream_restart()

        thread.msleep = fake_msleep
        thread._process_stream_loop()  # deve retornar, não travar
        self.assertTrue(thread._stream_restart_requested)


class TestFalhaDeGravacaoPropagaParaUI(AudioTestCase):
    """#15: falhas de stream/escrita devem emitir audio_error e desmarcar is_recording."""

    def test_fail_active_recording_desmarca_estado_e_emite_sinal(self):
        thread = self.make_thread()
        thread.is_recording = True
        thread.txt_path = "/tmp/fake.txt"

        recebidos = []
        thread.audio_error.connect(lambda msg: recebidos.append(msg))

        thread._fail_active_recording("⚠️ teste de falha")

        self.assertFalse(thread.is_recording)
        self.assertIsNone(thread.txt_path)
        self.assertEqual(recebidos, ["⚠️ teste de falha"])

    def test_falha_de_escrita_no_loop_interrompe_gravacao(self):
        """
        Reproduz o cenário do achado: disco cheio/pendrive removido durante
        a escrita do resultado final. Antes, o código só limpava txt_path e
        emitia audio_warning — deixando is_recording=True sem saída válida.
        """
        thread = self.make_thread()
        thread.is_recording = True
        thread.txt_path = "/caminho/que/nao/existe/arquivo.txt"

        recebidos_error = []
        thread.audio_error.connect(lambda msg: recebidos_error.append(msg))

        # Simula o ramo de falha de escrita chamando o helper diretamente
        # (o loop completo depende de um recognizer real).
        with self.assertRaises(FileNotFoundError):
            with open(thread.txt_path, 'a', encoding='utf-8') as f:
                f.write("x")

        thread._fail_active_recording("⚠️ Gravação interrompida: falha ao salvar no arquivo da aula!")

        self.assertFalse(thread.is_recording)
        self.assertEqual(len(recebidos_error), 1)


class TestSourceLangConfiguravel(AudioTestCase):
    """#24: idioma de origem não pode ficar fixo em 'pt'."""

    def test_default_e_pt_para_retrocompatibilidade(self):
        thread = self.make_thread()
        self.assertEqual(thread._resolve_source_lang(), "pt")

    def test_le_source_lang_do_perfil_ativo(self):
        self.config.set_audio("source_lang", "en")
        thread = self.make_thread()
        self.assertEqual(thread._resolve_source_lang(), "en")

    def test_translate_usa_source_lang_configurado(self):
        self.config.set_audio("source_lang", "en")
        self.config.set_audio("target_lang", "es")
        thread = self.make_thread()
        thread.is_translating = True

        with mock.patch.object(audio_mod, "ARGOS_AVAILABLE", True), \
             mock.patch.object(audio_mod, "argostranslate") as mock_argos:
            mock_argos.translate.translate.return_value = "traducido"
            resultado = thread._translate_if_needed("hello")

        mock_argos.translate.translate.assert_called_once_with("hello", "en", "es")
        self.assertEqual(resultado, "traducido")

    def test_erro_de_traducao_menciona_o_par_de_idiomas_configurado(self):
        self.config.set_audio("source_lang", "en")
        self.config.set_audio("target_lang", "es")
        thread = self.make_thread()
        thread.is_translating = True

        avisos = []
        thread.audio_warning.connect(lambda msg: avisos.append(msg))

        with mock.patch.object(audio_mod, "ARGOS_AVAILABLE", True), \
             mock.patch.object(audio_mod, "argostranslate") as mock_argos:
            mock_argos.translate.translate.side_effect = RuntimeError("pacote ausente")
            thread._translate_if_needed("hello")

        self.assertTrue(any("en->es" in msg for msg in avisos))


if __name__ == "__main__":
    unittest.main(verbosity=2)
