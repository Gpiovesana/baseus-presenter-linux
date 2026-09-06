# ~/Documentos/Projetos/baseus-presenter-linux/app/gui.py
import os
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QSlider, QComboBox, QPushButton, QSystemTrayIcon, QMenu, 
                             qApp, QTabWidget, QColorDialog, QFileDialog, QFormLayout, QInputDialog, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
import sounddevice as sd

from .logger import get_logger
from .config import save_config

log = get_logger(__name__)

class MainWindow(QMainWindow):
    config_updated = pyqtSignal()
    model_changed = pyqtSignal() # Emite para o AudioThread dar reload

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Baseus Presenter - Configurações")
        self.setMinimumWidth(500)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # --- ABA 1: VISUAL ---
        tab_visual = QWidget()
        form_visual = QFormLayout(tab_visual)

        self.laser_slider = QSlider(Qt.Horizontal); self.laser_slider.setRange(10, 100)
        self.laser_slider.setValue(self.config["visual"].get("laser_size", 30))
        self.laser_slider.valueChanged.connect(self.save_settings)
        
        box_cores = QHBoxLayout()
        self.btn_laser_color = QPushButton("Cor do Laser")
        self.set_btn_color(self.btn_laser_color, self.config["visual"].get("laser_color", "#FF0000"))
        self.btn_laser_color.clicked.connect(lambda: self.pick_color("laser_color", self.btn_laser_color))
        
        self.btn_pincel_color = QPushButton("Cor do Pincel")
        self.set_btn_color(self.btn_pincel_color, self.config["visual"].get("pincel_color", "#FF0000"))
        self.btn_pincel_color.clicked.connect(lambda: self.pick_color("pincel_color", self.btn_pincel_color))
        box_cores.addWidget(self.btn_laser_color); box_cores.addWidget(self.btn_pincel_color)

        self.lupa_slider = QSlider(Qt.Horizontal); self.lupa_slider.setRange(100, 500)
        self.lupa_slider.setValue(self.config["visual"].get("lupa_size", 250))
        self.lupa_slider.valueChanged.connect(self.save_settings)
        
        self.spotlight_slider = QSlider(Qt.Horizontal); self.spotlight_slider.setRange(100, 800)
        self.spotlight_slider.setValue(self.config["visual"].get("spotlight_size", 300))
        self.spotlight_slider.valueChanged.connect(self.save_settings)
        
        self.spotlight_opacity = QSlider(Qt.Horizontal); self.spotlight_opacity.setRange(50, 255)
        self.spotlight_opacity.setValue(self.config["visual"].get("spotlight_opacity", 160))
        self.spotlight_opacity.valueChanged.connect(self.save_settings)

        form_visual.addRow("Tamanho do Laser:", self.laser_slider)
        form_visual.addRow("Cores:", box_cores)
        form_visual.addRow("Tamanho da Lupa:", self.lupa_slider)
        form_visual.addRow("Tamanho/Escuridão Spotlight:", self.spotlight_slider)
        form_visual.addRow("", self.spotlight_opacity)
        tabs.addTab(tab_visual, "Visual e Ponteiro")

        # --- ABA 2: ÁUDIO & I.A. ---
        tab_ia = QWidget()
        form_ia = QFormLayout(tab_ia)
        
        # 1. Seletor de Microfones (Ideia do ChatGPT)
        self.combo_mic = QComboBox()
        self.combo_mic.addItem("Padrão do Sistema (Automático)", None)
        for idx, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0:
                self.combo_mic.addItem(f"{idx} - {dev['name']}", idx)
        
        saved_mic = self.config["audio"].get("input_device")
        if saved_mic is not None:
            idx = self.combo_mic.findData(saved_mic)
            if idx >= 0: self.combo_mic.setCurrentIndex(idx)
        self.combo_mic.currentIndexChanged.connect(self.save_settings)

        # 2. Gerenciador de Modelos (Adicionado o Delete Seguro)
        box_modelos = QHBoxLayout()
        self.combo_models = QComboBox()
        self.refresh_models_combo()
        self.combo_models.currentIndexChanged.connect(self.select_model)
        
        btn_add = QPushButton("Adicionar")
        btn_add.clicked.connect(self.add_model)
        btn_del = QPushButton("Remover")
        btn_del.clicked.connect(self.delete_model)
        
        box_modelos.addWidget(self.combo_models)
        box_modelos.addWidget(btn_add)
        box_modelos.addWidget(btn_del)

        # Pasta TXT
        row_txt = QHBoxLayout()
        self.lbl_txt_path = QLabel(self.config.get("save_dir", os.path.expanduser("~")))
        btn_txt = QPushButton("Alterar Destino")
        btn_txt.clicked.connect(self.pick_txt_dir)
        row_txt.addWidget(self.lbl_txt_path); row_txt.addWidget(btn_txt)

        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["en", "es", "fr", "de"])
        self.combo_lang.setCurrentText(self.config["audio"].get("target_lang", "en"))
        self.combo_lang.currentTextChanged.connect(self.save_settings)

        form_ia.addRow("Microfone:", self.combo_mic)
        form_ia.addRow("Modelo de Voz:", box_modelos)
        form_ia.addRow("Salvar aulas (.txt) em:", row_txt)
        form_ia.addRow("Traduzir para:", self.combo_lang)
        tabs.addTab(tab_ia, "Áudio e I.A.")

    def set_btn_color(self, btn, color_hex):
        btn.setStyleSheet(f"background-color: {color_hex}; color: white; font-weight: bold; border: 1px solid black;")

    def pick_color(self, config_key, btn):
        cor_atual = QColor(self.config["visual"].get(config_key, "#FF0000"))
        cor_escolhida = QColorDialog.getColor(cor_atual, self, "Escolha a cor")
        if cor_escolhida.isValid():
            self.config["visual"][config_key] = cor_escolhida.name()
            self.set_btn_color(btn, cor_escolhida.name())
            self.save_settings()

    def refresh_models_combo(self):
        self.combo_models.blockSignals(True)
        self.combo_models.clear()
        models = self.config["audio"].get("models", [])
        if not models:
            self.combo_models.addItem("Nenhum modelo configurado")
        else:
            for m in models:
                self.combo_models.addItem(m.get("label", "Modelo"), m.get("path"))
            idx = self.combo_models.findData(self.config["audio"].get("selected_model_path", ""))
            if idx >= 0: self.combo_models.setCurrentIndex(idx)
        self.combo_models.blockSignals(False)

    def select_model(self, index):
        path = self.combo_models.itemData(index)
        if path:
            self.config["audio"]["selected_model_path"] = path
            self.save_settings()
            self.model_changed.emit()

    def add_model(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Selecione a pasta do Vosk")
        if diretorio:
            nome, ok = QInputDialog.getText(self, "Nome do Modelo", "Dê um nome (ex: Vosk PT-BR Pequeno):")
            if ok and nome:
                models = self.config["audio"].setdefault("models", [])
                models.append({"label": nome, "path": diretorio})
                self.config["audio"]["selected_model_path"] = diretorio
                self.save_settings()
                self.refresh_models_combo()
                self.model_changed.emit()

    def delete_model(self):
        path = self.combo_models.currentData()
        if not path: return
        models = self.config["audio"].get("models", [])
        model = next((m for m in models if m.get("path") == path), None)
        
        if model:
            reply = QMessageBox.question(self, "Remover Modelo",
                                         f"Remover '{model.get('label')}' do app?\n(Os arquivos NÃO serão apagados do seu HD).",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.config["audio"]["models"] = [m for m in models if m.get("path") != path]
                if self.config["audio"].get("selected_model_path") == path:
                    self.config["audio"]["selected_model_path"] = ""
                self.save_settings()
                self.refresh_models_combo()

    def pick_txt_dir(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Onde salvar os relatórios (.txt)")
        if diretorio:
            self.config["save_dir"] = diretorio
            self.lbl_txt_path.setText(diretorio)
            self.save_settings()

    def save_settings(self):
        self.config["visual"]["laser_size"] = self.laser_slider.value()
        self.config["visual"]["lupa_size"] = self.lupa_slider.value()
        self.config["visual"]["spotlight_size"] = self.spotlight_slider.value()
        self.config["visual"]["spotlight_opacity"] = self.spotlight_opacity.value()
        self.config["audio"]["target_lang"] = self.combo_lang.currentText()
        self.config["audio"]["input_device"] = self.combo_mic.currentData()
        
        save_config(self.config)
        self.config_updated.emit()

    def closeEvent(self, event):
        if self.config.get("close_behavior", "tray") == "tray":
            event.ignore()
            self.hide()
        else:
            event.accept()
            qApp.quit()

class TrayIcon(QSystemTrayIcon):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        menu = QMenu()
        menu.addAction("Configurações").triggered.connect(self.main_window.showNormal)
        menu.addAction("Sair").triggered.connect(qApp.quit)
        self.setContextMenu(menu)
