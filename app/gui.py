# ~/Documentos/Projetos/baseus-presenter-linux/app/gui.py
import os
import re
import copy
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QSlider, QComboBox, QPushButton, QSystemTrayIcon, QMenu, 
                             qApp, QTabWidget, QColorDialog, QFileDialog, QFormLayout, QInputDialog, QMessageBox, QCheckBox, QProgressDialog, QStyle)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QColor,QIcon, QPixmap, QPainter, QPen
import sounddevice as sd

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_GUI_AVAILABLE = True
except ImportError:
    ARGOS_GUI_AVAILABLE = False

from .logger import get_logger
from .config import save_config

log = get_logger(__name__)

class PackageInstallThread(QThread):
    finished = pyqtSignal(bool, str)
    def __init__(self, from_code, to_code):
        super().__init__()
        self.from_code = from_code
        self.to_code = to_code

    def run(self):
        try:
            argostranslate.package.update_package_index()
            available = argostranslate.package.get_available_packages()
            pkg = next((p for p in available if p.from_code == self.from_code and p.to_code == self.to_code), None)
            if not pkg:
                self.finished.emit(False, "Pacote não encontrado no servidor.")
                return
            path = pkg.download()
            argostranslate.package.install_from_path(path)
            self.finished.emit(True, "Instalação concluída!")
        except Exception as e:
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):
    config_updated = pyqtSignal()
    model_changed = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Baseus Presenter - Configurações (v2.0)")
        self.setWindowIcon(QIcon.fromTheme("input-mouse")) # A CORREÇÃO DO CHATGPT
        self.setMinimumWidth(550)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- A BARRA DE PERFIS VIP ---
        row_perfil = QHBoxLayout()
        row_perfil.addWidget(QLabel("<b>Perfil:</b>"))
        
        self.combo_profiles = QComboBox()
        self.combo_profiles.currentTextChanged.connect(self.change_profile)
        
        btn_new_profile = QPushButton("Novo Perfil")
        btn_new_profile.clicked.connect(self.new_profile)
        
        btn_del_profile = QPushButton("Excluir")
        btn_del_profile.clicked.connect(self.delete_profile)
        
        row_perfil.addWidget(self.combo_profiles, stretch=1)
        row_perfil.addWidget(btn_new_profile)
        row_perfil.addWidget(btn_del_profile)
        
        main_layout.addLayout(row_perfil)
        
        line = QWidget(); line.setFixedHeight(1); line.setStyleSheet("background-color: #cccccc; margin-bottom: 5px;")
        main_layout.addWidget(line)

        # 🔋 O Visor de Bateria!
        # Substitui o texto com emoji quebrado por um botão invisível com suporte a ícone
        self.lbl_battery = QPushButton(" Bateria: Aguardando...")
        self.lbl_battery.setFlat(True)
        self.lbl_battery.setStyleSheet("""
            text-align: left; 
            color: #4a90e2; 
            font-weight: bold; 
            border: none;
        """)
        main_layout.addWidget(self.lbl_battery)

        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # --- ABA 1: VISUAL ---
        tab_visual = QWidget()
        form_visual = QFormLayout(tab_visual)

        self.laser_slider = QSlider(Qt.Horizontal); self.laser_slider.setRange(10, 100)
        self.laser_slider.valueChanged.connect(self.save_settings)
        
        box_cores = QHBoxLayout()
        self.btn_laser_color = QPushButton("Cor do Laser")
        self.btn_laser_color.clicked.connect(lambda: self.pick_color("laser_color", self.btn_laser_color))
        
        self.btn_pincel_color = QPushButton("Cor do Pincel")
        self.btn_pincel_color.clicked.connect(lambda: self.pick_color("pincel_color", self.btn_pincel_color))
        box_cores.addWidget(self.btn_laser_color); box_cores.addWidget(self.btn_pincel_color)

        self.lupa_slider = QSlider(Qt.Horizontal); self.lupa_slider.setRange(100, 500)
        self.lupa_slider.valueChanged.connect(self.save_settings)
        
        self.spotlight_slider = QSlider(Qt.Horizontal); self.spotlight_slider.setRange(100, 800)
        self.spotlight_slider.valueChanged.connect(self.save_settings)
        
        self.spotlight_opacity = QSlider(Qt.Horizontal); self.spotlight_opacity.setRange(50, 255)
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
        
        self.combo_mic = QComboBox()
        self.combo_mic.addItem("Padrão do Sistema (Automático)", None)
        for idx, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0:
                self.combo_mic.addItem(f"{idx} - {dev['name']}", idx)
        self.combo_mic.currentIndexChanged.connect(self.save_settings)

        box_modelos = QHBoxLayout()
        self.combo_models = QComboBox()
        self.combo_models.currentIndexChanged.connect(self.save_settings)
        
        btn_add = QPushButton("Adicionar"); btn_add.clicked.connect(self.add_model)
        btn_del = QPushButton("Remover"); btn_del.clicked.connect(self.delete_model)
        box_modelos.addWidget(self.combo_models); box_modelos.addWidget(btn_add); box_modelos.addWidget(btn_del)

        row_txt = QHBoxLayout()
        self.lbl_txt_path = QLabel(self.config.get("save_dir", os.path.expanduser("~")))
        btn_txt = QPushButton("Alterar Destino")
        btn_txt.clicked.connect(self.pick_txt_dir)
        row_txt.addWidget(self.lbl_txt_path); row_txt.addWidget(btn_txt)

        self.combo_lang = QComboBox()
        self.populate_languages() # Puxa a lista dinâmica!
        self.combo_lang.currentIndexChanged.connect(self.check_and_download_lang)

        form_ia.addRow("Microfone:", self.combo_mic)
        form_ia.addRow("Modelo de Voz:", box_modelos)
        form_ia.addRow("Salvar aulas (.txt) em:", row_txt)
        form_ia.addRow("Traduzir para:", self.combo_lang)
        tabs.addTab(tab_ia, "Áudio e I.A.")

        # --- ABA 3: GERAL ---
        tab_geral = QWidget()
        form_geral = QFormLayout(tab_geral)
        
        self.combo_close = QComboBox()
        self.combo_close.addItems(["Minimizar para a Bandeja (Segundo Plano)", "Sair do Aplicativo completamente"])
        self.combo_close.currentIndexChanged.connect(self.save_settings)
        
        self.check_legenda = QCheckBox("Exibir as legendas na tela ao usar o botão 'Gravar'")
        self.check_legenda.toggled.connect(self.save_settings)
        
        form_geral.addRow("Ao clicar no X da janela:", self.combo_close)
        form_geral.addRow("Visual:", self.check_legenda)
        tabs.addTab(tab_geral, "Geral")

        # Injeção inicial dos dados na tela!
        self.populate_profiles_combo()
        self._load_profile_into_widgets()
        
    def update_battery(self, msg):
        # Tenta extrair a porcentagem da mensagem (ex: "100%" vira 100)
        match = re.search(r'(\d+)', msg)
        percent = int(match.group(1)) if match else 0

        # Prepara a tela (pixmap) para desenhar o ícone
        pixmap = QPixmap(28, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Desenha a carcaça da pilha (em azul, combinando com sua fonte)
        painter.setPen(QPen(QColor("#4a90e2"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, 22, 12, 2, 2)
        painter.drawRect(24, 4, 2, 6) # Polo positivo

        # Preenche a bateria (Verde se > 20%, Vermelho se <= 20%)
        fill_width = int(20 * (percent / 100))
        cor = QColor(0, 200, 0) if percent > 20 else QColor(220, 50, 50)
        painter.setBrush(cor)
        painter.setPen(Qt.NoPen)
        if fill_width > 0:
            painter.drawRect(2, 2, fill_width, 10)

        painter.end()

        # Aplica a arte e o texto na tela
        self.lbl_battery.setIcon(QIcon(pixmap))
        self.lbl_battery.setIconSize(pixmap.size())
        self.lbl_battery.setText(f" Bateria: {percent}%")

    # ==========================================
    # LÓGICA DE PERFIS (A MÁGICA)
    # ==========================================
    def populate_profiles_combo(self):
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        self.combo_profiles.addItems(list(self.config["profiles"].keys()))
        self.combo_profiles.setCurrentText(self.config["active_profile"])
        self.combo_profiles.blockSignals(False)

    def change_profile(self, profile_name):
        if profile_name and profile_name in self.config["profiles"]:
            self.config["active_profile"] = profile_name
            self._load_profile_into_widgets()
            
            # Avisa os outros módulos que tudo mudou!
            self.model_changed.emit()
            self.config_updated.emit()

    def new_profile(self):
        nome, ok = QInputDialog.getText(self, "Novo Perfil", "Nome do novo perfil (ex: Aula IFMG):")
        if ok and nome:
            if nome in self.config["profiles"]:
                QMessageBox.warning(self, "Erro", "Já existe um perfil com esse nome.")
                return
            
            # Clona o perfil atual
            current = self.config["active_profile"]
            self.config["profiles"][nome] = copy.deepcopy(self.config["profiles"][current])
            self.config["active_profile"] = nome
            self.save_settings()
            
            self.populate_profiles_combo()
            self._load_profile_into_widgets()
            self.model_changed.emit()
            self.config_updated.emit()

    def delete_profile(self):
        current = self.config["active_profile"]
        if len(self.config["profiles"]) <= 1:
            QMessageBox.warning(self, "Aviso", "Você não pode excluir o único perfil existente.")
            return
            
        reply = QMessageBox.question(self, "Excluir", f"Excluir o perfil '{current}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del self.config["profiles"][current]
            self.config["active_profile"] = list(self.config["profiles"].keys())[0]
            self.save_settings()
            
            self.populate_profiles_combo()
            self._load_profile_into_widgets()
            self.model_changed.emit()
            self.config_updated.emit()

    def _load_profile_into_widgets(self):
        active = self.config["active_profile"]
        p = self.config["profiles"][active]
        
        # O TRUQUE DO ESPELHO: Atualiza a raiz para o Laser/Áudio lerem sem mexer no código deles!
        self.config.setdefault("visual", {}).update(p["visual"])
        self.config.setdefault("audio", {}).update(p["audio"])
        
        def block_all(block):
            self.laser_slider.blockSignals(block); self.lupa_slider.blockSignals(block)
            self.spotlight_slider.blockSignals(block); self.spotlight_opacity.blockSignals(block)
            self.combo_lang.blockSignals(block); self.combo_mic.blockSignals(block)
            self.combo_models.blockSignals(block); self.check_legenda.blockSignals(block)
            self.combo_close.blockSignals(block)

        block_all(True)
        
        self.laser_slider.setValue(p["visual"].get("laser_size", 30))
        self.lupa_slider.setValue(p["visual"].get("lupa_size", 250))
        self.spotlight_slider.setValue(p["visual"].get("spotlight_size", 300))
        self.spotlight_opacity.setValue(p["visual"].get("spotlight_opacity", 160))
        self.set_btn_color(self.btn_laser_color, p["visual"].get("laser_color", "#FF0000"))
        self.set_btn_color(self.btn_pincel_color, p["visual"].get("pincel_color", "#FF0000"))
        
        lang = p["audio"].get("target_lang", "en")
        idx_lang = self.combo_lang.findData(lang)                    # LINHA NOVA 1
        if idx_lang >= 0: self.combo_lang.setCurrentIndex(idx_lang)  # LINHA NOVA 2
        
        mic = p["audio"].get("input_device")
        idx_mic = self.combo_mic.findData(mic)
        if idx_mic >= 0: self.combo_mic.setCurrentIndex(idx_mic)
        
        self.refresh_models_combo()
        idx_mod = self.combo_models.findData(p["audio"].get("selected_model_path", ""))
        if idx_mod >= 0: self.combo_models.setCurrentIndex(idx_mod)
        
        self.check_legenda.setChecked(p["audio"].get("show_subtitles", True))
        self.combo_close.setCurrentIndex(1 if self.config.get("close_behavior", "tray") == "quit" else 0)
        
        block_all(False)

    def save_settings(self):
        # 1. Salva no Espelho Global
        self.config.setdefault("visual", {})["laser_size"] = self.laser_slider.value()
        self.config["visual"]["lupa_size"] = self.lupa_slider.value()
        self.config["visual"]["spotlight_size"] = self.spotlight_slider.value()
        self.config["visual"]["spotlight_opacity"] = self.spotlight_opacity.value()
        
        self.config.setdefault("audio", {})["target_lang"] = self.combo_lang.currentData() or "en"
        self.config.setdefault("audio", {})["show_subtitles"] = self.check_legenda.isChecked()
        self.config["audio"]["input_device"] = self.combo_mic.currentData()
        self.config["audio"]["selected_model_path"] = self.combo_models.currentData() or ""
        self.config["audio"]["show_subtitles"] = self.check_legenda.isChecked()
        self.config["close_behavior"] = "quit" if self.combo_close.currentIndex() == 1 else "tray"
        
        # 2. Clona e salva na Maleta do Perfil Ativo!
        active = self.config["active_profile"]
        self.config["profiles"][active]["visual"] = copy.deepcopy(self.config["visual"])
        self.config["profiles"][active]["audio"] = copy.deepcopy(self.config["audio"])
        
        save_config(self.config)
        self.config_updated.emit()

    # ==========================================
    # LÓGICAS ANTIGAS (Modelos, Cores e Idiomas)
    # ==========================================
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
        models = self.config.get("models", [])
        if not models:
            self.combo_models.addItem("Nenhum modelo configurado")
        else:
            for m in models:
                self.combo_models.addItem(m.get("label", "Modelo"), m.get("path"))
        self.combo_models.blockSignals(False)

    def add_model(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Selecione a pasta do Vosk")
        if diretorio:
            nome, ok = QInputDialog.getText(self, "Nome", "Dê um nome (ex: Vosk PT-BR):")
            if ok and nome:
                models = self.config.setdefault("models", [])
                models.append({"label": nome, "path": diretorio})
                self.config.setdefault("audio", {})["selected_model_path"] = diretorio
                self.save_settings()
                self._load_profile_into_widgets()
                self.model_changed.emit()

    def delete_model(self):
        path = self.combo_models.currentData()
        if not path: return
        models = self.config.get("models", [])
        model = next((m for m in models if m.get("path") == path), None)
        
        if model:
            reply = QMessageBox.question(self, "Remover Modelo", f"Remover '{model.get('label')}'?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.config["models"] = [m for m in models if m.get("path") != path]
                
                # Desvincula de todos os perfis se for deletado globalmente
                for p_name, p_data in self.config["profiles"].items():
                    if p_data["audio"].get("selected_model_path") == path:
                        p_data["audio"]["selected_model_path"] = ""
                
                self.save_settings()
                self._load_profile_into_widgets()
                self.model_changed.emit()

    def pick_txt_dir(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Onde salvar os relatórios (.txt)")
        if diretorio:
            self.config["save_dir"] = diretorio
            self.lbl_txt_path.setText(diretorio)
            self.save_settings()

    def populate_languages(self):
            self.combo_lang.blockSignals(True)
            self.combo_lang.clear()
            
            if not ARGOS_GUI_AVAILABLE:
                self.combo_lang.addItem("Inglês (Argos não detectado)", "en")
            else:
                try:
                    pacotes = argostranslate.package.get_available_packages()
                    for p in pacotes:
                        if p.from_code == "pt":
                            # Tela mostra "English", mas o Python guarda "en"
                            self.combo_lang.addItem(p.to_name, p.to_code)
                except Exception as e:
                    log.error(f"Erro ao carregar idiomas do Argos: {e}")
                    self.combo_lang.addItem("Inglês (Erro ao ler índice)", "en")
                    
            self.combo_lang.blockSignals(False)
    
    def check_and_download_lang(self, index):
        self.save_settings()
        if not ARGOS_GUI_AVAILABLE: return
        
        # Extrai o "en" ou "es" que escondemos no item
        target_lang = self.combo_lang.itemData(index)
        if not target_lang: return
        
        installed = argostranslate.translate.get_installed_languages()
        # (O resto da função continua exatamente igual a partir daqui...)
        from_lang = next((l for l in installed if l.code == "pt"), None)
        to_lang = next((l for l in installed if l.code == target_lang), None)
        
        if from_lang and to_lang and from_lang.get_translation(to_lang): return
            
        nome_idioma = self.combo_lang.itemText(index)
        reply = QMessageBox.question(self, "Baixar Idioma", f"O idioma '{nome_idioma}' não está instalado.\nDeseja baixar? (Aprox. 30MB)", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.progress = QProgressDialog("Baixando pacote... Aguarde.", None, 0, 0, self)
            self.progress.setWindowTitle("Argos")
            self.progress.setModal(True); self.progress.show()
            self.installer = PackageInstallThread("pt", target_lang)
            self.installer.finished.connect(self.on_install_finished)
            self.installer.finished.connect(self.installer.deleteLater)  # Cleanup
            self.installer.start()

    def on_install_finished(self, success, msg):
        self.progress.close()
        if success: QMessageBox.information(self, "Sucesso", "Idioma instalado!")
        else: QMessageBox.warning(self, "Erro", f"Falha no download:\n{msg}")

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
        self.setIcon(QIcon.fromTheme("input-mouse"))
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("Bandeja do sistema indisponível. No Zorin/GNOME, pode ser necessário instalar a extensão 'AppIndicator Support'.")
        menu = QMenu()
        # A bateria fixa no menu sugerida pelos dois IAs!
        self.battery_action = menu.addAction("🔋 Bateria: Aguardando passador...")
        self.battery_action.setEnabled(False) 
        menu.addSeparator()
        
        menu.addAction("Configurações").triggered.connect(self.main_window.showNormal)
        menu.addAction("Sair").triggered.connect(qApp.quit)
        self.setContextMenu(menu)
        self.show()
    
    def update_battery(self, msg):
        self.battery_action.setText(msg)
        self.setToolTip(f"Baseus Presenter - {msg}")