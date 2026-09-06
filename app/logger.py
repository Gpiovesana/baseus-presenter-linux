# ~/BaseusPresenter/app/logger.py
import logging
import logging.handlers
import os

# Define a pasta e o arquivo de log (na mesma pasta de config)
LOG_DIR = os.path.expanduser("~/.config/baseus_pointer")
LOG_PATH = os.path.join(LOG_DIR, "baseus.log")

def get_logger(name):
    """
    Retorna um logger configurado que grava em arquivo e no terminal.
    Usa RotatingFileHandler para não deixar o arquivo crescer infinitamente.
    """
    logger = logging.getLogger(name)
    
    # Se o logger já tiver handlers configurados, não adiciona de novo
    if logger.handlers:
        return logger
        
    # Nível mínimo de captura (DEBUG captura tudo)
    logger.setLevel(logging.DEBUG)
    
    # Cria a pasta de logs se ela não existir
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # --- Handler 1: Arquivo (Rotating) ---
    # maxBytes=2_000_000 (2MB), backupCount=3 (guarda até 3 arquivos antigos)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG) # Grava tudo no arquivo
    
    # --- Handler 2: Console (Terminal) ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO) # No terminal, mostra só o importante
    
    # --- Formatação ---
    # Exemplo: 14:30:05 [INFO] hardware: Dongle Baseus conectado
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
    file_handler.setFormatter(fmt)
    console_handler.setFormatter(fmt)
    
    # Adiciona os handlers ao logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
