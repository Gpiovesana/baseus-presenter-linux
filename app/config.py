# ~/Documentos/Projetos/baseus-presenter-linux/app/config.py
import os
import json
import copy
import threading
from .logger import get_logger

log = get_logger(__name__)

CONFIG_DIR = os.path.expanduser("~/.config/baseus_presenter")
CONFIG_FILE = os.path.join(CONFIG_DIR, "baseus_pointer.json")

# Versão do schema. Usada por _migrate_to_profiles em vez de adivinhar o
# formato pela presença da chave "profiles" (heurística que quebraria na v3).
CONFIG_VERSION = 2

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "close_behavior": "quit",
    "save_dir": os.path.expanduser("~"),
    "models": [],               # Catálogo Global de Modelos
    "active_profile": "Padrão", # Perfil ativo no momento
    "show_subtitles": True,     # Para retrocompatibilidade provisória
    "hardware": {               # IDs do passador (antes hardcoded no código)
        "vendor_id": "abc8",
        "product_id": "ca08"
    },
    "profiles": {
        "Padrão": {
            "visual": {
                "laser_size": 30,
                "laser_color": "#FF0000",
                "pincel_color": "#FF0000",
                "lupa_size": 250,
                "spotlight_size": 300,
                "spotlight_opacity": 160
            },
            "audio": {
                "selected_model_path": "",
                "source_lang": "pt",  # #24: idioma do modelo Vosk selecionado
                "target_lang": "en",
                # Índice do PortAudio: mantido apenas por compatibilidade.
                # Índices NÃO são estáveis entre execuções.
                "input_device": None,
                # Nome do dispositivo: esta é a fonte de verdade para
                # reabrir o microfone certo (ver AudioThread._get_device_id).
                "input_device_name": None,
                "show_subtitles": True
            }
        }
    }
}

def _migrate_to_profiles(loaded):
    """
    Transforma o JSON antigo (onde tudo ficava misturado na raiz) 
    no JSON novo da v2.0 com suporte a Perfis, sem perder os dados do usuário.
    """
    if loaded.get("config_version", 0) >= 2 or "profiles" in loaded:
        # Já está no formato novo (v2+), passa direto. A checagem por
        # "profiles" mantém compatibilidade com arquivos v2 gravados
        # antes de config_version existir.
        loaded.setdefault("config_version", CONFIG_VERSION)
        return loaded

    log.info("Configuração antiga detectada! Migrando para o formato de Perfis (v2.0)...")
    
    old_visual = loaded.get("visual", {})
    old_audio = loaded.get("audio", {})
    
    migrated = {
        "config_version": CONFIG_VERSION,
        "close_behavior": loaded.get("close_behavior", "quit"),
        "save_dir": loaded.get("save_dir", os.path.expanduser("~")),
        "models": old_audio.get("models", []),  # Modelos agora são globais!
        "active_profile": "Padrão",
        "profiles": {
            "Padrão": {
                "visual": old_visual,
                "audio": {
                    "selected_model_path": old_audio.get("selected_model_path", ""),
                    "source_lang": old_audio.get("source_lang", "pt"),
                    "target_lang": old_audio.get("target_lang", "en"),
                    "input_device": old_audio.get("input_device", None),
                    "input_device_name": old_audio.get("input_device_name", None),
                    "show_subtitles": loaded.get("show_subtitles", True)
                }
            }
        }
    }
    return migrated

def _deep_merge(base, update):
    """
    Mescla as configurações garantindo que chaves novas do DEFAULT apareçam.

    Valida o TIPO de cada valor contra o default: se o usuário (ou uma versão
    futura) gravou "laser_size": "grande" ou "profiles": null, o valor ruim é
    descartado e o default daquela chave é mantido. Sem isso o valor inválido
    passava batido e o crash acontecia bem depois, num setValue() ou paintEvent,
    longe da causa real.
    """
    if not isinstance(update, dict):
        return base

    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif key in base and base[key] is not None and value is not None:
            # bool é subclasse de int em Python; trate-os como incompatíveis.
            expected = type(base[key])
            same_kind = isinstance(value, expected) and \
                isinstance(value, bool) == isinstance(base[key], bool)
            if same_kind:
                base[key] = value
            else:
                log.warning(
                    f"Config: valor inválido em '{key}' "
                    f"(esperado {expected.__name__}, recebido {type(value).__name__}). "
                    f"Mantendo padrão: {base[key]!r}"
                )
        else:
            base[key] = value
    return base


def _validate_profiles(config):
    """Garante que 'profiles' seja utilizável e que o perfil ativo exista."""
    default_profile = copy.deepcopy(DEFAULT_CONFIG["profiles"]["Padrão"])

    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        log.warning("Config: 'profiles' ausente ou inválido. Recriando o perfil Padrão.")
        config["profiles"] = {"Padrão": default_profile}
        config["active_profile"] = "Padrão"
        return config

    # Descarta perfis malformados em vez de deixar estourar mais tarde.
    for name in list(profiles.keys()):
        if not isinstance(profiles[name], dict):
            log.warning(f"Config: perfil '{name}' malformado. Descartando.")
            del profiles[name]
        else:
            profiles[name] = _deep_merge(copy.deepcopy(default_profile), profiles[name])

    if not profiles:
        profiles["Padrão"] = default_profile

    active = config.get("active_profile")
    if not isinstance(active, str) or active not in profiles:
        fallback = next(iter(profiles))
        log.warning(f"Config: perfil ativo inválido ({active!r}). Usando '{fallback}'.")
        config["active_profile"] = fallback

    return config


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = json.load(f)

        if not isinstance(user_config, dict):
            raise ValueError(f"raiz do JSON deveria ser um objeto, veio {type(user_config).__name__}")

        # 1. Aplica o escudo de migração (salvando os dados do usuário)
        migrated_config = _migrate_to_profiles(user_config)

        # 2. Garante que qualquer chave nova do sistema seja adicionada.
        #    'profiles' fica FORA do merge: é um dict com chaves definidas pelo
        #    usuário, então mesclar o default reinjetaria o perfil "Padrão"
        #    toda vez que o app subisse (ressuscitando um perfil excluído).
        skeleton = copy.deepcopy(DEFAULT_CONFIG)
        skeleton.pop("profiles", None)
        user_profiles = migrated_config.pop("profiles", None)

        # Remove o "espelho" legado na raiz, gravado por versões antigas da
        # GUI. Os dados de verdade vivem em profiles[ativo]; manter as cópias
        # obsoletas só induziria a erro em depurações futuras.
        if user_profiles:
            migrated_config.pop("visual", None)
            migrated_config.pop("audio", None)
        final_config = _deep_merge(skeleton, migrated_config)
        final_config["profiles"] = user_profiles

        # 3. Valida os perfis antes de entregar para a GUI/threads
        return _validate_profiles(final_config)
    except Exception as e:
        # Preserva o arquivo problemático em vez de sobrescrevê-lo no próximo
        # save: descartar em silêncio significava perda total das configurações.
        log.exception(f"Erro ao carregar configurações: {e}. Usando padrões.")
        try:
            backup = CONFIG_FILE + ".corrupt"
            os.replace(CONFIG_FILE, backup)
            log.error(f"Arquivo problemático preservado em: {backup}")
        except OSError as exc:
            log.error(f"Não foi possível preservar o arquivo problemático: {exc}")
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config):
    """
    Grava a config de forma ATÔMICA (tmp + os.replace).

    Escrever direto no arquivo final significava que um crash ou disco cheio no
    meio do json.dump deixava um JSON truncado, que o load_config descartava —
    perdendo toda a configuração do usuário.
    """
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp_path = CONFIG_FILE + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)  # atômico no POSIX
        log.debug("Configurações salvas com sucesso.")
    except Exception as e:
        log.exception(f"Erro ao salvar configurações: {e}")
        try:
            if os.path.exists(CONFIG_FILE + ".tmp"):
                os.unlink(CONFIG_FILE + ".tmp")
        except OSError:
            pass


# =============================================================================
# ACESSADORES DE PERFIL
#
# Antes, a GUI copiava profiles[ativo]["audio"] para config["audio"] na raiz
# (o "truque do espelho"). Isso criava DUAS fontes de verdade e fazia
# config["audio"] só existir depois da GUI rodar — o que estourava KeyError
# na AudioThread. Agora todo consumidor lê o perfil ativo por aqui.
# =============================================================================

def active_profile(config):
    """Retorna o dict do perfil ativo, criando-o se necessário."""
    name = config.get("active_profile", "Padrão")
    profiles = config.setdefault("profiles", {})
    if name not in profiles:
        profiles[name] = copy.deepcopy(DEFAULT_CONFIG["profiles"]["Padrão"])
    return profiles[name]


def audio_cfg(config):
    """Configurações de áudio do perfil ativo."""
    return active_profile(config).setdefault("audio", {})


def visual_cfg(config):
    """Configurações visuais do perfil ativo."""
    return active_profile(config).setdefault("visual", {})


class Config:
    """
    Wrapper com lock em volta do dict de configuração.

    O mesmo dict era passado por referência para HardwareReader, AudioThread,
    PointerWindow e MainWindow — 3 threads distintas — sem nenhuma proteção.
    A GUI chega a SUBSTITUIR profiles[ativo]["audio"] por um dict novo enquanto
    a AudioThread está lendo. O GIL evita corrupção de memória, mas não leitura
    inconsistente. Só a GUI escreve; as threads leem por getters/snapshot.
    """

    def __init__(self, data=None):
        self._data = data if data is not None else load_config()
        self._lock = threading.RLock()

    # --- Leitura ---
    def get(self, key, default=None):
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))

    def get_audio(self, key, default=None):
        with self._lock:
            return copy.deepcopy(audio_cfg(self._data).get(key, default))

    def get_visual(self, key, default=None):
        with self._lock:
            return copy.deepcopy(visual_cfg(self._data).get(key, default))

    def snapshot(self):
        """Cópia profunda e consistente de toda a configuração."""
        with self._lock:
            return copy.deepcopy(self._data)

    # --- Escrita (usada apenas pela GUI, na thread principal) ---
    def set(self, key, value):
        with self._lock:
            self._data[key] = value

    def set_audio(self, key, value):
        with self._lock:
            audio_cfg(self._data)[key] = value

    def set_visual(self, key, value):
        with self._lock:
            visual_cfg(self._data)[key] = value

    def mutate(self):
        """
        Context manager para operações compostas (criar/excluir perfil).

        with cfg.mutate() as data:
            data["profiles"][nome] = ...
        """
        return _ConfigMutation(self._data, self._lock)

    def save(self):
        with self._lock:
            save_config(self._data)


class _ConfigMutation:
    def __init__(self, data, lock):
        self._data, self._lock = data, lock

    def __enter__(self):
        self._lock.acquire()
        return self._data

    def __exit__(self, *exc):
        self._lock.release()
        return False