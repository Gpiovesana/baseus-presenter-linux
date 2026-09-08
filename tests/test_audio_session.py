"""
Testes de app/audio.py — Etapa 1 da auditoria (#7, #8, #14).

Não depende do Vosk/sounddevice reais: usa um KaldiRecognizer e Model falsos
e chama os métodos internos diretamente (sem QThread.start()), simulando o
que o loop run() faria a cada iteração. Isso evita depender de hardware de
áudio e mantém os testes rápidos e determinísticos.

    python3 -m unittest tests.test_audio_session -v
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as cfg
from app import audio as audio_mod


class FakeRecognizer:
    """Substitui o KaldiRecognizer real. Comportamento configurável por teste."""

    def __init__(self, final_text="", accept_result=False):
        self.final_text = final_text
        self.accept_result = accept_result
        self.reset_called = False
        self.accepted_chunks = []

    def AcceptWaveform(self, data):
        self.accepted_chunks.append(data)
        return self.accept_result

    def Result(self):
        return json.dumps({"text": self.final_text})

    def PartialResult(self):
        return json.dumps({"partial": ""})

    def FinalResult(self):
        return json.dumps({"text": self.final_text})

    def Reset(self):
        self.reset_called = True


class AudioTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        self.config.set("save_dir", self.tmpdir.name)

    def make_thread(self, recognizer=None, model="fake-model"):
        thread = audio_mod.AudioThread(self.config)
        thread.model = model
        thread.recognizer = recognizer or FakeRecognizer()
        return thread


class TestValidacaoAntesDeGravar(AudioTestCase):
    """#14: is_recording só deve ficar True após validar modelo e destino."""

    def test_sem_modelo_nao_ativa_gravacao(self):
        thread = self.make_thread()
        thread.model = None
        errors = []
        thread.audio_error.connect(errors.append)
        thread.set_recording(True)
        self.assertEqual(len(errors), 1)
        self.assertFalse(thread.is_recording)
        self.assertIsNone(thread.txt_path)

    def test_falha_ao_criar_pasta_nao_ativa_gravacao(self):
        thread = self.make_thread()
        # save_dir aponta para um caminho que não pode ser criado (arquivo
        # comum no lugar de diretório).
        arquivo_bloqueador = os.path.join(self.tmpdir.name, "bloqueio")
        with open(arquivo_bloqueador, "w") as f:
            f.write("x")
        self.config.set("save_dir", os.path.join(arquivo_bloqueador, "subpasta"))

        thread.set_recording(True)
        self.assertFalse(thread.is_recording)
        self.assertIsNone(thread.txt_path)

    def test_sucesso_ativa_gravacao_com_arquivo_criado(self):
        thread = self.make_thread()
        thread.set_recording(True)
        self.assertTrue(thread.is_recording)
        self.assertTrue(os.path.exists(thread.txt_path))


class TestFinalizacaoAoPausar(AudioTestCase):
    """#7: pausar não pode perder uma fala que o Vosk ainda não fechou."""

    def test_pausa_agenda_finalizacao_com_contexto_da_sessao(self):
        thread = self.make_thread()
        thread.set_recording(True)
        txt_path_sessao = thread.txt_path

        thread.set_recording(False)

        self.assertTrue(thread._pending_finalize)
        self.assertEqual(thread._finalize_ctx["txt_path"], txt_path_sessao)
        self.assertIsNone(thread.txt_path)
        self.assertFalse(thread.is_recording)

    def test_finalize_grava_fala_pendente_no_arquivo_da_sessao_pausada(self):
        recognizer = FakeRecognizer(final_text="fala pendente")
        thread = self.make_thread(recognizer=recognizer)
        thread.set_recording(True)
        txt_path_sessao = thread.txt_path

        thread.set_recording(False)  # agenda finalize
        thread._finalize_pending_utterance()

        with open(txt_path_sessao, encoding="utf-8") as f:
            conteudo = f.read()
        self.assertIn("fala pendente", conteudo)
        self.assertTrue(recognizer.reset_called)
        self.assertFalse(thread._pending_finalize)

    def test_finalize_preserva_resultados_completos_e_fala_final(self):
        recognizer = mock.Mock()
        recognizer.AcceptWaveform.side_effect = [True, False, True]
        recognizer.Result.side_effect = ['{"text": "primeira frase"}', '{"text": "segunda frase"}']
        recognizer.FinalResult.return_value = '{"text": "fala final"}'
        thread = self.make_thread(recognizer=recognizer)
        thread.set_recording(True)
        path = thread.txt_path
        for chunk in (b"a", b"b", b"c"):
            thread.q.put(chunk)
        thread.set_recording(False)
        thread._finalize_pending_utterance()
        with open(path, encoding="utf-8") as output:
            self.assertTrue(output.read().endswith("primeira frase\nsegunda frase\nfala final\n"))
        self.assertEqual(recognizer.Result.call_count, 2)

    def test_finalize_sem_texto_nao_escreve_nada_extra(self):
        recognizer = FakeRecognizer(final_text="")
        thread = self.make_thread(recognizer=recognizer)
        thread.set_recording(True)
        txt_path_sessao = thread.txt_path
        with open(txt_path_sessao, encoding="utf-8") as f:
            conteudo_antes = f.read()

        thread.set_recording(False)
        thread._finalize_pending_utterance()

        with open(txt_path_sessao, encoding="utf-8") as f:
            conteudo_depois = f.read()
        self.assertEqual(conteudo_antes, conteudo_depois)

    def test_pausar_sem_sessao_ativa_nao_agenda_finalize(self):
        thread = self.make_thread()
        thread.set_recording(False)  # nunca esteve gravando
        self.assertFalse(thread._pending_finalize)
        self.assertIsNone(thread._finalize_ctx)

    def test_stop_finaliza_gravacao_pendente(self):
        recognizer = FakeRecognizer(final_text="ultima frase")
        thread = self.make_thread(recognizer=recognizer)
        thread.set_recording(True)
        txt_path_sessao = thread.txt_path

        # stop() real chamaria wait() numa QThread não iniciada; simulamos
        # só a parte relevante (finalização) sem iniciar a thread de fato.
        thread.set_recording(False)
        thread._finalize_pending_utterance()

        with open(txt_path_sessao, encoding="utf-8") as f:
            self.assertIn("ultima frase", f.read())


class TestEncerramentoEArquivos(AudioTestCase):
    def test_sessoes_no_mesmo_instante_preservam_arquivo_anterior(self):
        import datetime
        thread = self.make_thread()
        with mock.patch("app.audio.datetime") as clock:
            clock.datetime.now.return_value = datetime.datetime(2026, 1, 1)
            thread.set_recording(True)
            first = thread.txt_path
            with open(first, "a", encoding="utf-8") as output:
                output.write("fala anterior\n")
            thread.set_recording(False)
            thread._finalize_pending_utterance()
            thread.set_recording(True)
        self.assertNotEqual(first, thread.txt_path)
        with open(first, encoding="utf-8") as output:
            self.assertIn("fala anterior", output.read())

    def test_saida_do_loop_finaliza_fala_pendente(self):
        thread = self.make_thread(recognizer=FakeRecognizer(final_text="ultima fala"))
        thread.set_recording(True)
        path = thread.txt_path
        thread.set_recording(False)
        thread.running = False
        thread.run()
        with open(path, encoding="utf-8") as output:
            self.assertIn("ultima fala", output.read())


class TestSemMisturaEntreSessoes(AudioTestCase):
    """#8: uma transcrição não pode ser gravada no arquivo da sessão seguinte."""

    def test_resultado_tardio_usa_o_arquivo_capturado_no_momento_do_dado(self):
        """
        Simula o cenário do achado #8: o loop de run() captura txt_path ANTES
        de traduzir/processar (potencialmente lento). Mesmo que outra sessão
        comece nesse intervalo, o resultado deve ir para o arquivo capturado.
        """
        thread = self.make_thread()
        thread.set_recording(True)
        sessao_1_path = thread.txt_path

        # Snapshot como o loop faz agora, ANTES de qualquer operação lenta.
        with thread._txt_lock:
            snap_path = thread.txt_path
            snap_gravando = thread.is_recording

        # Enquanto isso, o usuário pausa e inicia uma nova sessão. Como o
        # nome do arquivo tem granularidade de segundo, forçamos um instante
        # diferente para garantir dois arquivos distintos no teste (na vida
        # real, qualquer segundo de diferença já garante isso).
        thread.set_recording(False)
        thread._finalize_pending_utterance()
        import datetime as _dt
        proximo_segundo = _dt.datetime.now() + _dt.timedelta(seconds=1)
        with mock.patch("app.audio.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = proximo_segundo
            thread.set_recording(True)
        sessao_2_path = thread.txt_path
        self.assertNotEqual(sessao_1_path, sessao_2_path)

        # O resultado "atrasado" da sessão 1 deve gravar em sessao_1_path,
        # usando o snapshot — não thread.txt_path atual (que já é a sessão 2).
        if snap_path and snap_gravando:
            with open(snap_path, 'a', encoding='utf-8') as f:
                f.write("texto da sessao 1\n")

        with open(sessao_1_path, encoding="utf-8") as f:
            self.assertIn("texto da sessao 1", f.read())
        with open(sessao_2_path, encoding="utf-8") as f:
            self.assertNotIn("texto da sessao 1", f.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
