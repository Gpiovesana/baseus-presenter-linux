import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
import urllib.error
import urllib.request

from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .logger import get_logger

log = get_logger(__name__)

REPO = "Gpiovesana/baseus-presenter-linux"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 horas


def read_local_version():
    """Lê a versão instalada a partir do arquivo version."""
    # Assume que este arquivo está em app/updater.py (2 níveis abaixo da raiz
    # da instalação, ~/BaseusPresenter/). Se a estrutura de pacotes mudar
    # (ex: app/core/updater.py), esse cálculo precisa ser revisado.
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
    version = version.strip().removeprefix("v")
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if not match:
        return (0, 0, 0)
    return tuple(int(x or 0) for x in match.groups())


def is_newer(current, latest):
    return normalize_version(latest) > normalize_version(current)


def get_latest_release():
    """Consulta a última Release estável do GitHub."""
    request = urllib.request.Request(
        API_URL,
        headers={"User-Agent": "Baseus-Presenter-Updater"},
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
    update_available = pyqtSignal(str, str, bool)
    no_update = pyqtSignal(bool)
    failed = pyqtSignal(str, bool)

    def __init__(self, current_version, is_manual, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.is_manual = is_manual

    def run(self):
        try:
            result = get_latest_release()

            if result is None:
                self.no_update.emit(self.is_manual)
                return

            latest_tag, release_url = result

            if is_newer(self.current_version, latest_tag):
                log.info(f"Nova versão encontrada: {latest_tag} (atual: {self.current_version})")
                self.update_available.emit(latest_tag, release_url, self.is_manual)
            else:
                log.debug(f"Baseus Presenter já está atualizado ({self.current_version}).")
                self.no_update.emit(self.is_manual)

        except urllib.error.URLError as exc:
            log.warning(f"Falha ao verificar atualizações: {exc}")
            self.failed.emit(str(exc), self.is_manual)
        except Exception as exc:
            log.exception(f"Erro ao verificar atualizações: {exc}")
            self.failed.emit(str(exc), self.is_manual)


class UpdateChecker(QObject):
    """Verifica atualizações ao iniciar e depois periodicamente."""
    update_available = pyqtSignal(str, str, bool)
    no_update = pyqtSignal(bool)
    failed = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._stopped = False
        self.ignored_version = None

        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(lambda: self.check(is_manual=False))

    @property
    def is_checking(self):
        """Retorna True se uma consulta estiver em andamento."""
        return self._thread is not None and self._thread.isRunning()

    def start(self):
        # Checagem inicial alguns segundos depois da abertura
        QTimer.singleShot(10000, lambda: self.check(is_manual=False))
        self.timer.start()

    def check(self, is_manual=False):
        if self._stopped or self.is_checking:
            return

        current_version = read_local_version()
        log.debug(f"Verificando atualizações (manual={is_manual}, versão atual: {current_version})...")

        self._thread = UpdateCheckThread(current_version, is_manual, self)

        self._thread.update_available.connect(self.update_available.emit)
        self._thread.no_update.connect(self.no_update.emit)
        self._thread.failed.connect(self.failed.emit)

        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def stop(self):
        self._stopped = True
        self.timer.stop()
        if self._thread is not None:
            # urlopen usa timeout de 10 s; o limite evita travar indefinidamente
            # o encerramento caso uma implementação de rede ignore esse prazo.
            if not self._thread.wait(12000):
                log.warning("A consulta de atualização não encerrou dentro do prazo.")
                self._thread.terminate()
                self._thread.wait()

    def _on_thread_finished(self):
        thread = self.sender()
        if thread is self._thread:
            self._thread = None
        thread.deleteLater()


def start_update_process(version_tag, autostart=None):
    """Prepara a atualização e só encerra o app quando o staging estiver pronto."""
    base_dir = os.path.realpath(os.path.dirname(os.path.dirname(__file__)))
    # .git também pode ser um arquivo (git worktree). Verifica ancestrais
    # para proteger projetos instalados em uma subpasta de um checkout.
    root = Path(base_dir)
    if any((path / ".git").is_file() or (path / ".git/HEAD").is_file()
           or (path / ".git").is_symlink() for path in (root, *root.parents)):
        QMessageBox.warning(
            None, "Atualização indisponível",
            "Esta cópia está em um checkout de desenvolvimento. "
            "Atualize pelo Git ou use uma instalação separada do aplicativo.",
        )
        return False
    updater_script = os.path.join(base_dir, "updater.sh")

    if not os.path.exists(updater_script):
        log.error("Script de atualização (updater.sh) não encontrado na raiz!")
        return

    tag = version_tag.strip()
    version = tag.removeprefix("v")
    if not re.fullmatch(r"v?\d+(?:\.\d+){0,2}", tag):
        log.error(f"Versão de atualização inválida: {version_tag!r}")
        QMessageBox.warning(None, "Erro de Atualização", "A versão informada pela atualização é inválida.")
        return False

    app = QApplication.instance()
    if app is None:
        log.error("Não há uma instância QApplication ativa para coordenar a atualização.")
        return False

    current_process = getattr(app, "_baseus_update_process", None)
    if current_process is not None and current_process.poll() is None:
        log.warning("Uma atualização já está sendo preparada.")
        return False

    status_fd, status_file = tempfile.mkstemp(prefix="baseus-update-status-")
    os.close(status_fd)
    log_fd, log_file = tempfile.mkstemp(prefix="baseus-update-log-")
    log_stream = os.fdopen(log_fd, "w", encoding="utf-8")

    log.info(f"Preparando atualização (Alvo: {version})...")

    # Se o Popen falhar (bash ausente, permissão negada, etc.), não podemos
    # simplesmente fechar o app — isso deixaria o usuário sem o programa e
    # sem atualização. Só chamamos app.quit() se o processo realmente subiu.
    try:
        process = subprocess.Popen(
            ["bash", updater_script, tag, str(os.getpid()), status_file,
             "keep" if autostart is None else "enable" if autostart else "disable"],
            cwd=base_dir,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        log_stream.close()
        for path in (status_file, log_file):
            try:
                os.unlink(path)
            except OSError:
                pass
        log.error(f"Falha ao iniciar updater.sh: {exc}")
        QMessageBox.warning(None, "Erro de Atualização", f"Não foi possível iniciar o atualizador:\n\n{exc}")
        return False
    finally:
        log_stream.close()

    # Os objetos ficam presos ao QApplication para não serem coletados enquanto
    # o preparo assíncrono está em andamento.
    timer = QTimer(app)
    timer.setInterval(200)
    app._baseus_update_process = process
    app._baseus_update_timer = timer
    app._baseus_update_status_file = status_file
    app._baseus_update_log_file = log_file
    progress = QProgressDialog("Preparando atualização… Aguarde.", None, 0, 0)
    progress.setWindowTitle("Atualizando Baseus Presenter")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setWindowFlags(progress.windowFlags() & ~Qt.WindowCloseButtonHint)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()
    app._baseus_update_progress = progress

    def poll_update_preparation():
        try:
            with open(log_file, "rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 4096))
                lines = stream.read().decode("utf-8", errors="replace").splitlines()
            stages = [line for line in lines if line.startswith(("🔄", "📥", "📦", "🐍", "⏳"))]
            if stages:
                progress.setLabelText(stages[-1] + "\n\nAguarde. O aplicativo será reiniciado ao concluir.")
        except OSError:
            pass
        try:
            with open(status_file, "r", encoding="utf-8") as stream:
                status = stream.read().strip()
        except OSError:
            status = ""

        return_code = process.poll()
        if status == "READY" and (return_code is None or return_code == 0):
            timer.stop()
            progress.close()
            progress.deleteLater()
            app._baseus_update_progress = None
            log.info("Atualização preparada; encerrando o aplicativo para concluir a troca.")
            app.quit()
            return

        if return_code is None:
            return

        timer.stop()
        progress.close()
        progress.deleteLater()
        app._baseus_update_progress = None
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as stream:
                details = stream.read().strip()
        except OSError:
            details = ""
        details = details[-2000:] if details else f"O atualizador terminou com código {return_code}."
        log.error(f"Falha ao preparar atualização: {details}")
        QMessageBox.warning(
            None,
            "Erro de Atualização",
            "Não foi possível preparar a atualização. O aplicativo continuará aberto.\n\n" + details,
        )
        for path in (status_file, log_file):
            try:
                os.unlink(path)
            except OSError:
                pass
        app._baseus_update_process = None

    timer.timeout.connect(poll_update_preparation)
    timer.start()
    return True
