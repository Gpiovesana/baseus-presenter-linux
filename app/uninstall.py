"""Desinstalador independente da GUI e da venv, com confirmação obrigatória."""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

UDEV_RULE = Path("/etc/udev/rules.d/99-baseus-presenter.rules")

WRAPPER = '''#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/python3 "$SCRIPT_DIR/app/uninstall.py" "$SCRIPT_DIR"
'''


def validate_installation(directory):
    requested = Path(directory)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("O destino deve ser uma pasta absoluta, sem link simbólico.")
    target = requested.resolve(strict=True)
    home = Path.home().resolve()
    if target == home or target in home.parents or target == Path("/"):
        raise ValueError("Diretório de desinstalação inseguro.")
    if any((parent / ".git/HEAD").is_file() or (parent / ".git").is_file()
           or (parent / ".git").is_symlink()
           for parent in (target, *target.parents)):
        raise ValueError("Desinstalação bloqueada em checkout de desenvolvimento.")
    if target.stat().st_uid != os.getuid():
        raise ValueError("A instalação pertence a outro usuário.")
    for name in ("baseus_app.py", "version", "app/uninstall.py"):
        item = target / name
        if not item.is_file() or item.is_symlink() or not item.resolve().is_relative_to(target):
            raise ValueError("Esta pasta não parece uma instalação válida do Baseus Presenter.")
    return target


def desktop_path():
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications/baseus-presenter-uninstall.desktop"


def desktop_quote(value):
    # Exec tem dois níveis de escape (Desktop Entry e argumentos Exec).
    value = str(value).replace("%", "%%")
    for char in ("\\", '"', "`", "$"):
        value = value.replace(char, "\\" + char)
    return '"' + value.replace("\\", "\\\\") + '"'


def register_desktop(directory):
    target = validate_installation(directory)
    if "\n" in str(target) or "\r" in str(target):
        raise ValueError("Caminho de instalação inválido.")
    # O updater antigo copia app/, mas não uninstall.sh. Permite a migração.
    wrapper = target / "uninstall.sh"
    if wrapper.is_symlink():
        raise ValueError("O desinstalador não pode ser um link simbólico.")
    if not wrapper.exists():
        wrapper.write_text(WRAPPER, encoding="utf-8")
    launcher = desktop_path()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        "[Desktop Entry]\nType=Application\n"
        "Name=Desinstalar Baseus Presenter\n"
        "Comment=Remover o aplicativo (pede confirmação antes de continuar)\n"
        f"Exec=/bin/bash {desktop_quote(wrapper)}\n"
        "Icon=edit-delete\nTerminal=true\nCategories=Utility;\nStartupNotify=false\n",
        encoding="utf-8",
    )
    return launcher


def app_lock_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and Path(runtime).is_dir():
        return Path(runtime) / "baseus_presenter.lock"
    return Path(f"/tmp/baseus_presenter-{os.getuid()}.lock")


def open_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise ValueError("Arquivo de trava pertence a outro usuário.")
    return os.fdopen(fd, "r+")


def stop_application(target, lock):
    try:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    except BlockingIOError:
        pass
    lock.seek(0)
    pid = int(lock.read().strip())
    if pid <= 1 or pid == os.getpid():
        raise ValueError("PID inválido. Feche o aplicativo e tente novamente.")
    proc = Path(f"/proc/{pid}")
    args = (proc / "cmdline").read_bytes().split(b"\0")
    cwd = (proc / "cwd").resolve(strict=True)
    expected = target / "baseus_app.py"
    if proc.stat().st_uid != os.getuid() or not any(
        (cwd / os.fsdecode(arg)).resolve() == expected for arg in args[1:] if arg
    ):
        raise ValueError("Outra instância está ativa. Feche o Baseus Presenter e tente novamente.")
    print("Encerrando Baseus Presenter e liberando os dispositivos…", flush=True)
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(0.1)
    raise RuntimeError("O aplicativo ainda está encerrando. Tente novamente quando ele fechar.")


class UninstallProgress:
    """Janela independente da instalação; mantém feedback no terminal sem GUI."""

    def __init__(self):
        self.process = None
        zenity = shutil.which("zenity")
        if zenity:
            try:
                self.process = subprocess.Popen(
                    [zenity, "--progress", "--pulsate", "--auto-close", "--no-cancel",
                     "--title=Desinstalando Baseus Presenter", "--text=Preparando desinstalação…",
                     "--width=460"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, text=True, cwd="/tmp",
                )
            except OSError:
                pass

    def update(self, message):
        print(message, flush=True)
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write("# " + message + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def close(self):
        if self.process is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()


def remove_installation(directory, progress=None):
    report = progress or (lambda message: print(message, flush=True))
    report("Verificando a instalação…")
    if os.geteuid() == 0:
        raise ValueError("Execute como seu usuário normal; a senha será pedida apenas para a regra USB.")
    target = validate_installation(directory)
    update_lock = Path(os.environ.get("BASEUS_UPDATE_LOCK_FILE", str(target) + ".update-lock"))
    with open_lock(update_lock) as update, open_lock(app_lock_path()) as app:
        try:
            fcntl.flock(update, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Há uma instalação ou atualização em andamento. Tente novamente depois.")
        report("Encerrando o aplicativo e liberando os dispositivos…")
        stop_application(target, app)
        rule = UDEV_RULE
        if rule.exists():
            report("Removendo permissões USB… Se solicitado, digite sua senha no terminal.")
            print("A remoção da regra USB requer sua senha administrativa.", flush=True)
            subprocess.run(["sudo", "rm", "--", str(rule)], check=True)
            subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=True)
            subprocess.run(["sudo", "udevadm", "trigger"], check=True)
        data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        validate_installation(target)
        os.chdir(target.parent)
        report("Removendo os arquivos do aplicativo…")
        shutil.rmtree(target)
        report("Removendo atalhos e inicialização automática…")
        for launcher in (data / "applications/baseus-presenter.desktop",
                         desktop_path(), config / "autostart/baseus-presenter.desktop"):
            launcher.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register-desktop", action="store_true")
    parser.add_argument("directory")
    args = parser.parse_args(argv)
    if args.register_desktop:
        register_desktop(args.directory)
        return 0
    print("AVISO — DESINSTALAR BASEUS PRESENTER\n")
    print(f"Será removida a pasta inteira: {args.directory}")
    print("Inclui aplicativo, ambiente virtual, atalhos e regra USB.")
    print("Configurações, modelos e transcrições FORA dessa pasta serão preservados.")
    print("Arquivos pessoais guardados DENTRO dela também serão apagados.\n")
    try:
        validate_installation(args.directory)
        answer = input("Digite desinstalar para confirmar (maiúsculas ou minúsculas; Enter cancela): ")
        if answer.strip().lower() != "desinstalar":
            print("Cancelado. Nenhum arquivo foi removido.")
            return 0
        progress = UninstallProgress()
        try:
            remove_installation(args.directory, progress=progress.update)
        finally:
            progress.close()
        print("\nDesinstalação concluída. Os arquivos removidos não foram enviados à lixeira.")
        print("Dados externos preservados, incluindo ~/.config/baseus_presenter e ~/.config/baseus_pointer.")
        result = 0
    except (EOFError, KeyboardInterrupt):
        print("\nOperação interrompida.")
        return 1
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\nNão foi possível concluir a desinstalação: {error}")
        print("Se a remoção já começou, alguns itens podem ter sido removidos.")
        result = 1
    if sys.stdin.isatty():
        try:
            input("Pressione Enter para fechar…")
        except (EOFError, KeyboardInterrupt):
            pass
    return result


if __name__ == "__main__":
    sys.exit(main())
