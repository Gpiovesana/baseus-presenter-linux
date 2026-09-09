"""
Testes de app/config.py.

Alvo de maior retorno do projeto: lógica pura, sem Qt e sem hardware, e é onde
mora o risco de PERDA DE DADOS do usuário (migração v1->v2, merge de defaults,
JSON corrompido). Roda sem PyQt5/evdev/vosk instalados.

    python3 -m pytest tests/ -v
    (ou:  python3 -m unittest discover -s tests -v)
"""
import copy
import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as cfg

# Vários testes exercitam caminhos de erro de propósito (JSON corrompido, tipo
# inválido, falha de gravação). Silencia o log para a saída do teste ficar
# legível — as asserções, não o log, é que verificam o comportamento.
logging.disable(logging.CRITICAL)


class ConfigTestCase(unittest.TestCase):
    """Redireciona CONFIG_FILE para um diretório temporário."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config_file = os.path.join(self.tmpdir.name, "baseus_pointer.json")

        patcher_dir = mock.patch.object(cfg, "CONFIG_DIR", self.tmpdir.name)
        patcher_file = mock.patch.object(cfg, "CONFIG_FILE", self.config_file)
        patcher_dir.start(); self.addCleanup(patcher_dir.stop)
        patcher_file.start(); self.addCleanup(patcher_file.stop)

    def write_raw(self, text):
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(text)

    def write_json(self, data):
        self.write_raw(json.dumps(data))


class TestLoadDefaults(ConfigTestCase):
    def test_arquivo_ausente_retorna_defaults(self):
        loaded = cfg.load_config()
        self.assertEqual(loaded["active_profile"], "Padrão")
        self.assertIn("Padrão", loaded["profiles"])

    def test_defaults_nao_sao_compartilhados_entre_chamadas(self):
        """load_config deve devolver cópias, nunca o DEFAULT_CONFIG global."""
        a = cfg.load_config()
        a["profiles"]["Padrão"]["visual"]["laser_size"] = 999
        b = cfg.load_config()
        self.assertNotEqual(b["profiles"]["Padrão"]["visual"]["laser_size"], 999)
        self.assertEqual(
            cfg.DEFAULT_CONFIG["profiles"]["Padrão"]["visual"]["laser_size"], 30)

    def test_chave_nova_do_default_aparece_em_config_antigo(self):
        self.write_json({
            "config_version": 2,
            "active_profile": "Padrão",
            "profiles": {"Padrão": {"visual": {}, "audio": {}}},
        })
        loaded = cfg.load_config()
        # hardware foi adicionado depois; precisa ser mesclado.
        self.assertEqual(loaded["hardware"]["vendor_id"], "abc8")


class TestMigracao(ConfigTestCase):
    def test_migra_v1_preservando_dados_do_usuario(self):
        self.write_json({
            "close_behavior": "tray",
            "save_dir": "/tmp/aulas",
            "show_subtitles": False,
            "visual": {"laser_size": 77, "laser_color": "#00FF00"},
            "audio": {
                "selected_model_path": "/opt/vosk-pt",
                "target_lang": "es",
                "input_device": 3,
                "models": [{"label": "PT", "path": "/opt/vosk-pt"}],
            },
        })
        loaded = cfg.load_config()
        prof = loaded["profiles"]["Padrão"]

        self.assertEqual(loaded["close_behavior"], "tray")
        self.assertEqual(loaded["save_dir"], "/tmp/aulas")
        self.assertEqual(prof["visual"]["laser_size"], 77)
        self.assertEqual(prof["visual"]["laser_color"], "#00FF00")
        self.assertEqual(prof["audio"]["selected_model_path"], "/opt/vosk-pt")
        self.assertEqual(prof["audio"]["target_lang"], "es")
        self.assertEqual(prof["audio"]["input_device"], 3)
        self.assertFalse(prof["audio"]["show_subtitles"])
        # Modelos passaram a ser globais.
        self.assertEqual(loaded["models"], [{"label": "PT", "path": "/opt/vosk-pt"}])
        self.assertEqual(loaded["config_version"], cfg.CONFIG_VERSION)

    def test_config_v2_nao_e_remigrado(self):
        self.write_json({
            "config_version": 2,
            "active_profile": "Aula",
            "profiles": {"Aula": {"visual": {"laser_size": 42}, "audio": {}}},
        })
        loaded = cfg.load_config()
        self.assertEqual(loaded["active_profile"], "Aula")
        self.assertEqual(loaded["profiles"]["Aula"]["visual"]["laser_size"], 42)

    def test_espelho_legado_na_raiz_e_removido(self):
        """Versões antigas da GUI duplicavam visual/audio na raiz."""
        self.write_json({
            "config_version": 2,
            "active_profile": "Padrão",
            "visual": {"laser_size": 99},   # espelho obsoleto
            "audio": {"target_lang": "ru"},  # espelho obsoleto
            "profiles": {"Padrão": {"visual": {"laser_size": 30},
                                    "audio": {"target_lang": "en"}}},
        })
        loaded = cfg.load_config()
        self.assertNotIn("visual", loaded)
        self.assertNotIn("audio", loaded)
        # O perfil (fonte de verdade) permanece intacto.
        self.assertEqual(loaded["profiles"]["Padrão"]["audio"]["target_lang"], "en")

    def test_v2_sem_config_version_ainda_e_reconhecido(self):
        """Arquivos v2 gravados antes de config_version existir."""
        self.write_json({
            "active_profile": "Padrão",
            "profiles": {"Padrão": {"visual": {}, "audio": {}}},
        })
        loaded = cfg.load_config()
        self.assertEqual(loaded["config_version"], cfg.CONFIG_VERSION)


class TestDeepMerge(unittest.TestCase):
    def test_mescla_dicts_aninhados(self):
        base = {"a": {"x": 1, "y": 2}}
        cfg._deep_merge(base, {"a": {"y": 9}})
        self.assertEqual(base["a"], {"x": 1, "y": 9})

    def test_tipo_invalido_e_rejeitado(self):
        """String onde se espera int não deve passar e crashar depois."""
        base = {"laser_size": 30}
        cfg._deep_merge(base, {"laser_size": "grande"})
        self.assertEqual(base["laser_size"], 30)

    def test_bool_nao_e_aceito_como_int(self):
        base = {"laser_size": 30}
        cfg._deep_merge(base, {"laser_size": True})
        self.assertEqual(base["laser_size"], 30)

    def test_int_nao_e_aceito_como_bool(self):
        base = {"show_subtitles": True}
        cfg._deep_merge(base, {"show_subtitles": 1})
        self.assertTrue(base["show_subtitles"] is True)

    def test_valor_valido_e_aceito(self):
        base = {"laser_size": 30}
        cfg._deep_merge(base, {"laser_size": 55})
        self.assertEqual(base["laser_size"], 55)

    def test_none_no_default_aceita_qualquer_valor(self):
        """input_device tem default None e aceita int."""
        base = {"input_device": None}
        cfg._deep_merge(base, {"input_device": 4})
        self.assertEqual(base["input_device"], 4)

    def test_dict_onde_se_espera_escalar_nao_derruba(self):
        base = {"laser_size": 30}
        cfg._deep_merge(base, {"laser_size": {"nested": 1}})
        self.assertEqual(base["laser_size"], 30)

    def test_update_nao_dict_e_ignorado(self):
        base = {"a": 1}
        self.assertEqual(cfg._deep_merge(base, None), {"a": 1})


class TestArquivoCorrompido(ConfigTestCase):
    def test_json_truncado_usa_defaults_e_faz_backup(self):
        self.write_raw('{"active_profile": "Padrão", "profiles": {')
        loaded = cfg.load_config()
        self.assertEqual(loaded["active_profile"], "Padrão")
        # O arquivo problemático deve ser preservado, não descartado.
        self.assertTrue(os.path.exists(self.config_file + ".corrupt"))

    def test_raiz_nao_objeto_e_rejeitada(self):
        self.write_raw('["isso", "nao", "e", "um", "objeto"]')
        loaded = cfg.load_config()
        self.assertIn("profiles", loaded)

    def test_profiles_nulo_e_recriado(self):
        self.write_json({"config_version": 2, "profiles": None,
                         "active_profile": "Padrão"})
        loaded = cfg.load_config()
        self.assertIn("Padrão", loaded["profiles"])

    def test_perfil_ativo_inexistente_cai_no_primeiro(self):
        self.write_json({
            "config_version": 2,
            "active_profile": "Fantasma",
            "profiles": {"Real": {"visual": {}, "audio": {}}},
        })
        loaded = cfg.load_config()
        self.assertEqual(loaded["active_profile"], "Real")

    def test_perfil_padrao_excluido_nao_ressuscita(self):
        """
        Regressão: _deep_merge com DEFAULT_CONFIG reinjetava o perfil "Padrão",
        fazendo um perfil excluído pelo usuário reaparecer a cada reinício.
        """
        self.write_json({
            "config_version": 2,
            "active_profile": "Aula",
            "profiles": {"Aula": {"visual": {}, "audio": {}}},
        })
        loaded = cfg.load_config()
        self.assertNotIn("Padrão", loaded["profiles"])
        self.assertEqual(list(loaded["profiles"]), ["Aula"])

    def test_perfil_malformado_e_descartado(self):
        self.write_json({
            "config_version": 2,
            "active_profile": "Bom",
            "profiles": {
                "Bom": {"visual": {}, "audio": {}},
                "Ruim": "isso deveria ser um dict",
            },
        })
        loaded = cfg.load_config()
        self.assertIn("Bom", loaded["profiles"])
        self.assertNotIn("Ruim", loaded["profiles"])


class TestSaveAtomico(ConfigTestCase):
    def test_round_trip(self):
        data = cfg.load_config()
        data["profiles"]["Padrão"]["visual"]["laser_size"] = 88
        cfg.save_config(data)
        self.assertEqual(
            cfg.load_config()["profiles"]["Padrão"]["visual"]["laser_size"], 88)

    def test_nao_deixa_tmp_para_tras(self):
        cfg.save_config(cfg.load_config())
        self.assertFalse(os.path.exists(self.config_file + ".tmp"))

    def test_falha_na_gravacao_preserva_arquivo_anterior(self):
        cfg.save_config(cfg.load_config())
        with open(self.config_file, encoding="utf-8") as f:
            original = f.read()

        # json.dump falha no meio: o arquivo final não pode ser corrompido.
        class NaoSerializavel:
            pass

        cfg.save_config({"ruim": NaoSerializavel()})

        with open(self.config_file, encoding="utf-8") as f:
            self.assertEqual(f.read(), original)
        self.assertFalse(os.path.exists(self.config_file + ".tmp"))


class TestAcessadores(unittest.TestCase):
    def test_audio_e_visual_apontam_para_o_perfil_ativo(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        cfg.audio_cfg(data)["target_lang"] = "fr"
        self.assertEqual(
            data["profiles"]["Padrão"]["audio"]["target_lang"], "fr")

        cfg.visual_cfg(data)["laser_size"] = 12
        self.assertEqual(data["profiles"]["Padrão"]["visual"]["laser_size"], 12)

    def test_perfil_ativo_ausente_e_criado(self):
        data = {"active_profile": "Novo", "profiles": {}}
        prof = cfg.active_profile(data)
        self.assertIn("Novo", data["profiles"])
        self.assertIn("visual", prof)

    def test_acessadores_funcionam_sem_espelho_na_raiz(self):
        """
        Regressão do bug original: a AudioThread estourava KeyError porque
        config["audio"] só existia depois da GUI criar o "espelho".
        """
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        self.assertNotIn("audio", data)  # não há espelho na raiz
        self.assertEqual(cfg.audio_cfg(data).get("target_lang"), "en")


class TestConfigWrapper(ConfigTestCase):
    def test_getters_leem_do_perfil_ativo(self):
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        self.assertEqual(c.get_audio("target_lang"), "en")
        self.assertEqual(c.get_visual("laser_size"), 30)
        self.assertEqual(c.get("close_behavior"), "quit")

    def test_setters_escrevem_no_perfil_ativo(self):
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        c.set_audio("target_lang", "de")
        c.set_visual("laser_size", 44)
        self.assertEqual(c.get_audio("target_lang"), "de")
        self.assertEqual(
            c.snapshot()["profiles"]["Padrão"]["visual"]["laser_size"], 44)

    def test_snapshot_e_isolado(self):
        """Mutar o snapshot não pode afetar o config real (nem vice-versa)."""
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        snap = c.snapshot()
        snap["profiles"]["Padrão"]["visual"]["laser_size"] = 999
        self.assertEqual(c.get_visual("laser_size"), 30)

    def test_getter_retorna_copia(self):
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        got = c.get("models")
        got.append({"label": "x"})
        self.assertEqual(c.get("models"), [])

    def test_mutate_permite_operacao_composta(self):
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        with c.mutate() as data:
            data["profiles"]["Aula"] = copy.deepcopy(data["profiles"]["Padrão"])
            data["active_profile"] = "Aula"
        self.assertEqual(c.snapshot()["active_profile"], "Aula")

    def test_mutate_libera_o_lock_mesmo_com_excecao(self):
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        with self.assertRaises(RuntimeError):
            with c.mutate():
                raise RuntimeError("boom")
        # Se o lock tivesse vazado, isto travaria para sempre.
        self.assertEqual(c.get_visual("laser_size"), 30)

    def test_save_persiste_em_disco(self):
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        c.set_visual("laser_size", 61)
        c.save()
        self.assertEqual(
            cfg.load_config()["profiles"]["Padrão"]["visual"]["laser_size"], 61)

    def test_acesso_concorrente_nao_corrompe(self):
        import threading
        c = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        erros = []

        def escritor():
            try:
                for i in range(200):
                    c.set_visual("laser_size", 10 + (i % 90))
            except Exception as e:  # pragma: no cover
                erros.append(e)

        def leitor():
            try:
                for _ in range(200):
                    # Nunca deve levantar KeyError nem ver estado parcial.
                    self.assertIsInstance(c.get_visual("laser_size"), int)
                    self.assertIn("profiles", c.snapshot())
            except Exception as e:  # pragma: no cover
                erros.append(e)

        threads = [threading.Thread(target=escritor) for _ in range(2)]
        threads += [threading.Thread(target=leitor) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(erros, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
