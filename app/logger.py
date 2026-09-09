# ~/BaseusPresenter/app/logger.py
import logging
import logging.handlers
import os
import threading

# Define a pasta e o arquivo de log (na mesma pasta de config)
LOG_DIR = os.path.expanduser("~/.config/baseus_pointer")
LOG_PATH = os.path.join(LOG_DIR, "baseus.log")

# #29: ANTES, cada chamada de get_logger(name) criava o SEU PRÓPRIO
# RotatingFileHandler apontando para o mesmo arquivo. Com N loggers havia N
# handlers, cada um com seu próprio descritor e sua própria contagem de
# bytes. Quando um deles rotacionava (renomeando baseus.log -> baseus.log.1),
# os outros continuavam escrevendo no INODE ANTIGO — que depois era removido
# pela rotação seguinte, levando embora mensagens recentes.
#
# A correção é ter UM ÚNICO handler de arquivo, criado uma vez e anexado ao
# logger RAIZ do pacote. Os loggers filhos (app.audio, app.gui, ...) propagam
# para ele por herança, sem handler próprio.
_ROOT_LOGGER_NAME = "app"
_setup_lock = threading.Lock()
_configured = False


def _configure_root_logger():
    """Cria (uma única vez) os handlers compartilhados no logger raiz."""
    global _configured
    if _configured:
        return

    with _setup_lock:
        if _configured:  # outra thread pode ter configurado enquanto esperávamos
            return

        root = logging.getLogger(_ROOT_LOGGER_NAME)
        root.setLevel(logging.DEBUG)

        # Evita duplicar handlers se esta função for chamada de novo.
        if not root.handlers:
            # Exemplo: 14:30:05 [INFO] app.hardware: Dongle Baseus conectado
            fmt = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")

            # --- Handler 1: Arquivo (Rotating) — ÚNICO no processo ---
            # maxBytes=2_000_000 (2MB), backupCount=3 (até 3 arquivos antigos)
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                file_handler = logging.handlers.RotatingFileHandler(
                    LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
                )
                file_handler.setLevel(logging.DEBUG)  # Grava tudo no arquivo
                file_handler.setFormatter(fmt)
                root.addHandler(file_handler)
            except OSError as exc:
                # Sem permissão / disco cheio: o app deve continuar rodando
                # com log apenas no console em vez de falhar no import.
                print(f"[logger] Aviso: log em arquivo desativado ({exc})")

            # --- Handler 2: Console (Terminal) ---
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)  # No terminal, só o importante
            console_handler.setFormatter(fmt)
            root.addHandler(console_handler)

            # Não deixa as mensagens subirem para o root logger global do
            # Python (evita saída duplicada se algo mais configurar logging).
            root.propagate = False

        _configured = True


def get_logger(name):
    """
    Retorna um logger que grava em arquivo e no terminal.

    Todos os loggers compartilham os handlers do logger raiz do pacote, de
    modo que existe apenas UM RotatingFileHandler no processo — condição
    necessária para a rotação não perder mensagens (#29).
    """
    _configure_root_logger()

    # Normaliza para que todo logger seja filho de "app" e herde os handlers.
    # __name__ dos módulos do pacote já vem como "app.audio", "app.gui", etc.
    if name == _ROOT_LOGGER_NAME or name.startswith(_ROOT_LOGGER_NAME + "."):
        logger_name = name
    else:
        # Ex.: get_logger("Main") em baseus_app.py -> "app.Main"
        logger_name = f"{_ROOT_LOGGER_NAME}.{name}"

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    # Sem handlers próprios: propaga para o raiz, que tem o handler único.
    logger.propagate = True
    return logger
