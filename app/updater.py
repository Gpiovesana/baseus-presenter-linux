import json
import os
import re
import subprocess
import urllib.error
import urllib.request

from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal

from .logger import get_logger

log = get_logger(__name__)

REPO = "Gpiovesana/baseus-presenter-linux"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 horas


def read_local_version():
    """Lê a versão instalada a partir do arquivo version."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    version_file = os.path.join(base_dir, "version")

    try:
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError as exc:
        log.warning(f"Não foi possível ler a versão instalada: {exc}")
        return "0.0.0"


def normalize_version(version):
    """Transforma v2.1.0 / 2.1.0 em uma tupla comparável."""
    version = version.strip().lstrip("v")

    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if not match:
        return (0, 0, 0)

    return tuple(int(x or 0) for x in match.groups())


def is_newer(current, latest):
    return normalize_version(latest) > normalize_version(current)


def get_latest_release():
    """
    Consulta a última Release estável do GitHub.

    Retorna:
        (tag, url) ou None
    """
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Baseus-Presenter-Updater"
        },
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("draft") or data.get("prerelease"):
        return None

    tag = data.get("tag_name")
    html_url = data.get("html_url")

    if not tag:
        return None

    return tag, html_url


class UpdateCheckThread(QThread):
    update_available = pyqtSignal(str, str)
    no_update = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            result = get_latest_release()

            if result is None:
                self.no_update.emit()
                return

            latest_tag, release_url = result

            if is_newer(self.current_version, latest_tag):
                log.info(
                    f"Nova versão encontrada: "
                    f"{latest_tag} (atual: {self.current_version})"
                )
                self.update_available.emit(latest_tag, release_url)
            else:
                log.debug(
                    f"Baseus Presenter já está atualizado "
                    f"({self.current_version})."
                )
                self.no_update.emit()

        except urllib.error.URLError as exc:
            log.warning(f"Falha ao verificar atualizações: {exc}")
            self.failed.emit(str(exc))

        except Exception as exc:
            log.exception(f"Erro ao verificar atualizações: {exc}")
            self.failed.emit(str(exc))


class UpdateChecker(QObject):
    """
    Verifica atualizações ao iniciar e depois periodicamente.
    """

    update_available = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._thread = None

        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)

    def start(self):
        # Checagem inicial alguns segundos depois da abertura,
        # para não disputar recursos com a inicialização do hardware.
        QTimer.singleShot(10000, self.check)

        self.timer.start()

    def check(self):
        # Não inicia outra thread enquanto uma consulta anterior
        # ainda estiver rodando.
        if self._thread and self._thread.isRunning():
            return

        current_version = read_local_version()

        log.debug(
            f"Verificando atualizações (versão instalada: {current_version})..."
        )

        self._thread = UpdateCheckThread(current_version, self)

        self._thread.update_available.connect(
            self.update_available.emit
        )

        self._thread.failed.connect(
            lambda msg: log.debug(
                f"Atualização indisponível no momento: {msg}"
            )
        )

        self._thread.finished.connect(
            self._thread.deleteLater
        )

        self._thread.start()
