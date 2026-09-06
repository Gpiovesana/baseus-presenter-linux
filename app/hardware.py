# ~/Documentos/Projetos/baseus-presenter-linux/app/hardware.py
import os
import time
import fcntl
import select
from PyQt5.QtCore import QThread, pyqtSignal
from .logger import get_logger

log = get_logger(__name__)

class HardwareReader(QThread):
    pointer_active = pyqtSignal(bool)
    toggle_mode = pyqtSignal()
    pen_active = pyqtSignal(bool)
    pen_clear = pyqtSignal()
    battery_update = pyqtSignal(str)
    record_toggled = pyqtSignal(bool)
    translate_toggled = pyqtSignal(bool)
    black_screen_toggle = pyqtSignal()

    def __init__(self, vendor_id="33ea", product_id="1001"):
        super().__init__()
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.running = True # A trava de segurança que o ChatGPT pediu
        self.device_file = self.find_device()

    def find_device(self):
        try:
            import pyudev
            context = pyudev.Context()
            for device in context.list_devices(subsystem='hidraw'):
                if 'ID_VENDOR_ID' in device.properties and 'ID_MODEL_ID' in device.properties:
                    if device.properties['ID_VENDOR_ID'].lower() == self.vendor_id and \
                       device.properties['ID_MODEL_ID'].lower() == self.product_id:
                        return device.device_node
        except ImportError:
            log.warning("pyudev não instalado. Tentando busca manual de dispositivo...")
        return None

    def run(self):
        if not self.device_file:
            log.error("Passador Baseus não encontrado. Hardware monitor desativado.")
            return

        try:
            fd = os.open(self.device_file, os.O_RDONLY | os.O_NONBLOCK)
        except PermissionError:
            log.error(f"Sem permissão para ler {self.device_file}. Rode: sudo chmod a+r {self.device_file}")
            return
        
        log.info("Iniciando monitoramento de hardware USB (Baseus)...")
        
        is_laser_active = False
        is_pen_active = False
        is_recording = False
        is_translating = False
        
        last_rec_toggle = 0
        last_translate_toggle = 0
        DEBOUNCE = 0.5

        while self.running:
            # O select impede que o programa trave aqui esperando o botão
            r, _, _ = select.select([fd], [], [], 0.5)
            if fd in r:
                try:
                    data = os.read(fd, 32)
                    if len(data) >= 6:
                        comando = data[5]
                        
                        # Bateria
                        if data[3] == 0x08 and data[4] == 0x07:
                            self.battery_update.emit(f"🔋 Bateria: {comando}%")
                            
                        # Ponteiro/Laser
                        elif comando == 0x02:
                            if not is_laser_active:
                                is_laser_active = True
                                self.pointer_active.emit(True)
                        elif comando == 0x0a:
                            if is_laser_active:
                                is_laser_active = False
                                self.pointer_active.emit(False)
                        
                        # Duplo clique (Modo)
                        elif comando == 0x01:
                            self.toggle_mode.emit()

                        # --- A INVERSÃO DEFINITIVA DOS BOTÕES ---
                        elif comando in [0x75, 0x76, 0x77]: # Botão do Microfone
                            now = time.time()
                            if now - last_rec_toggle > DEBOUNCE:
                                is_recording = not is_recording; last_rec_toggle = now
                                self.record_toggled.emit(is_recording)
                                
                        elif comando in [0x7a, 0x7c, 0x7d]: # Botão de Tradução (Legenda)
                            now = time.time()
                            if now - last_translate_toggle > DEBOUNCE:
                                is_translating = not is_translating; last_translate_toggle = now
                                self.translate_toggled.emit(is_translating)

                except OSError:
                    break
                    
        os.close(fd)
        log.info("Monitoramento de hardware encerrado com segurança.")

    def stop(self):
        self.running = False
        self.wait()
