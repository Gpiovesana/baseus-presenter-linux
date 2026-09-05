#!/usr/bin/env python3
import sys
import os
import time
import select
import json
import pyudev
import queue
import copy

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QSlider, QComboBox, QFileDialog, QColorDialog, QGroupBox,
    QSystemTrayIcon, QProgressDialog, QMenu, QAction, QInputDialog, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QRectF, QRect
from PyQt5.QtGui import QPainter, QColor, QPainterPath, QIcon, QPixmap, QPen, QFont, QFontMetrics
from pynput.mouse import Controller, Button

import sounddevice as sd
from vosk import Model, KaldiRecognizer
import argostranslate.translate
import argostranslate.package

try:
    from evdev import InputDevice, UInput, ecodes as e, list_devices
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False

# ==========================================
# CONFIGURAÇÕES BASE
# ==========================================
CONFIG_PATH = os.path.expanduser("~/.config/baseus_pointer.json")
MODELS_DIR = os.path.expanduser("~/.config/baseus_pointer/models")

LANG_OPTIONS = [
    ("Inglês", "en"), ("Espanhol", "es"), ("Francês", "fr"), ("Alemão", "de"), ("Italiano", "it"), ("Português", "pt")
]

DEFAULT_CONFIG = {
    "close_behavior": "tray",
    "save_dir": os.path.expanduser("~"),
    "visual": {
        "laser_size": 30, "lupa_size": 250, "spotlight_size": 300,
        "spotlight_opacity": 160, "lupa_shape": "circular",
        "laser_color": "#FF0000", "pincel_color": "#FF0000",
    },
    "audio": {
        "target_lang": "en",
        "selected_model_path": "",
        "models": [] # Lista dinâmica: [{"label": "Nome", "path": "caminho", "lang": "pt"}]
    },
}

def _deep_merge(defaults, loaded):
    result = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else: result[key] = value
    return result

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f: loaded = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, loaded)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    try:
        # Escreve primeiro num arquivo temporário (Salvamento Atômico do Claude)
        with open(tmp_path, "w") as f: 
            json.dump(config, f, indent=2)
        os.replace(tmp_path, CONFIG_PATH)
    except OSError: 
        pass
# ==========================================
# THREADS DE DOWNLOAD DO ARGOS TRANSLATE
# ==========================================
class ArgosIndexThread(QThread):
    packages_ready = pyqtSignal(list)
    def run(self):
        try:
            argostranslate.package.update_package_index()
            self.packages_ready.emit(argostranslate.package.get_available_packages())
        except Exception as e:
            print(f"⚠️ Erro ao buscar pacotes de idiomas na internet: {e}")
            self.packages_ready.emit([])

class PackageInstallThread(QThread):
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, from_code, to_code, available_packages):
        super().__init__()
        self.from_code = from_code; self.to_code = to_code; self.available_packages = available_packages

    def run(self):
        try:
            pkg = next((p for p in self.available_packages if p.from_code == self.from_code and p.to_code == self.to_code), None)
            if pkg is None:
                self.failed.emit(f"Pacote {self.from_code} -> {self.to_code} não existe nos servidores.")
                return
            download_path = pkg.download()
            argostranslate.package.install_from_path(download_path)
            self.finished_ok.emit(self.to_code)
        except Exception as e:
            self.failed.emit(f"Falha de rede ou instalação: {str(e)}")

# ==========================================
# THREAD DE ÁUDIO (VOSK)
# ==========================================
class AudioThread(QThread):
    partial_ready = pyqtSignal(str); final_ready = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.q = queue.Queue(); self.is_listening = False; self.config = config
        self.load_active_model()

    def load_active_model(self):
        model_path = self.config["audio"]["selected_model_path"]
        try:
            if model_path and os.path.exists(model_path):
                self.model = Model(model_path)
                self.rec = KaldiRecognizer(self.model, 16000)
                self.model_loaded = True
                print(f"🎙️ Vosk carregado de: {model_path}")
            else:
                self.model_loaded = False
                print("⚠️ Nenhum modelo Vosk válido selecionado.")
        except Exception as e:
            self.model_loaded = False
            print(f"⚠️ Erro no Vosk: {e}")

    def callback_audio(self, indata, frames, time, status):
        if self.is_listening: self.q.put(bytes(indata))

    def run(self):
        with sd.RawInputStream(samplerate=16000, blocksize=4000, device=None, dtype='int16', channels=1, callback=self.callback_audio):
            while True:
                if self.is_listening and self.model_loaded:
                    data = self.q.get()
                    if self.rec.AcceptWaveform(data):
                        res = json.loads(self.rec.Result())
                        if res.get("text"): self.final_ready.emit(res["text"])
                    else:
                        res = json.loads(self.rec.PartialResult())
                        if res.get("partial"): self.partial_ready.emit(res["partial"])
                else:
                    while not self.q.empty(): self.q.get()
                    time.sleep(0.1)

# ==========================================
# THREAD DO PASSADOR (DEBOUNCE)
# ==========================================
class USBReader(QThread):
    pointer_active = pyqtSignal(bool); toggle_mode = pyqtSignal(); trigger_click = pyqtSignal()
    battery_update = pyqtSignal(str); pen_active = pyqtSignal(bool); pen_clear = pyqtSignal()
    black_screen_toggle = pyqtSignal(); record_toggled = pyqtSignal(bool); translate_toggled = pyqtSignal(bool)

    def run(self):
        context = pyudev.Context(); monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem='hidraw'); monitor.start()
        self.fds = {}; self.kbd = None; self.mouse_ev = None; self.ui = None

        def scan_devices():
            for fd in list(self.fds.keys()):
                try: os.close(fd)
                except OSError: pass
            self.fds.clear()
            for i in range(20):
                path = f"/sys/class/hidraw/hidraw{i}/device/uevent"
                if os.path.exists(path):
                    try:
                        with open(path, 'r') as f:
                            if 'ABC8' in f.read().upper():
                                node = f"/dev/hidraw{i}"
                                self.fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
                    except OSError: pass
            if EVDEV_AVAILABLE:
                if self.ui: self.ui.close(); self.ui = None
                if self.kbd: self.kbd.ungrab()
                if self.mouse_ev: self.mouse_ev.ungrab()
                try:
                    for path in list_devices():
                        dev = InputDevice(path)
                        if dev.info.vendor == 0xabc8 and dev.info.product == 0xca08:
                            if 'Keyboard' in dev.name: self.kbd = dev
                            elif 'Mouse' in dev.name: self.mouse_ev = dev
                    if self.kbd and self.mouse_ev:
                        self.kbd.grab(); self.mouse_ev.grab()
                        self.ui = UInput.from_device(self.kbd, self.mouse_ev, name='baseus-virtual')
                except Exception: pass
        scan_devices()

        last_click_time = 0; last_gyro_time = 0; press_time = 0
        is_drawing = False; is_pen_drawing = False; just_toggled = False; active_tool = None 
        DEBOUNCE = 0.5; last_rec_toggle = 0; last_translate_toggle = 0
        is_recording = False; is_translating = False

        while True:
            watch_fds = list(self.fds.keys()) + [monitor.fileno()]
            if self.kbd: watch_fds.append(self.kbd.fd)
            if self.mouse_ev: watch_fds.append(self.mouse_ev.fd)

            r, w, x = select.select(watch_fds, [], [], 0.05)
            for fd in r:
                if EVDEV_AVAILABLE and ((self.kbd and fd == self.kbd.fd) or (self.mouse_ev and fd == self.mouse_ev.fd)):
                    dev = self.kbd if fd == self.kbd.fd else self.mouse_ev
                    for ev in dev.read():
                        if ev.type == e.EV_KEY:
                            if ev.code == e.KEY_B: continue 
                            if is_pen_drawing and (ev.code == e.BTN_LEFT or ev.code == e.KEY_ESC): continue  
                        if self.ui: self.ui.write_event(ev); self.ui.syn()
                    continue

                if fd == monitor.fileno():
                    device = monitor.poll(0)
                    if device and device.action in ['add', 'remove']: time.sleep(0.5); scan_devices()
                    continue

                try: data = os.read(fd, 64)
                except OSError: continue
                if not data: continue
                
                if data[0] == 0x0A:
                    self.battery_update.emit(f"🔋 Bateria: {data[3]}%")
                    comando = data[5]
                    
                    if comando in [0x71, 0x72, 0x73]:
                        active_tool = "LASER"; curr = time.time()
                        if curr - last_click_time < 0.4:
                            self.toggle_mode.emit(); self.pointer_active.emit(True)
                            last_click_time = 0; just_toggled = True; press_time = curr
                        else: last_click_time = curr; press_time = curr; just_toggled = False
                        last_gyro_time = time.time()
                        if not is_drawing: self.pointer_active.emit(True); is_drawing = True
                    elif comando in [0x6a, 0x6c]: self.pen_clear.emit() 
                    elif comando == 0x6d: self.black_screen_toggle.emit()
                    elif comando == 0x68:
                        active_tool = "PEN"; last_gyro_time = time.time()
                        if not is_pen_drawing: self.pen_active.emit(True); is_pen_drawing = True
                    elif comando in [0x67, 0x69]: self.pen_clear.emit()
                    
                    elif comando in [0x75, 0x76, 0x77]:
                        now = time.time()
                        if now - last_rec_toggle > DEBOUNCE:
                            is_recording = not is_recording; last_rec_toggle = now; self.record_toggled.emit(is_recording)
                            
                    elif comando in [0x7a, 0x7c, 0x7d]:
                        now = time.time()
                        if now - last_translate_toggle > DEBOUNCE:
                            is_translating = not is_translating; last_translate_toggle = now; self.translate_toggled.emit(is_translating)
                            
                elif data[0] == 0x02:
                    if active_tool in ["LASER", "PEN"]: last_gyro_time = time.time()
                    if active_tool == "LASER" and not is_drawing and last_click_time > 0:
                        self.pointer_active.emit(True); is_drawing = True
                    elif active_tool == "PEN" and not is_pen_drawing:
                        self.pen_active.emit(True); is_pen_drawing = True

            if time.time() - last_gyro_time > 0.3:
                if is_drawing:
                    self.pointer_active.emit(False); is_drawing = False
                    if active_tool == "LASER" and not just_toggled and (time.time() - press_time < 0.4): self.trigger_click.emit()
                if is_pen_drawing:
                    self.pen_active.emit(False); is_pen_drawing = False
                active_tool = None

# ==========================================
# JANELA TRANSPARENTE (OVERLAY)
# ==========================================
class PointerWindow(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.X11BypassWindowManagerHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(0, 0, QApplication.primaryScreen().size().width(), QApplication.primaryScreen().size().height())
        self.modes = ["LASER", "LUPA", "SPOTLIGHT", "MOUSE PURO"]; self.mode_index = 0
        self.is_drawing = False; self.is_pen_drawing = False; self.is_black_screen = False 
        self.is_recording = False; self.is_translating = False; self.blink_state = True
        self.caption_text = ""; self.is_caption_final = True; self.pen_points = []; self.mouse_sim = Controller()
        self.timer = QTimer(); self.timer.timeout.connect(self.update)
        self.blink_timer = QTimer(); self.blink_timer.timeout.connect(self.toggle_blink)
        self.subtitle_timer = QTimer(); self.subtitle_timer.timeout.connect(self.clear_subtitle)

    def toggle_blink(self): self.blink_state = not self.blink_state; self.update()
    def set_partial_subtitle(self, text):
        if self.is_translating: self.caption_text = text; self.is_caption_final = False; self.subtitle_timer.stop(); self._check_timer()
    def set_final_subtitle(self, text):
        if self.is_translating: self.caption_text = text; self.is_caption_final = True; self.subtitle_timer.start(6000); self._check_timer()
    def clear_subtitle(self): self.caption_text = ""; self.update()
    def set_recording(self, state): self.is_recording = state; self._check_hud_timers()
    def set_translating(self, state): 
        self.is_translating = state; 
        if not state: self.clear_subtitle()
        self._check_hud_timers()
    def _check_hud_timers(self):
        if self.is_recording or self.is_translating:
            if not self.blink_timer.isActive(): self.blink_timer.start(500)
        else: self.blink_timer.stop(); self.blink_state = True
        self._check_timer()
    def toggle_black_screen(self): self.is_black_screen = not self.is_black_screen; self._check_timer(); self.update()
    def set_active(self, active):
        self.is_drawing = active; self._check_timer()
        if active and self.modes[self.mode_index] == "LUPA": self.screen_pixmap = QApplication.primaryScreen().grabWindow(0); self.show()
    def set_pen_active(self, active):
        self.is_pen_drawing = active; self._check_timer()
        if not active and self.pen_points and self.pen_points[-1] is not None: self.pen_points.append(None) 
    def clear_pen(self): self.pen_points.clear(); self.update()
    def _check_timer(self):
        if self.is_drawing or self.is_pen_drawing or self.pen_points or self.is_black_screen or self.is_recording or self.is_translating or self.caption_text:
            self.show()
            if not self.timer.isActive(): self.timer.start(16)
        else: self.hide(); self.timer.stop(); self.update()
    def switch_mode(self):
        self.mode_index = (self.mode_index + 1) % len(self.modes)
        if self.is_drawing and self.modes[self.mode_index] == "LUPA": self.hide(); self.screen_pixmap = QApplication.primaryScreen().grabWindow(0); self.show()
        if self.is_drawing: self.update()
    def do_click(self):
        if self.modes[self.mode_index] == "MOUSE PURO": self.mouse_sim.click(Button.left)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.is_black_screen: painter.fillRect(self.rect(), Qt.black)
        painter.setRenderHint(QPainter.Antialiasing)
        pos = self.cursor().pos()
        v = self.config["visual"]
        c_pincel = QColor(v["pincel_color"]); c_laser = QColor(v["laser_color"])

        if self.pen_points or self.is_pen_drawing:
            if self.is_pen_drawing: self.pen_points.append(pos)
            painter.setPen(QPen(c_pincel, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            for i in range(1, len(self.pen_points)):
                p1, p2 = self.pen_points[i-1], self.pen_points[i]
                if p1 is not None and p2 is not None: painter.drawLine(p1, p2)

        if self.is_drawing and self.modes[self.mode_index] != "MOUSE PURO":
            mode = self.modes[self.mode_index]
            if mode == "LASER":
                c_laser.setAlpha(200); painter.setBrush(c_laser); painter.setPen(Qt.NoPen)
                r = v["laser_size"]; painter.drawEllipse(int(pos.x() - r/2), int(pos.y() - r/2), r, r)
            elif mode == "SPOTLIGHT":
                r = v["spotlight_size"]; path = QPainterPath()
                path.addRect(QRectF(self.rect())); path.addEllipse(QRectF(pos.x() - r/2, pos.y() - r/2, r, r))
                painter.setBrush(QColor(0, 0, 0, v["spotlight_opacity"])); painter.setPen(Qt.NoPen); painter.drawPath(path)
            elif mode == "LUPA" and hasattr(self, 'screen_pixmap'):
                r = v["lupa_size"]
                src = QRectF(pos.x() - r/4, pos.y() - r/4, r/2, r/2); dst = QRectF(pos.x() - r/2, pos.y() - r/2, r, r)
                path = QPainterPath()
                if v["lupa_shape"] == "retangular":
                    path.addRect(dst); painter.setClipPath(path)
                    painter.drawPixmap(dst, self.screen_pixmap, src); painter.setClipping(False)
                    painter.setPen(QPen(QColor(255, 255, 255), 3)); painter.drawRect(dst)
                else:
                    path.addEllipse(dst); painter.setClipPath(path)
                    painter.drawPixmap(dst, self.screen_pixmap, src); painter.setClipping(False)
                    painter.setPen(QPen(QColor(255, 255, 255), 3)); painter.drawEllipse(dst)

        if self.blink_state:
            x_pos = 30
            if self.is_recording:
                painter.setBrush(QColor(255, 0, 0)); painter.setPen(Qt.NoPen)
                painter.drawEllipse(x_pos, 30, 20, 20); x_pos += 30
            if self.is_translating:
                painter.setBrush(QColor(0, 150, 255)); painter.setPen(Qt.NoPen)
                painter.drawEllipse(x_pos, 30, 20, 20)
                
        if self.is_translating and self.caption_text:
            text_color = QColor(200, 200, 200) if not self.is_caption_final else QColor(255, 255, 255)
            font = QFont("Arial", 28, QFont.Bold); painter.setFont(font); fm = QFontMetrics(font)
            max_w = int(self.width() * 0.7); margin = 20
            text_rect = fm.boundingRect(QRect(0, 0, max_w, 10000), Qt.TextWordWrap | Qt.AlignHCenter, self.caption_text)
            box_w = text_rect.width() + margin*2; box_h = text_rect.height() + margin*2
            box_x = (self.width() - box_w) // 2; box_y = self.height() - box_h - 60 
            painter.setBrush(QColor(0, 0, 0, 170)); painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(box_x, box_y, box_w, box_h, 12, 12)
            painter.setPen(text_color)
            painter.drawText(QRectF(box_x + margin, box_y + margin, box_w - margin*2, box_h - margin*2), Qt.TextWordWrap | Qt.AlignHCenter, self.caption_text)

# ==========================================
# GUI: BOTÃO DE COR E MAIN WINDOW
# ==========================================
class ColorButton(QPushButton):
    colorChanged = pyqtSignal(str)
    def __init__(self, initial_hex="#FF0000", parent=None):
        super().__init__(parent); self._color = initial_hex; self.setFixedWidth(90)
        self.clicked.connect(self._pick_color); self._update_style()
    def _update_style(self):
        self.setStyleSheet(f"background-color: {self._color}; border: 1px solid #555; border-radius: 4px; color: white; font-weight: bold;"); self.setText(self._color.upper())
    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, "Escolher cor")
        if color.isValid(): self._color = color.name(); self._update_style(); self.colorChanged.emit(self._color)

class MainWindow(QMainWindow):
    config_updated = pyqtSignal()
    model_changed = pyqtSignal() # Sinaliza para recarregar o Vosk
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self._available_packages = [] # Cache de pacotes do Argos
        
        # Inicia a busca silenciosa dos pacotes de tradução na internet
        self.index_thread = ArgosIndexThread()
        self.index_thread.packages_ready.connect(self._on_packages_ready)
        self.index_thread.start()

        self.setWindowTitle("Baseus Presenter — Configurações")
        self.resize(520, 480)
        tabs = QTabWidget()
        tabs.addTab(self._build_tab_general(), "Geral")
        tabs.addTab(self._build_tab_visual(), "Visual")
        tabs.addTab(self._build_tab_audio(), "Áudio e Idioma")
        self.setCentralWidget(tabs)

    def _on_packages_ready(self, packages):
        self._available_packages = packages
        print(f"🌍 Servidor Argos contactado. {len(packages)} pacotes de tradução disponíveis.")

    # [ABAS GERAL E VISUAL MANTERAM-SE IGUAIS - omitidas para focar no Áudio]
    def _build_tab_general(self):
        widget = QWidget(); layout = QVBoxLayout()
        close_group = QGroupBox("Comportamento do botão fechar (X)"); close_layout = QVBoxLayout()
        self.radio_tray = QRadioButton("Minimizar para a bandeja do sistema"); self.radio_quit = QRadioButton("Fechar o aplicativo completamente")
        btn_group = QButtonGroup(self); btn_group.addButton(self.radio_tray); btn_group.addButton(self.radio_quit)
        if self.config["close_behavior"] == "quit": self.radio_quit.setChecked(True)
        else: self.radio_tray.setChecked(True)
        self.radio_tray.toggled.connect(lambda: self._update_g_config("close_behavior", "tray" if self.radio_tray.isChecked() else "quit"))
        close_layout.addWidget(self.radio_tray); close_layout.addWidget(self.radio_quit); close_group.setLayout(close_layout); layout.addWidget(close_group)

        dir_group = QGroupBox("Salvar Aula (aula_de_hoje.txt)"); dir_layout = QHBoxLayout()
        self.save_dir_edit = QLineEdit(self.config["save_dir"]); self.save_dir_edit.setReadOnly(True)
        btn_choose_dir = QPushButton("Escolher pasta...")
        btn_choose_dir.clicked.connect(self._on_choose_save_dir)
        dir_layout.addWidget(self.save_dir_edit); dir_layout.addWidget(btn_choose_dir); dir_group.setLayout(dir_layout); layout.addWidget(dir_group)
        layout.addStretch(); widget.setLayout(layout)
        return widget

    def _on_choose_save_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Escolher pasta", self.config["save_dir"])
        if chosen: self.config["save_dir"] = chosen; self.save_dir_edit.setText(chosen); self._save()
    def _update_g_config(self, key, value): self.config[key] = value; self._save()

    def _build_tab_visual(self):
        widget = QWidget(); layout = QVBoxLayout(); v = self.config["visual"]; form = QFormLayout()
        self.slider_laser = self._make_slider(10, 100, v["laser_size"], lambda val: self._update_v_config("laser_size", val))
        form.addRow("Tamanho do Laser:", self.slider_laser)
        self.slider_lupa = self._make_slider(100, 600, v["lupa_size"], lambda val: self._update_v_config("lupa_size", val))
        form.addRow("Tamanho da Lupa:", self.slider_lupa)
        self.slider_spotlight = self._make_slider(100, 600, v["spotlight_size"], lambda val: self._update_v_config("spotlight_size", val))
        form.addRow("Tamanho do Spotlight:", self.slider_spotlight)
        self.slider_spotlight_opacity = self._make_slider(0, 255, v["spotlight_opacity"], lambda val: self._update_v_config("spotlight_opacity", val))
        form.addRow("Opacidade do Spotlight:", self.slider_spotlight_opacity)
        self.combo_lupa_shape = QComboBox(); self.combo_lupa_shape.addItem("Circular", "circular"); self.combo_lupa_shape.addItem("Retangular", "retangular")
        self.combo_lupa_shape.setCurrentIndex(max(self.combo_lupa_shape.findData(v["lupa_shape"]), 0))
        self.combo_lupa_shape.currentIndexChanged.connect(lambda: self._update_v_config("lupa_shape", self.combo_lupa_shape.currentData()))
        form.addRow("Formato da Lupa:", self.combo_lupa_shape)
        self.btn_laser_color = ColorButton(v["laser_color"]); self.btn_laser_color.colorChanged.connect(lambda h: self._update_v_config("laser_color", h))
        form.addRow("Cor do Laser:", self.btn_laser_color)
        self.btn_pincel_color = ColorButton(v["pincel_color"]); self.btn_pincel_color.colorChanged.connect(lambda h: self._update_v_config("pincel_color", h))
        form.addRow("Cor do Pincel:", self.btn_pincel_color)
        layout.addLayout(form); layout.addStretch(); widget.setLayout(layout)
        return widget

    def _make_slider(self, m_min, m_max, val, cb):
        s = QSlider(Qt.Horizontal); s.setRange(m_min, m_max); s.setValue(val); s.valueChanged.connect(cb); return s
    def _update_v_config(self, key, value): self.config["visual"][key] = value; self._save()

# === ABA DE ÁUDIO REFEITA (A Mágica da Arquitetura do Claude) ===
    def _build_tab_audio(self):
        widget = QWidget(); layout = QVBoxLayout(); a = self.config["audio"]

        # Gerenciador de Modelos (Híbrido)
        model_group = QGroupBox("1. Modelo de Transcrição (Vosk)"); model_layout = QVBoxLayout()
        
        row1 = QHBoxLayout()
        self.combo_models = QComboBox()
        self._populate_models_combo()
        self.combo_models.currentIndexChanged.connect(self._on_model_selected)
        
        btn_add_model = QPushButton("+ Adicionar pasta...")
        btn_add_model.clicked.connect(self._on_add_model_clicked)
        
        btn_del_model = QPushButton("🗑️ Excluir")
        btn_del_model.clicked.connect(self._on_del_model_clicked)
        
        row1.addWidget(self.combo_models, stretch=1)
        row1.addWidget(btn_add_model)
        row1.addWidget(btn_del_model)
        
        model_layout.addLayout(row1)
        model_group.setLayout(model_layout); layout.addWidget(model_group)

        # Tradutor (com Guarda-Costas)
        target_group = QGroupBox("2. Tradução ao Vivo (Argos)"); target_form = QFormLayout()
        self.combo_target = QComboBox()
        for name, code in LANG_OPTIONS: self.combo_target.addItem(name, code)
        self.combo_target.setCurrentIndex(max(self.combo_target.findData(a["target_lang"]), 0))
        self.combo_target.currentIndexChanged.connect(self._on_target_lang_changed)
        
        target_form.addRow("Traduzir legenda para:", self.combo_target)
        target_group.setLayout(target_form); layout.addWidget(target_group)

        layout.addStretch(); widget.setLayout(layout)
        return widget

    def _populate_models_combo(self):
        self.combo_models.blockSignals(True)
        self.combo_models.clear()
        
        models = self.config["audio"].get("models", [])
        if not models:
            self.combo_models.addItem("Nenhum modelo cadastrado", "")
        else:
            for m in models:
                # Exibe o label bonito, mas guarda o path como dado
                self.combo_models.addItem(f"{m['label']} [{m['lang'].upper()}]", m['path'])
                
            # Seleciona o que tava salvo no config
            current_path = self.config["audio"]["selected_model_path"]
            idx = self.combo_models.findData(current_path)
            if idx >= 0: self.combo_models.setCurrentIndex(idx)
            
        self.combo_models.blockSignals(False)

    def _on_model_selected(self):
        path = self.combo_models.currentData()
        if path:
            self.config["audio"]["selected_model_path"] = path
            self._save()
            self.model_changed.emit() # Avisa a AudioThread para carregar a IA nova!

    def _on_add_model_clicked(self):
        path = QFileDialog.getExistingDirectory(self, "Selecione a pasta extraída do Vosk")
        if not path: return
        
        # Validação flexível: Se não achar as pastas comuns, apenas avisa, mas não bloqueia.
        if not any(os.path.exists(os.path.join(path, f)) for f in ["am", "conf", "graph", "ivector", "mfcc.conf"]):
            reply = QMessageBox.question(self, "Aviso", "Esta pasta não parece ter a estrutura padrão de um modelo Vosk. Deseja tentar adicioná-la mesmo assim?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No: return
            
        label, ok1 = QInputDialog.getText(self, "Novo Modelo", "Dê um nome (ex: Português Leve):")
        if not ok1 or not label: return
        
        # Orientação clara para evitar o erro do "pr-br"
        lang, ok2 = QInputDialog.getText(self, "Idioma", "Qual a sigla ISO (2 letras) deste modelo? (EXATAMENTE: pt, en, es, fr):")
        if not ok2 or not lang: return
        
        new_model = {"label": label, "path": path, "lang": lang.lower().strip()}
        self.config["audio"].setdefault("models", []).append(new_model)
        self.config["audio"]["selected_model_path"] = path
        self._save()
        self._populate_models_combo()
        self.model_changed.emit()

    def _on_del_model_clicked(self):
        path = self.combo_models.currentData()
        if not path: return
        
        reply = QMessageBox.question(self, "Excluir", "Deseja remover este modelo da lista?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            models = self.config["audio"].get("models", [])
            self.config["audio"]["models"] = [m for m in models if m["path"] != path]
            self.config["audio"]["selected_model_path"] = ""
            self._save()
            self._populate_models_combo()
            self.model_changed.emit()

    def _get_current_source_lang(self):
        # Descobre qual idioma estamos falando baseado no modelo Vosk selecionado
        current_path = self.config["audio"]["selected_model_path"]
        for m in self.config["audio"].get("models", []):
            if m["path"] == current_path: return m["lang"]
        return "pt" # Fallback

    def _on_target_lang_changed(self):
        to_code = self.combo_target.currentData()
        from_code = self._get_current_source_lang()
        
        if from_code == to_code:
            self.config["audio"]["target_lang"] = to_code; self._save()
            return
            
        # Verifica se já temos esse pacote
        installed = argostranslate.package.get_installed_packages()
        if any(p.from_code == from_code and p.to_code == to_code for p in installed):
            self.config["audio"]["target_lang"] = to_code; self._save()
            return

        # Guarda-costas entra em ação!
        if not self._available_packages:
            QMessageBox.warning(self, "Aguarde", "O aplicativo ainda está conectando aos servidores. Tente novamente em 2 segundos.")
            return

        # Reverte a seleção visualmente para não ficar errada enquanto baixa
        self.combo_target.blockSignals(True)
        self.combo_target.setCurrentIndex(max(self.combo_target.findData(self.config["audio"]["target_lang"]), 0))
        self.combo_target.blockSignals(False)

        self._progress = QProgressDialog(f"Baixando Inteligência de Tradução ({from_code.upper()} -> {to_code.upper()})...\nIsso ocorre apenas uma vez.", "Cancelar", 0, 0, self)
        self._progress.setWindowTitle("Instalando Idioma")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.show()

        self.install_thread = PackageInstallThread(from_code, to_code, self._available_packages)
        self.install_thread.finished_ok.connect(lambda code: self._on_package_installed(code))
        self.install_thread.failed.connect(lambda err: self._on_package_failed(err))
        self.install_thread.start()

    def _on_package_installed(self, to_code):
        self._progress.close()
        self.combo_target.blockSignals(True)
        self.combo_target.setCurrentIndex(max(self.combo_target.findData(to_code), 0))
        self.combo_target.blockSignals(False)
        self.config["audio"]["target_lang"] = to_code
        self._save()
        QMessageBox.information(self, "Sucesso", "Idioma instalado! Agora funcionará 100% offline.")

    def _on_package_failed(self, error_msg):
        self._progress.close()
        QMessageBox.warning(self, "Falha na instalação", error_msg)

    def _save(self):
        save_config(self.config)
        self.config_updated.emit()

    def closeEvent(self, event):
        if self.config.get("close_behavior") == "quit":
            event.accept(); QApplication.instance().quit()
        else:
            event.ignore(); self.hide()


# ==========================================
# INICIALIZAÇÃO PRINCIPAL
# ==========================================
if __name__ == '__main__':
    import fcntl
    from PyQt5.QtWidgets import QMessageBox
    
    # CADEADO BLINDADO PARA LINUX (À prova de crashes)
    lock_file_path = os.path.expanduser("~/.config/baseus_pointer.lock")
    lock_fd = open(lock_file_path, 'w')
    try:
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        app = QApplication(sys.argv)
        QMessageBox.warning(None, "Aviso", "O Baseus Presenter já está rodando! Procure o ícone vermelho perto do relógio.")
        sys.exit(0)
        
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) 
    
    config = load_config()
    
    pointer_window = PointerWindow(config)
    settings_window = MainWindow(config)
    settings_window.config_updated.connect(pointer_window.update)
    
    # Faz a janela abrir direto ao iniciar o app!
    settings_window.show()
    settings_window.activateWindow()
    
    pixmap = QPixmap(32, 32); pixmap.fill(Qt.transparent); p = QPainter(pixmap)
    p.setBrush(QColor(255, 0, 0)); p.setPen(Qt.NoPen); p.drawEllipse(4, 4, 24, 24); p.end()
    tray = QSystemTrayIcon(QIcon(pixmap), app)
    
    menu = QMenu()
    action_settings = QAction("⚙️ Abrir Configurações", app)
    action_settings.triggered.connect(lambda: (settings_window.show(), settings_window.activateWindow(), settings_window.raise_()))
    action_battery = QAction("🔋 Bateria: Lendo...", app); action_battery.setEnabled(False)
    action_quit = QAction("❌ Sair do Baseus", app)
    action_quit.triggered.connect(app.quit)
    
    menu.addAction(action_settings); menu.addSeparator(); menu.addAction(action_battery); menu.addAction(action_quit)
    tray.setContextMenu(menu); tray.show()
    
    audio_thread = AudioThread(config)
    audio_thread.start()
    
    # Recarrega a IA sem fechar o app se o usuário trocar a pasta do modelo!
    settings_window.model_changed.connect(audio_thread.load_active_model)
    
    reader = USBReader()
    reader.pointer_active.connect(pointer_window.set_active)
    reader.toggle_mode.connect(pointer_window.switch_mode)
    reader.trigger_click.connect(pointer_window.do_click)
    reader.battery_update.connect(action_battery.setText)
    reader.pen_active.connect(pointer_window.set_pen_active)
    reader.pen_clear.connect(pointer_window.clear_pen)
    reader.black_screen_toggle.connect(pointer_window.toggle_black_screen)
    reader.record_toggled.connect(pointer_window.set_recording)
    reader.translate_toggled.connect(pointer_window.set_translating)
    
    def sync_audio_state():
        # Se tentou ligar, mas o modelo não está carregado
        if (pointer_window.is_recording or pointer_window.is_translating) and not audio_thread.model_loaded:
            pointer_window.set_final_subtitle("⚠️ ERRO: Modelo de Voz não configurado nas Configurações!")
            pointer_window.set_recording(False)
            pointer_window.set_translating(False)
            return
            
        audio_thread.is_listening = pointer_window.is_recording or pointer_window.is_translating
    
    def handle_partial(text):
        if pointer_window.is_translating: pointer_window.set_partial_subtitle(text)
            
    def handle_final(text):
        if pointer_window.is_recording:
            file_path = os.path.join(config["save_dir"], "aula_de_hoje.txt")
            with open(file_path, 'a', encoding='utf-8') as f: f.write(text + "\n")
        
        if pointer_window.is_translating:
            # Puxa dinamicamente qual o idioma do modelo Vosk ativo no momento
            source = "pt"
            for m in config["audio"].get("models", []):
                if m["path"] == config["audio"]["selected_model_path"]: source = m["lang"]
                
            target = config["audio"]["target_lang"]
            
            # Só tenta traduzir se não for o mesmo idioma
            if source != target:
                try:
                    translated = argostranslate.translate.translate(text, source, target)
                    pointer_window.set_final_subtitle(translated)
                except Exception:
                    pointer_window.set_final_subtitle(text) # Se falhar, mostra o original
            else:
                pointer_window.set_final_subtitle(text)

    audio_thread.partial_ready.connect(handle_partial)
    audio_thread.final_ready.connect(handle_final)
    
    reader.start()
    print("🚀 BASEUS SUPREMO v1.1 RODANDO! (Verifique o ícone vermelho perto do relógio)")
    sys.exit(app.exec_())
