# ~/Documentos/Projetos/baseus-presenter-linux/baseus_app.py
import sys
import os
import fcntl
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

from app.logger import get_logger
from app.config import Config
from app.hardware import HardwareReader
from app.audio import AudioThread
from app.overlay import PointerWindow
from app.gui import MainWindow, TrayIcon

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
        # Modo 'a+eee' (não 'w'): abrir com 'w' TRUNCA o arquivo antes de
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
    
    # Config agora é um wrapper com lock: o mesmo dict era compartilhado por
    # 3 threads sem nenhuma proteção.
    config = Config()
    log.info("Iniciando o Baseus Presenter (Versão 2.0 Modular)...")

    # 3. Instanciando os Módulos (Nenhum deles sabe que os outros existem)
    hardware = HardwareReader(config=config)
    audio = AudioThread(config)
    overlay = PointerWindow(config)
    settings_gui = MainWindow(config)
    tray = TrayIcon(settings_gui)
    
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
    hardware.record_toggled.connect(overlay.set_recording)
    hardware.translate_toggled.connect(overlay.set_translating)
    hardware.black_screen_toggle.connect(overlay.toggle_black_screen)
    
    # Hardware conversando com o Áudio (Usa as novas funções limpas)
    hardware.record_toggled.connect(audio.set_recording)
    hardware.translate_toggled.connect(audio.set_translating)
    
    # Áudio conversando com o Visor 
    audio.partial_ready.connect(overlay.show_subtitle)
    audio.final_ready.connect(overlay.show_subtitle)
    audio.audio_warning.connect(lambda msg: overlay.show_subtitle(msg, 4000))
    # #15: audio_error é para falhas que exigem que a UI sincronize o
    # estado (ex.: desmarcar visualmente a gravação). Mostra tanto no
    # overlay (mais tempo em tela, é mais grave que um aviso comum) quanto
    # na janela de configurações.
    audio.audio_error.connect(lambda msg: overlay.show_subtitle(msg, 6000))
    audio.audio_error.connect(settings_gui.show_warning)
    
    # Interface Gráfica conversando com Visor e Áudio
    # update_visual_config invalida o cache visual do overlay (paintEvent roda
    # a 60 FPS e não pode reler o config a cada quadro).
    settings_gui.config_updated.connect(overlay.update_visual_config)
    settings_gui.model_changed.connect(audio.trigger_reload)
    # #16: troca de microfone (seleção manual ou troca de perfil) pede à
    # AudioThread para fechar e reabrir o RawInputStream com o device_id
    # atualizado.
    settings_gui.input_device_changed.connect(audio.request_stream_restart)
    
    # Passa a bateria para a Janela e para a Bandeja do Sistema (Ícone)
    hardware.battery_update.connect(settings_gui.update_battery)
    hardware.battery_update.connect(tray.update_battery)

    # Avisos de permissão (regra udev / grupo 'input') viram feedback visível
    hardware.permission_error.connect(settings_gui.show_warning)
    hardware.permission_error.connect(lambda msg: overlay.show_subtitle(msg, 6000))
    # =========================================================================

    # 5. Dando a partida nos motores!
    hardware.start()
    audio.start()
    overlay.show()
    settings_gui.show() # <-- ADICIONE ESTA LINHA AQUI!
    
    # Limpeza ao sair
    def cleanup():
        log.info("Encerrando threads...")
        # Persiste alterações que ainda estavam no debounce do save.
        try:
            settings_gui.flush_pending_save()
        except Exception:
            log.exception("Falha ao gravar configurações pendentes.")

        # Cada etapa é isolada: uma falha não pode impedir a liberação do
        # hardware nem a remoção do lock.
        for nome, acao in (("hardware", hardware.stop),
                           ("audio", audio.stop),
                           ("threads da GUI", settings_gui.stop_threads),
                           ("overlay", overlay.close)):
            try:
                acao()
            except Exception:
                log.exception(f"Falha ao encerrar {nome}.")

        # #30: NÃO removemos o arquivo de lock. Fazer unlink abria uma janela
        # de corrida: um processo B que já tinha aberto o arquivo (mas ainda
        # não travado) ficava com o inode antigo, enquanto um processo C
        # criava e travava um arquivo NOVO no mesmo caminho — resultando em
        # duas instâncias simultâneas, cada uma "dona" de um inode diferente.
        # Basta fechar o descritor: o lock do fcntl é liberado pelo kernel e
        # o arquivo (vazio, alguns bytes) é reutilizado na próxima execução.
        lock_fp.close()
        log.info("Encerramento concluído.")
    
    app.aboutToQuit.connect(cleanup)
    
    log.info("Todos os sistemas online. Aguardando comandos do passador.")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
