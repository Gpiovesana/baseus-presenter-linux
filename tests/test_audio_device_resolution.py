"""
Testes de app/audio.py — resolução de dispositivo e monitor de nível.

BUG DE PRODUÇÃO que originou estes testes: o app salvava `input_device` como
um ÍNDICE numérico do PortAudio. Índices NÃO são estáveis — mudam quando
dispositivos aparecem/desaparecem, inclusive quando o próprio app abre o
Baseus em modo exclusivo (o `hw:` sai da enumeração e desloca os índices
seguintes). Resultado: o perfil tinha `input_device=15` mas na execução
seguinte esse índice podia não existir, ou apontar silenciosamente para
OUTRO microfone (ex.: o da placa-mãe), sem erro nenhum.

Também cobre o monitor de nível de entrada, que detecta a falha silenciosa
"stream aberto mas sem áudio chegando".

    python3 -m unittest discover -s tests -p "test_audio_device_resolution.py" -v
"""
import array
import copy
import logging
import math
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

from app import config as cfg
from app import audio as audio_mod


def fake_devices(*nomes_entrada):
    """
    Monta uma lista de dispositivos no formato do sounddevice.

    Intercala saídas (max_input_channels=0) para garantir que os índices não
    sejam sequenciais — exatamente a condição que causava o bug.
    """
    devs = [{"name": "Saida Qualquer", "max_input_channels": 0}]
    for nome in nomes_entrada:
        devs.append({"name": nome, "max_input_channels": 1})
        devs.append({"name": f"{nome} (saida)", "max_input_channels": 0})
    return devs


class DeviceResolutionTestCase(unittest.TestCase):
    def setUp(self):
        self.config = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))

    def make_thread(self):
        return audio_mod.AudioThread(self.config)


class TestResolucaoPorNome(DeviceResolutionTestCase):
    """O NOME é a fonte de verdade; o índice é apenas dica legada."""

    def test_nome_vence_indice_desatualizado(self):
        # "Baseus" está no índice 3 agora, mas o config salvou 15.
        devs = fake_devices("Placa Mae", "BaseusPresent: USB Audio (hw:3,0)")
        self.config.set_audio("input_device", 15)          # índice obsoleto
        self.config.set_audio("input_device_name", "BaseusPresent: USB Audio (hw:3,0)")

        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            resolvido = thread._get_device_id()

        self.assertEqual(devs[resolvido]["name"], "BaseusPresent: USB Audio (hw:3,0)")
        self.assertNotEqual(resolvido, 15)

    def test_nome_ausente_cai_no_padrao_em_vez_do_mic_errado(self):
        """
        O ponto central do bug: NUNCA devolver um índice que aponta para
        outro microfone. Se o dispositivo salvo não existe, usar o padrão
        do sistema (None) é o comportamento correto.
        """
        devs = fake_devices("Placa Mae")  # Baseus desconectado
        self.config.set_audio("input_device", 15)
        self.config.set_audio("input_device_name", "BaseusPresent: USB Audio (hw:3,0)")

        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            self.assertIsNone(thread._get_device_id())

    def test_indice_igual_ao_salvo_tambem_funciona(self):
        devs = fake_devices("BaseusPresent: USB Audio (hw:3,0)")
        idx_real = 1  # primeiro dispositivo de entrada
        self.config.set_audio("input_device", idx_real)
        self.config.set_audio("input_device_name", "BaseusPresent: USB Audio (hw:3,0)")

        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            self.assertEqual(thread._get_device_id(), idx_real)


class TestConfigLegado(DeviceResolutionTestCase):
    """Configs antigas só têm o índice; precisam ser validadas antes de usar."""

    def test_indice_legado_valido_e_aceito(self):
        devs = fake_devices("Placa Mae", "Baseus")
        self.config.set_audio("input_device", 1)  # entrada válida
        self.config.set_audio("input_device_name", None)

        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            self.assertEqual(thread._get_device_id(), 1)

    def test_indice_legado_fora_do_range_e_rejeitado(self):
        devs = fake_devices("Placa Mae")
        self.config.set_audio("input_device", 99)
        self.config.set_audio("input_device_name", None)

        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            self.assertIsNone(thread._get_device_id())

    def test_indice_legado_apontando_para_saida_e_rejeitado(self):
        """Índice 0 existe, mas é um dispositivo de SAÍDA (0 canais de entrada)."""
        devs = fake_devices("Placa Mae")
        self.config.set_audio("input_device", 0)
        self.config.set_audio("input_device_name", None)

        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            self.assertIsNone(thread._get_device_id())


class TestAutodeteccao(DeviceResolutionTestCase):
    """Sem nada salvo, tenta achar o Baseus sozinho."""

    def test_encontra_baseus_automaticamente(self):
        devs = fake_devices("Placa Mae", "BaseusPresent: USB Audio")
        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            resolvido = thread._get_device_id()
        self.assertIn("baseus", devs[resolvido]["name"].lower())

    def test_sem_baseus_usa_padrao_do_sistema(self):
        devs = fake_devices("Placa Mae")
        thread = self.make_thread()
        with mock.patch.object(audio_mod.sd, "query_devices", return_value=devs):
            self.assertIsNone(thread._get_device_id())


class TestRmsHelper(unittest.TestCase):
    """O cálculo de RMS usa só a stdlib; precisa ser correto o suficiente."""

    def test_silencio_da_zero(self):
        self.assertEqual(audio_mod._rms_int16(bytes(8000)), 0.0)

    def test_tom_alto_da_valor_alto(self):
        tom = array.array('h', [int(10000 * math.sin(i * 0.1)) for i in range(4000)])
        rms = audio_mod._rms_int16(tom.tobytes())
        # RMS de uma senoide de amplitude A é A/sqrt(2) ~= 7071
        self.assertGreater(rms, 6000)
        self.assertLess(rms, 8000)

    def test_bloco_vazio_nao_estoura(self):
        self.assertEqual(audio_mod._rms_int16(b""), 0.0)

    def test_classifica_silencio_abaixo_do_limiar(self):
        quase_mudo = array.array('h', [5] * 4000)
        self.assertLess(audio_mod._rms_int16(quase_mudo.tobytes()),
                        audio_mod._LEVEL_SILENCE_RMS)


class TestMonitorDeNivel(DeviceResolutionTestCase):
    """
    Detecta a falha silenciosa: stream aberto, blocos chegando, mas mudos.
    Antes o app simplesmente não transcrevia nada, sem nenhum aviso.
    """

    def _bloco_silencio(self):
        return bytes(8000)

    def _bloco_com_voz(self):
        tom = array.array('h', [int(8000 * math.sin(i * 0.1)) for i in range(4000)])
        return tom.tobytes()

    def test_avisa_quando_nao_chega_audio(self):
        thread = self.make_thread()
        thread.is_recording = True
        avisos = []
        thread.audio_warning.connect(lambda m: avisos.append(m))

        thread._reset_level_monitor()
        # Força a janela de análise a já ter expirado.
        thread._level_window_start = time.monotonic() - (audio_mod._LEVEL_CHECK_WINDOW_S + 1)
        thread._monitor_input_level(self._bloco_silencio())

        self.assertEqual(len(avisos), 1)
        self.assertIn("sem sinal", avisos[0].lower())

    def test_nao_avisa_quando_ha_audio(self):
        thread = self.make_thread()
        thread.is_recording = True
        avisos = []
        thread.audio_warning.connect(lambda m: avisos.append(m))

        thread._reset_level_monitor()
        thread._monitor_input_level(self._bloco_com_voz())
        thread._level_window_start = time.monotonic() - (audio_mod._LEVEL_CHECK_WINDOW_S + 1)
        thread._monitor_input_level(self._bloco_com_voz())

        self.assertEqual(avisos, [])

    def test_avisa_apenas_uma_vez_por_queda(self):
        """Não deve inundar a UI com o mesmo aviso a cada janela."""
        thread = self.make_thread()
        thread.is_recording = True
        avisos = []
        thread.audio_warning.connect(lambda m: avisos.append(m))

        thread._reset_level_monitor()
        for _ in range(3):
            thread._level_window_start = time.monotonic() - (audio_mod._LEVEL_CHECK_WINDOW_S + 1)
            thread._monitor_input_level(self._bloco_silencio())

        self.assertEqual(len(avisos), 1)

    def test_rearma_o_aviso_depois_de_voltar_o_audio(self):
        thread = self.make_thread()
        thread.is_recording = True
        avisos = []
        thread.audio_warning.connect(lambda m: avisos.append(m))

        thread._reset_level_monitor()

        # 1ª queda -> avisa
        thread._level_window_start = time.monotonic() - (audio_mod._LEVEL_CHECK_WINDOW_S + 1)
        thread._monitor_input_level(self._bloco_silencio())
        # Áudio volta -> rearma
        thread._level_window_start = time.monotonic() - (audio_mod._LEVEL_CHECK_WINDOW_S + 1)
        thread._monitor_input_level(self._bloco_com_voz())
        # 2ª queda -> avisa de novo
        thread._level_window_start = time.monotonic() - (audio_mod._LEVEL_CHECK_WINDOW_S + 1)
        thread._monitor_input_level(self._bloco_silencio())

        self.assertEqual(len(avisos), 2)

    def test_nao_avalia_antes_de_fechar_a_janela(self):
        thread = self.make_thread()
        thread.is_recording = True
        avisos = []
        thread.audio_warning.connect(lambda m: avisos.append(m))

        thread._reset_level_monitor()
        thread._monitor_input_level(self._bloco_silencio())  # janela ainda aberta

        self.assertEqual(avisos, [])

    def test_reset_limpa_estado_do_aviso(self):
        thread = self.make_thread()
        thread._level_warned = True
        thread._level_peak = 999.0
        thread._reset_level_monitor()
        self.assertFalse(thread._level_warned)
        self.assertEqual(thread._level_peak, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
