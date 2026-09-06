# ~/Documentos/Projetos/baseus-presenter-linux/app/hardware.py
import os
import time
import select
from PyQt5.QtCore import QThread, pyqtSignal
from .logger import get_logger

log = get_logger(__name__)

try:
    import pyudev
except ImportError:
    pyudev = None
    log.warning("pyudev ausente. Hot-plug USB não funcionará em tempo real.")

try:
    from evdev import InputDevice, UInput, list_devices, ecodes as e
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    log.warning("Biblioteca evdev não instalada. Giroscópio desativado.")

class HardwareReader(QThread):
    pointer_active = pyqtSignal(bool)
    toggle_mode = pyqtSignal()
    trigger_click = pyqtSignal()
    battery_update = pyqtSignal(str)
    pen_active = pyqtSignal(bool)
    pen_clear = pyqtSignal()
    black_screen_toggle = pyqtSignal()
    record_toggled = pyqtSignal(bool)
    translate_toggled = pyqtSignal(bool)

    def __init__(self, vendor_id="abc8", product_id="ca08"):
        super().__init__()
        self.vendor_id_hex = vendor_id
        self.product_id_hex = product_id
        self.vendor_id_str = vendor_id.upper()
        self.running = True

    def run(self):
        log.info("Iniciando monitoramento USB (Hidraw + Evdev)...")
        
        if pyudev:
            context = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem='hidraw')
            monitor.start()
        else:
            monitor = None

        self.fds = {}
        self.kbd = None
        self.mouse_ev = None
        self.ui = None

        def scan_devices():
            for fd in list(self.fds.keys()):
                try: os.close(fd)
                except OSError: pass
            self.fds.clear()

            # 1. Busca Hidraw Raiz (Botões e Bateria)
            for i in range(20):
                path = f"/sys/class/hidraw/hidraw{i}/device/uevent"
                if os.path.exists(path):
                    try:
                        with open(path, 'r') as f:
                            if self.vendor_id_str in f.read().upper():
                                node = f"/dev/hidraw{i}"
                                self.fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
                                log.info(f"Conexão Baseus estabelecida: {node}")
                    except OSError: pass

            # 2. Busca Evdev Raiz (Giroscópio, Lupa e Laser)
            if EVDEV_AVAILABLE:
                if self.ui: self.ui.close(); self.ui = None
                if self.kbd: self.kbd.ungrab()
                if self.mouse_ev: self.mouse_ev.ungrab()
                self.kbd = None; self.mouse_ev = None

                try:
                    v_id = int(self.vendor_id_hex, 16)
                    p_id = int(self.product_id_hex, 16)
                    for path in list_devices():
                        dev = InputDevice(path)
                        if dev.info.vendor == v_id and dev.info.product == p_id:
                            if 'Keyboard' in dev.name: self.kbd = dev
                            elif 'Mouse' in dev.name: self.mouse_ev = dev
                    
                    if self.kbd and self.mouse_ev:
                        self.kbd.grab()
                        self.mouse_ev.grab()
                        self.ui = UInput.from_device(self.kbd, self.mouse_ev, name='baseus-virtual')
                        log.info("Giroscópio virtualizado com sucesso!")
                except Exception as exc:
                    log.error(f"Erro no giroscópio: {exc}")

        # Roda a busca inicial
        scan_devices()

        last_click_time = 0; last_gyro_time = 0; press_time = 0
        is_drawing = False; is_pen_drawing = False; just_toggled = False; active_tool = None 
        DEBOUNCE = 0.5; last_rec_toggle = 0; last_translate_toggle = 0
        is_recording = False; is_translating = False

        while self.running:
            watch_fds = list(self.fds.keys())
            if monitor: watch_fds.append(monitor.fileno())
            if self.kbd: watch_fds.append(self.kbd.fd)
            if self.mouse_ev: watch_fds.append(self.mouse_ev.fd)

            if not watch_fds:
                time.sleep(1)
                if not monitor: scan_devices()
                continue

            r, w, x = select.select(watch_fds, [], [], 0.05)
            for fd in r:
                
                # ---- SENSOR 1: EVDEV (O Movimento da Lupa/Laser) ----
                if EVDEV_AVAILABLE and ((self.kbd and fd == self.kbd.fd) or (self.mouse_ev and fd == self.mouse_ev.fd)):
                    dev = self.kbd if fd == self.kbd.fd else self.mouse_ev
                    try:
                        for ev in dev.read():
                            if ev.type == e.EV_KEY:
                                if ev.code == e.KEY_B: continue
                                if is_pen_drawing and (ev.code == e.BTN_LEFT or ev.code == e.KEY_ESC): continue  
                            if self.ui: 
                                self.ui.write_event(ev); self.ui.syn()
                    except OSError: pass
                    continue

                # ---- SENSOR 2: HOTPLUG (Colocar/Tirar do USB) ----
                if monitor and fd == monitor.fileno():
                    device = monitor.poll(0)
                    if device and device.action in ['add', 'remove']: 
                        time.sleep(0.5); scan_devices()
                    continue

                # ---- SENSOR 3: HIDRAW (Os Botões Baseus) ----
                try: data = os.read(fd, 64)
                except OSError: continue
                if not data: continue
                
                try:
                    if data[0] == 0x0A:
                        self.battery_update.emit(f"🔋 Bateria: {data[3]}%")
                        comando = data[5]
                        
                        if comando in [0x71, 0x72, 0x73]:
                            active_tool = "LASER"; curr = time.time()
                            if curr - last_click_time < 0.4:
                                self.toggle_mode.emit(); self.pointer_active.emit(True)
                                last_click_time = 0; just_toggled = True; press_time = curr
                            else: 
                                last_click_time = curr; press_time = curr; just_toggled = False
                            last_gyro_time = time.time()
                            if not is_drawing: self.pointer_active.emit(True); is_drawing = True
                        
                        elif comando == 0x68:
                            active_tool = "PEN"; last_gyro_time = time.time()
                            if not is_pen_drawing: self.pen_active.emit(True); is_pen_drawing = True
                        elif comando in [0x6a, 0x6c, 0x67, 0x69]: self.pen_clear.emit() 
                        elif comando == 0x6d: self.black_screen_toggle.emit()
                        
                        # A INVERSÃO DEFINITIVA CALCULADA!
                        elif comando in [0x75, 0x76, 0x77]: # MICROFONE FÍSICO
                            now = time.time()
                            if now - last_rec_toggle > DEBOUNCE:
                                is_recording = not is_recording; last_rec_toggle = now
                                self.record_toggled.emit(is_recording)
                                
                        elif comando in [0x7a, 0x7c, 0x7d]: # TRADUÇÃO FÍSICA
                            now = time.time()
                            if now - last_translate_toggle > DEBOUNCE:
                                is_translating = not is_translating; last_translate_toggle = now
                                self.translate_toggled.emit(is_translating)
                                
                    elif data[0] == 0x02:
                        if active_tool in ["LASER", "PEN"]: last_gyro_time = time.time()
                        if active_tool == "LASER" and not is_drawing and last_click_time > 0:
                            self.pointer_active.emit(True); is_drawing = True
                        elif active_tool == "PEN" and not is_pen_drawing:
                            self.pen_active.emit(True); is_pen_drawing = True
                except IndexError: pass

            if time.time() - last_gyro_time > 0.3:
                if is_drawing:
                    self.pointer_active.emit(False); is_drawing = False
                    if active_tool == "LASER" and not just_toggled and (time.time() - press_time < 0.4): 
                        self.trigger_click.emit()
                if is_pen_drawing:
                    self.pen_active.emit(False); is_pen_drawing = False
                active_tool = None

        # Limpa tudo ao sair (Fim do vazamento de RAM!)
        for fd in list(self.fds.keys()):
            try: os.close(fd)
            except OSError: pass
        if EVDEV_AVAILABLE:
            if self.ui: self.ui.close()
            if self.kbd: self.kbd.ungrab()
            if self.mouse_ev: self.mouse_ev.ungrab()

    def stop(self):
        self.running = False
        self.wait()
