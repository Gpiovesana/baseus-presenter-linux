# ~/Documentos/Projetos/baseus-presenter-linux/app/config.py
import os
import json
from .logger import get_logger

log = get_logger(__name__)

CONFIG_DIR = os.path.expanduser("~/.config/baseus_presenter")
CONFIG_FILE = os.path.join(CONFIG_DIR, "baseus_pointer.json")

DEFAULT_CONFIG = {
    "close_behavior": "quit",
    "save_dir": os.path.expanduser("~"),
    "models": [],               # Catálogo Global de Modelos
    "active_profile": "Padrão", # Perfil ativo no momento
    "show_subtitles": True,     # Para retrocompatibilidade provisória
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
                "target_lang": "en",
                "input_device": None,
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
    if "profiles" in loaded:
        return loaded  # Já está no formato novo da v2.0, passa direto!

    log.info("Configuração antiga detectada! Migrando para o formato de Perfis (v2.0)...")
    
    old_visual = loaded.get("visual", {})
    old_audio = loaded.get("audio", {})
    
    migrated = {
        "close_behavior": loaded.get("close_behavior", "quit"),
        "save_dir": loaded.get("save_dir", os.path.expanduser("~")),
        "models": old_audio.get("models", []),  # Modelos agora são globais!
        "active_profile": "Padrão",
        "profiles": {
            "Padrão": {
                "visual": old_visual,
                "audio": {
                    "selected_model_path": old_audio.get("selected_model_path", ""),
                    "target_lang": old_audio.get("target_lang", "en"),
                    "input_device": old_audio.get("input_device", None),
                    "show_subtitles": loaded.get("show_subtitles", True)
                }
            }
        }
    }
    return migrated

def _deep_merge(base, update):
    """Mescla as configurações garantindo que chaves novas do DEFAULT apareçam."""
    for key, value in update.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
        
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            
            # 1. Aplica o escudo de migração (salvando os dados do usuário)
            migrated_config = _migrate_to_profiles(user_config)
            
            # 2. Garante que qualquer chave nova do sistema seja adicionada
            final_config = _deep_merge(DEFAULT_CONFIG.copy(), migrated_config)
            return final_config
    except Exception as e:
        log.error(f"Erro ao carregar configurações: {e}. Usando padrões.")
        return DEFAULT_CONFIG.copy()

def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        log.info("Configurações salvas com sucesso.")
    except Exception as e:
        log.error(f"Erro ao salvar configurações: {e}")