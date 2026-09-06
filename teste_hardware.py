# ~/Documentos/Projetos/baseus-presenter-linux/teste_hardware.py
import sys
import os
from PyQt5.QtCore import QCoreApplication

# Permite que o script enxergue a pasta 'app'
sys.path.append(os.path.dirname(__file__))

from app.hardware import HardwareReader
from app.logger import get_logger

log = get_logger("Sniffer")

def main():
    # QCoreApplication é a versão "invisível" do PyQt5, feita só para rodar nos bastidores sem janela gráfica!
    app = QCoreApplication(sys.argv)
    
    log.info("🔌 Iniciando o Farejador USB (Modo Super Leve)...")
    
    hw = HardwareReader()
    
    # Vamos "escutar" os sinais que o hardware emite e jogar tudo no logger
    hw.pointer_active.connect(lambda estado: log.info(f"Laser/Mouse ativo? {estado}"))
    hw.toggle_mode.connect(lambda: log.info("Troca de Modo (duplo clique) acionada!"))
    hw.battery_update.connect(lambda carga: log.info(f"Sinal de Bateria: {carga}"))
    hw.record_toggled.connect(lambda estado: log.info(f"🎤 Botão de Gravar: {estado}"))
    hw.translate_toggled.connect(lambda estado: log.info(f"🌐 Botão de Traduzir: {estado}"))
    hw.black_screen_toggle.connect(lambda: log.info("Botão de Tela Preta acionado!"))
    
    hw.start()
    
    log.info("Passador conectado! Aperte os botões e veja a mágica. (Pressione Ctrl+C para sair)")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
