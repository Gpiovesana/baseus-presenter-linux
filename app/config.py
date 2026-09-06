# ~/Documentos/Projetos/baseus-presenter-linux/app/config.py
import os
import json
import copy
from .logger import get_logger

# Iniciando o nosso logger para este arquivo!
log = get_logger(__name__)

# Caminhos padrão
CONFIG_PATH = os.path.expanduser("~/.config/baseus_pointer.json")
MODELS_DIR = os.path.expanduser("~/.config/baseus_pointer/models")

# Configuração Padrão de Fábrica
DEFAULT_CONFIG = {
    "close_behavior": "tray",
    "save_dir": os.path.expanduser("~"),
    "visual": {
        "laser_size": 30, "lupa_size": 250, "spotlight_size": 300,
        "spotlight_opacity": 160, "lupa_shape": "circular",
        "laser_color": "#FF0000", "pincel_color": "#FF0000",
    },
    "audio": {
        "target_lang": "en",
        "selected_model_path": "",
        "models": [] # Lista dinâmica: [{"label": "Nome", "path": "caminho", "lang": "pt"}]
    },
}

def _deep_merge(defaults, loaded):
    """Mescla as configurações do usuário com os padrões para evitar crash se faltar alguma chave."""
    result = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else: 
            result[key] = value
    return result

def load_config():
    """Carrega as configurações do JSON do usuário ou retorna o padrão."""
    try:
        with open(CONFIG_PATH, "r") as f: 
            loaded = json.load(f)
        log.info("Configurações do usuário carregadas com sucesso.")
        return _deep_merge(DEFAULT_CONFIG, loaded)
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"Nenhum arquivo de config válido encontrado ({e}). Usando configurações padrão.")
        return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config):
    """Salva as configurações de forma atômica para evitar arquivos corrompidos."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f: 
            json.dump(config, f, indent=2)
        os.replace(tmp_path, CONFIG_PATH)
        log.debug("Configurações salvas no disco (modo atômico).")
    except OSError as e: 
        log.error(f"Falha crítica ao salvar o arquivo de configuração: {e}")
