# ~/Documentos/Projetos/baseus-presenter-linux/baseus_app.py
import sys
import os
import fcntl
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QTimer

from app.logger import get_logger
from app.config import Config
from app.hardware import HardwareReader
from app.audio import AudioThread
from app.overlay import PointerWindow
from app.gui import MainWindow, TrayIcon
from app.updater import UpdateChecker, start_update_process

log = get_logger("Main")

def _lock_path():
    """
    Caminho do lock por usuário.

    Um arquivo fixo em /tmp pertence ao primeiro usuário que rodar o app; o
    segundo usuário do sistema não consegue abri-lo em modo 'w'. XDG_RUNTIME_DIR
    é por usuário e é o local correto para runtime state.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "baseus_presenter.lock")
    return f"/tmp/baseus_presenter-{os.getuid()}.lock"


def acquire_single_instance_lock():
    """Garante instância única. Retorna (lock_fp, lock_file) ou encerra."""
    lock_file = _lock_path()
    try:
        # Modo 'a+' (não 'w'): abrir com 'w' TRUNCA o arquivo antes de
        # sabermos se conseguimos a trava, apagando o PID do processo que
        # legitimamente já está rodando. O truncamento é feito só depois de
        # adquirir o lock, mais abaixo.
        lock_fp = open(lock_file, 'a+')
    except OSError as exc:
        # /tmp cheio ou sem permissão: antes isso era um traceback cru.
        log.error(f"Não foi possível criar o arquivo de trava em {lock_file}: {exc}")
        sys.exit(1)

    try:
        fcntl.lockf(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Tenta informar QUEM está segurando a trava.
        try:
            lock_fp.seek(0)
            dono = lock_fp.read().strip() or "desconhecido"
        except OSError:
            dono = "desconhecido"
        log.error(
            f"O aplicativo já está rodando (PID {dono})! "
            "Fechando esta nova tentativa."
        )
        lock_fp.close()
        sys.exit(1)

    # Registra o PID para facilitar o diagnóstico de "quem está travando".
    # Só agora, com a trava garantida, é seguro sobrescrever o conteúdo.
    try:
        lock_fp.seek(0)
        lock_fp.truncate()
        lock_fp.write(f"{os.getpid()}\n")
        lock_fp.flush()
    except OSError:
        pass

    return lock_fp, lock_file


def main():
    # 1. Trava de Instância (Evita abrir duas vezes e bugar a porta USB)
    lock_fp, lock_file = acquire_single_instance_lock()

    # 2. Inicialização do Qt e Carregamento de Configurações
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # Mantém rodando mesmo se fechar a janela de config

    config = Config()
    log.info("Iniciando o Baseus Presenter (Versão 2.0 Modular)...")

    # 3. Instanciando os Módulos (Nenhum deles sabe que os outros existem)
    hardware = HardwareReader(config=config)
    audio = AudioThread(config)
    overlay = PointerWindow(config)
    settings_gui = MainWindow(config)
    tray = TrayIcon(settings_gui)
    updater = UpdateChecker()

    # Colocando um ícone provisório só pro aplicativo não ficar invisível na bandeja
    tray.setIcon(QIcon.fromTheme("input-mouse"))
    tray.show()

    # =========================================================================
    # 4. A FIAÇÃO (Onde a mágica acontece)
    # =========================================================================

    # Hardware conversando com o Visor (Overlay)
    hardware.pointer_active.connect(overlay.set_active)
    hardware.toggle_mode.connect(overlay.switch_mode)
    hardware.pen_active.connect(overlay.set_pen_active)
    hardware.pen_clear.connect(overlay.pen_clear)
    hardware.translate_toggled.connect(overlay.set_translating)
    hardware.black_screen_toggle.connect(overlay.toggle_black_screen)

    # Hardware conversando com o Áudio
    # Cada clique alterna o estado validado pelo áudio, inclusive após falhas.
    hardware.record_toggled.connect(lambda _state: audio.set_recording(not audio.is_recording))
    hardware.record_toggled.connect(lambda _state: overlay.set_recording(audio.is_recording))
    hardware.translate_toggled.connect(audio.set_translating)

    # Áudio conversando com o Visor
    audio.partial_ready.connect(overlay.show_subtitle)
    audio.final_ready.connect(overlay.show_subtitle)
    audio.audio_warning.connect(lambda msg: overlay.show_subtitle(msg, 4000))

    # Interface Gráfica conversando com Visor e Áudio
    settings_gui.config_updated.connect(overlay.update_visual_config)
    settings_gui.model_changed.connect(audio.trigger_reload)
    settings_gui.input_device_changed.connect(audio.request_stream_restart)
    hardware.permission_error.connect(settings_gui.show_warning)
    audio.audio_error.connect(settings_gui.show_warning)
    audio.audio_error.connect(lambda _msg: overlay.set_recording(False))
    audio.audio_error.connect(lambda msg: overlay.show_subtitle(msg, 6000))

    # Passa a bateria para a Janela e para a Bandeja do Sistema (Ícone)
    hardware.battery_update.connect(settings_gui.update_battery)
    hardware.battery_update.connect(tray.update_battery)

    # =========================================================================
    # ROTEAMENTO DO UPDATER
    # =========================================================================
    def handle_manual_check():
        if updater.is_checking:
            return
        settings_gui.set_update_checking_state(True)
        updater.check(is_manual=True)

    def handle_update_available(version, url, is_manual):
        settings_gui.set_update_checking_state(False)

        # Ignora avisos automáticos caso o usuário já tenha recusado a mesma versão nesta sessão
        if not is_manual and version == updater.ignored_version:
            log.debug(f"Aviso silencioso ({version}) suprimido: usuário já recusou nesta sessão.")
            return

        if settings_gui.prompt_update(version):
            start_update_process(version)
        else:
            updater.ignored_version = version
            log.info(f"Atualização para {version} adiada pelo usuário.")

    def handle_no_update(is_manual):
        settings_gui.set_update_checking_state(False)
        if is_manual:
            settings_gui.show_up_to_date()

    def handle_update_failed(err, is_manual):
        settings_gui.set_update_checking_state(False)
        if is_manual:
            settings_gui.show_update_error(err)

    settings_gui.manual_update_requested.connect(handle_manual_check)
    updater.update_available.connect(handle_update_available)
    updater.no_update.connect(handle_no_update)
    updater.failed.connect(handle_update_failed)

    # =========================================================================

    # 5. Dando a partida nos motores!
    hardware.start()
    audio.start()
    updater.start()
    overlay.show()
    settings_gui.show()

    # Limpeza ao sair
    def cleanup():
        log.info("Encerrando threads...")
        settings_gui.flush_pending_save()
        updater.stop()
        settings_gui.stop_threads()
        hardware.stop()
        audio.stop()
        overlay.close()
        # Mantém o inode: apagar o arquivo abre uma corrida entre instâncias.
        lock_fp.close()

    app.aboutToQuit.connect(cleanup)

    log.info("Todos os sistemas online. Aguardando comandos do passador.")
    # O supervisor só confirma a atualização quando o primeiro ciclo de
    # eventos roda, após a construção da interface e início dos workers.
    ready_path = os.environ.pop("BASEUS_UPDATE_READY_FILE", None)
    if ready_path:
        ready_file = open(ready_path, "w", encoding="utf-8")
        QTimer.singleShot(0, lambda: (
            ready_file.write(str(os.getpid())), ready_file.flush(), ready_file.close()))
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
