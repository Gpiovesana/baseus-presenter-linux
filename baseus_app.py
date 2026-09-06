# ~/Documentos/Projetos/baseus-presenter-linux/baseus_app.py
import sys
import os
import fcntl
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

from app.logger import get_logger
from app.config import load_config
from app.hardware import HardwareReader
from app.audio import AudioThread
from app.overlay import PointerWindow
from app.gui import MainWindow, TrayIcon

log = get_logger("Main")

def main():
    # 1. Trava de Instância (Evita abrir duas vezes e bugar a porta USB)
    lock_file = '/tmp/baseus_presenter.lock'
    lock_fp = open(lock_file, 'w')
    try:
        fcntl.lockf(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        log.error("O aplicativo já está rodando! Fechando esta nova tentativa.")
        sys.exit(1)

    # 2. Inicialização do Qt e Carregamento de Configurações
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # Mantém rodando mesmo se fechar a janela de config
    
    config = load_config()
    log.info("Iniciando o Baseus Presenter (Versão 2.0 Modular)...")

    # 3. Instanciando os Módulos (Nenhum deles sabe que os outros existem)
    hardware = HardwareReader()
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
    
    # Hardware conversando com o Áudio (Usa as novas funções limpas)
    hardware.record_toggled.connect(audio.set_recording)
    hardware.translate_toggled.connect(audio.set_translating)
    
    # Áudio conversando com o Visor 
    audio.partial_ready.connect(overlay.show_subtitle)
    audio.final_ready.connect(overlay.show_subtitle)
    audio.audio_warning.connect(lambda msg: overlay.show_subtitle(msg, 4000))
    
    # Interface Gráfica conversando com Visor e Áudio 
    settings_gui.config_updated.connect(overlay.update)
    settings_gui.model_changed.connect(audio.trigger_reload)
    
    # Passa a bateria para a Janela e para a Bandeja do Sistema (Ícone)
    hardware.battery_update.connect(settings_gui.update_battery)
    hardware.battery_update.connect(lambda msg: tray.setToolTip(f"Baseus Presenter - {msg}"))
    # =========================================================================

    # 5. Dando a partida nos motores!
    hardware.start()
    audio.start()
    overlay.show()
    settings_gui.show() # <-- ADICIONE ESTA LINHA AQUI!
    
    log.info("Todos os sistemas online. Aguardando comandos do passador.")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
