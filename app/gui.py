# ~/Documentos/Projetos/baseus-presenter-linux/app/gui.py
import os
import configparser
import re
import copy
import shutil
from pathlib import Path
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QSlider, QComboBox, QPushButton, QSystemTrayIcon, QMenu,
                             qApp, QColorDialog, QFileDialog, QInputDialog, QMessageBox, QCheckBox, QProgressDialog, QStyle)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QProcess, QLocale
from PyQt5.QtGui import QColor, QIcon, QPixmap, QPainter, QPen
import sounddevice as sd


from .logger import get_logger
from .config import Config
from .i18n import tr
from . import models
from .models import LanguageLoadThread, PackageInstallThread, ARGOS_AVAILABLE as ARGOS_GUI_AVAILABLE
from .uninstall import validate_installation, register_desktop

log = get_logger(__name__)

SAVE_DEBOUNCE_MS = 400

# Sentinela para distinguir "ainda não carregado" de "microfone padrão do
# sistema" (que é representado por None no combo_mic).
_UNSET = object()



class MainWindow(QMainWindow):
    config_updated = pyqtSignal()
    model_changed = pyqtSignal()
    input_device_changed = pyqtSignal()
    manual_update_requested = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self._loading_widgets = False
        self._last_input_device = _UNSET
        self.installer = None
        self._lang_loader = None
        self._language_pairs = None
        # Mesmo padrão de overlay.py/audio.py: aceita tanto o dict cru quanto
        # o wrapper já embrulhado, para não depender de quem instancia primeiro.
        self.config = config if isinstance(config, Config) else Config(config)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_now)
        self.setWindowTitle(tr('Baseus Presenter - Configurações (v2.0)'))
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "resources/baseus-presenter.png")))
        self.combo_profiles = QComboBox()
        self.combo_profiles.currentTextChanged.connect(self.change_profile)
        self.lbl_battery = QPushButton(tr(' Bateria: Aguardando...'))
        self._battery_text = self.lbl_battery.text()
        self.lbl_battery.setFlat(True)
        self.laser_slider = QSlider(Qt.Horizontal); self.laser_slider.setRange(10,100)
        self.lupa_slider = QSlider(Qt.Horizontal); self.lupa_slider.setRange(100,500)
        self.combo_lupa_shape = QComboBox()
        self.combo_lupa_shape.addItem(tr('Circular'), 'circular')
        self.combo_lupa_shape.addItem(tr('Quadrada'), 'square')
        self.combo_lupa_shape.currentIndexChanged.connect(self.save_settings)
        self.spotlight_slider = QSlider(Qt.Horizontal); self.spotlight_slider.setRange(100,800)
        self.spotlight_opacity = QSlider(Qt.Horizontal); self.spotlight_opacity.setRange(50,255)
        for slider in (self.laser_slider,self.lupa_slider,self.spotlight_slider,self.spotlight_opacity):
            slider.valueChanged.connect(self.save_settings)
        self.btn_laser_color = QPushButton(tr('Cor do Laser'))
        self.btn_pincel_color = QPushButton(tr('Cor do Pincel'))
        self.btn_laser_color.clicked.connect(lambda:self.pick_color('laser_color',self.btn_laser_color))
        self.btn_pincel_color.clicked.connect(lambda:self.pick_color('pincel_color',self.btn_pincel_color))
        self.combo_mic = QComboBox()
        self.combo_mic.addItem(tr('Padrão do Sistema (Automático)'),None)
        try:
            for index,device in enumerate(sd.query_devices()):
                if device['max_input_channels']>0:
                    self.combo_mic.addItem(f"{index} - {device['name']}",(index,device['name']))
        except Exception as exc:
            log.warning(f"Não foi possível listar microfones: {exc}")
        self.combo_mic.currentIndexChanged.connect(self.save_settings)
        self.combo_models = QComboBox()
        self.combo_models.currentIndexChanged.connect(self.save_settings)
        self._last_model_path = None
        self.lbl_txt_path = QLabel(self.config.get('save_dir',os.path.expanduser('~')))
        self.lbl_txt_path.setWordWrap(True)
        self.combo_lang = QComboBox()
        self.populate_languages()
        self.combo_lang.currentIndexChanged.connect(self.check_and_download_lang)
        self.combo_ui_language = QComboBox()
        for label,code in ((tr('Automático — idioma do sistema'),'auto'),('Português','pt'),('English','en')):
            self.combo_ui_language.addItem(label,code)
        selected = self.combo_ui_language.findData(self.config.get('ui_language','auto'))
        self.combo_ui_language.setCurrentIndex(max(0,selected))
        self.combo_ui_language.currentIndexChanged.connect(self.save_ui_language)
        self.combo_close = QComboBox()
        self.combo_close.addItems([tr('Minimizar para a Bandeja (Segundo Plano)'),tr('Sair do Aplicativo completamente')])
        self.combo_close.currentIndexChanged.connect(self.save_settings)
        self.check_legenda = QCheckBox(tr('Exibir legendas ao gravar'))
        self.check_legenda.toggled.connect(self.save_settings)
        self.btn_check_update = QPushButton(tr('Verificar Atualizações'))
        self.btn_check_update.clicked.connect(self.manual_update_requested.emit)
        self.btn_uninstall = QPushButton(tr('Desinstalar Baseus Presenter…'))
        self.btn_uninstall.clicked.connect(self.request_uninstall)
        try:
            validate_installation(Path(__file__).resolve().parents[1])
        except (OSError,ValueError):
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip(tr('Disponível apenas na versão instalada, fora de um checkout Git.'))
        from .gui_layout import build_layout
        build_layout(self)
        self.populate_profiles_combo()
        self._load_profile_into_widgets()

    def refresh_visual_preview(self):
        self.effects_canvas.settings = {
            'laser_size':self.laser_slider.value(),
            'lupa_size':self.lupa_slider.value(),
            'lupa_shape':self.combo_lupa_shape.currentData() or self.config.get_visual('lupa_shape','circular'),
            'spotlight_size':self.spotlight_slider.value(),
            'spotlight_opacity':self.spotlight_opacity.value(),
            'laser_color':self.config.get_visual('laser_color','#FF0000'),
            'pincel_color':self.config.get_visual('pincel_color','#FF0000'),
        }
        for key,(label,name) in self.effect_value_labels.items():
            value=self.effects_canvas.settings[key]
            suffix=f'{round(value/255*100)}%' if key=='spotlight_opacity' else f'{value} px'
            label.setText(name+'   '+suffix)
        self.effects_canvas.update()

    def refresh_model_language(self):
        model=models.find_model(self.config,self.combo_models.currentData())
        self.lbl_model_language.setText(tr('Idioma de origem: {0}',model.get('language') or tr('Não definido')))

    def save_ui_language(self):
        self.config.set("ui_language", self.combo_ui_language.currentData())
        self._save_now()

    def update_battery(self, msg):
        match = re.search(r'(\d+)', msg)
        percent = int(match.group(1)) if match else 0

        pixmap = QPixmap(28, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(QPen(QColor("#4a90e2"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, 22, 12, 2, 2)
        painter.drawRect(24, 4, 2, 6)

        fill_width = int(20 * (percent / 100))
        cor = QColor(0, 200, 0) if percent > 20 else QColor(220, 50, 50)
        painter.setBrush(cor)
        painter.setPen(Qt.NoPen)
        if fill_width > 0:
            painter.drawRect(2, 2, fill_width, 10)

        painter.end()

        self.lbl_battery.setIcon(QIcon(pixmap))
        self.lbl_battery.setIconSize(pixmap.size())
        self._battery_text = tr(' Bateria: {0}%', percent)
        self.lbl_battery.setText(self._battery_text)

    # --- CONTROLES DE ATUALIZAÇÃO ---
    def set_update_checking_state(self, is_checking):
        self.btn_check_update.setEnabled(not is_checking)
        self.btn_check_update.setText(tr('Buscando no GitHub...') if is_checking else tr('Verificar Atualizações'))

    def prompt_update(self, version):
        entry = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart/baseus-presenter.desktop"
        enabled = entry.is_file()
        if enabled:
            settings = configparser.ConfigParser(interpolation=None)
            try:
                settings.read(entry, encoding="utf-8")
                enabled = (not settings.getboolean("Desktop Entry", "Hidden", fallback=False)
                           and settings.getboolean("Desktop Entry", "X-GNOME-Autostart-enabled", fallback=True))
            except (OSError, ValueError, configparser.Error):
                enabled = False
        box = QMessageBox(self)
        box.setWindowTitle(tr('Atualização Disponível'))
        box.setText(tr('A versão {0} do Baseus Presenter foi lançada.\n\nDeseja fechar o aplicativo e atualizar agora?', version))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText(tr('Atualizar'))
        box.button(QMessageBox.No).setText(tr('Cancelar'))
        box.setDefaultButton(QMessageBox.No)
        checkbox = QCheckBox(tr('Iniciar o Baseus Presenter automaticamente ao entrar no sistema'), box)
        checkbox.setChecked(enabled)
        box.setCheckBox(checkbox)
        reply = box.exec_()
        return reply == QMessageBox.Yes, checkbox.isChecked()

    def show_up_to_date(self):
        QMessageBox.information(self, tr('Atualização'), tr('Você já está rodando a versão mais recente.'))

    def show_update_error(self, error):
        QMessageBox.warning(self, tr('Erro de Conexão'), tr('Não foi possível consultar o GitHub:\n\n{0}', error))

    # ==========================================
    # LÓGICA DE PERFIS (A MÁGICA)
    # ==========================================
    def populate_profiles_combo(self):
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        self.combo_profiles.addItems(list(self.config.get("profiles", {}).keys()))
        self.combo_profiles.setCurrentText(self.config.get("active_profile", "Padrão"))
        self.combo_profiles.blockSignals(False)
        self.btn_delete_profile.setEnabled(self.combo_profiles.count()>1)

    def change_profile(self, profile_name):
        with self.config.mutate() as data:
            valid = profile_name and profile_name in data["profiles"]
            if valid:
                data["active_profile"] = profile_name

        if not valid:
            return

        self._load_profile_into_widgets()

        # Sem isso, a troca de perfil só existia em memória: fechar o app
        # sem tocar em nenhum slider fazia o active_profile voltar ao
        # valor antigo no próximo boot, porque nunca era salvo em disco.
        self._save_now()

        self.model_changed.emit()
        self.config_updated.emit()

    def new_profile(self):
        nome, ok = QInputDialog.getText(self, tr('Novo Perfil'), tr('Nome do novo perfil (ex: Aula IFMG):'))
        if not (ok and nome):
            return

        with self.config.mutate() as data:
            if nome in data["profiles"]:
                already_exists = True
            else:
                already_exists = False
                current = data["active_profile"]
                data["profiles"][nome] = copy.deepcopy(data["profiles"][current])
                data["active_profile"] = nome

        if already_exists:
            QMessageBox.warning(self, tr('Erro'), tr('Já existe um perfil com esse nome.'))
            return

        self._save_now()
        self.populate_profiles_combo()
        self._load_profile_into_widgets()
        self.model_changed.emit()
        self.config_updated.emit()

    def delete_profile(self):
        current = self.config.get("active_profile")

        if len(self.config.get("profiles", {})) <= 1:
            QMessageBox.warning(self, tr('Aviso'), tr('Você não pode excluir o único perfil existente.'))
            return

        reply = QMessageBox.question(self, tr('Excluir'), tr("Excluir o perfil '{0}'?", current), QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        with self.config.mutate() as data:
            del data["profiles"][current]
            data["active_profile"] = list(data["profiles"].keys())[0]

        self._save_now()
        self.populate_profiles_combo()
        self._load_profile_into_widgets()
        self.model_changed.emit()
        self.config_updated.emit()

    def _load_profile_into_widgets(self):
        # Snapshot único e consistente do perfil ativo — evita 10+ chamadas
        # de get_audio/get_visual (cada uma com lock + deepcopy próprios)
        # para montar uma única tela.
        snap = self.config.snapshot()
        active = snap["active_profile"]
        p = snap["profiles"][active]

        def block_all(block):
            self.laser_slider.blockSignals(block); self.lupa_slider.blockSignals(block)
            self.combo_lupa_shape.blockSignals(block)
            self.spotlight_slider.blockSignals(block); self.spotlight_opacity.blockSignals(block)
            self.combo_lang.blockSignals(block); self.combo_mic.blockSignals(block)
            self.combo_models.blockSignals(block); self.check_legenda.blockSignals(block)
            self.combo_close.blockSignals(block)

        self._loading_widgets = True
        block_all(True)

        self.laser_slider.setValue(p["visual"].get("laser_size", 30))
        self.lupa_slider.setValue(p["visual"].get("lupa_size", 250))
        shape = p["visual"].get("lupa_shape", "circular")
        idx_shape = self.combo_lupa_shape.findData(shape)
        self.combo_lupa_shape.setCurrentIndex(max(0, idx_shape))
        self.spotlight_slider.setValue(p["visual"].get("spotlight_size", 300))
        self.spotlight_opacity.setValue(p["visual"].get("spotlight_opacity", 160))
        self.set_btn_color(self.btn_laser_color, p["visual"].get("laser_color", "#FF0000"))
        self.set_btn_color(self.btn_pincel_color, p["visual"].get("pincel_color", "#FF0000"))

        lang = p["audio"].get("target_lang", "en")
        idx_lang = self.combo_lang.findData(lang)
        if idx_lang < 0:
            self.combo_lang.addItem(lang, lang)
            idx_lang = self.combo_lang.count() - 1
        self.combo_lang.setCurrentIndex(idx_lang)

        idx_mic = self._find_mic_item(
            p["audio"].get("input_device_name"), p["audio"].get("input_device"))
        self.combo_mic.setCurrentIndex(max(0, idx_mic))

        self.refresh_models_combo(models=snap.get("models", []))
        idx_mod = self.combo_models.findData(p["audio"].get("selected_model_path", ""))
        if idx_mod < 0:
            saved_path = p["audio"].get("selected_model_path", "")
            self.combo_models.addItem(saved_path or tr('Nenhum modelo selecionado'), saved_path)
            idx_mod = self.combo_models.count() - 1
        self.combo_models.setCurrentIndex(idx_mod)

        self.check_legenda.setChecked(p["audio"].get("show_subtitles", True))
        self.combo_close.setCurrentIndex(1 if snap.get("close_behavior", "tray") == "quit" else 0)

        block_all(False)
        self._loading_widgets = False
        self._sync_input_device()

        # Baseline para a checagem de "modelo realmente mudou" em save_settings().
        # Atualizado aqui (boot E toda troca de perfil) porque uma troca de
        # perfil já emite model_changed explicitamente em change_profile() —
        # sem isso, o PRÓXIMO save_settings() disparado por qualquer outro
        # widget comparava contra o modelo do perfil anterior e emitia
        # model_changed de novo, à toa.
        self._last_model_path = p["audio"].get("selected_model_path", "")
        self.refresh_visual_preview()
        self.refresh_model_language()
        self._refresh_translation_targets()
        QTimer.singleShot(0, self._ensure_model_language)

    def save_settings(self):
        if self._loading_widgets:
            return
        mic_idx, mic_name = self._mic_item_data(self.combo_mic.currentIndex())
        new_model_path = self.combo_models.currentData() or ""
        model_path_changed = (
            self._last_model_path is not None
            and new_model_path != self._last_model_path
        )

        with self.config.mutate() as data:
            active = data["active_profile"]
            visual = data["profiles"][active]["visual"]
            audio = data["profiles"][active]["audio"]

            visual["laser_size"] = self.laser_slider.value()
            visual["lupa_size"] = self.lupa_slider.value()
            visual["lupa_shape"] = self.combo_lupa_shape.currentData() or "circular"
            visual["spotlight_size"] = self.spotlight_slider.value()
            visual["spotlight_opacity"] = self.spotlight_opacity.value()

            audio["target_lang"] = (self.combo_lang.currentData()
                                    or audio.get("target_lang", "en"))
            audio["input_device"] = mic_idx
            audio["input_device_name"] = mic_name
            audio["selected_model_path"] = new_model_path
            audio["show_subtitles"] = self.check_legenda.isChecked()

            data["close_behavior"] = "quit" if self.combo_close.currentIndex() == 1 else "tray"

        self._sync_input_device()
        self._last_model_path = new_model_path
        self._save_timer.start()
        self.refresh_visual_preview()
        self.config_updated.emit()

        # save_settings() é chamado por QUALQUER slider/combo (laser, spotlight,
        # idioma...), não só pelo combo de modelo. Sem essa checagem, trocar o
        # tamanho do laser também dispararia um reload desnecessário do Vosk.
        if model_path_changed:
            self._ensure_model_language()
            self._refresh_translation_targets()
            self.model_changed.emit()

    def _save_now(self):
        # A gravação imediata inclui todas as mudanças em memória e substitui
        # qualquer gravação agendada, evitando uma segunda escrita redundante.
        self._save_timer.stop()
        self.config.save()

    def flush_pending_save(self):
        if self._save_timer.isActive():
            self._save_now()

    # ==========================================
    # LÓGICAS ANTIGAS (Modelos, Cores e Idiomas)
    # ==========================================
    def _find_mic_item(self, nome_salvo, indice_salvo):
        """
        Localiza o item do combo_mic correspondente ao dispositivo salvo.

        Casa primeiro pelo NOME (estável entre execuções); só recorre ao
        índice se a config for legada (sem nome gravado). Retorna -1 quando
        não encontra.
        """
        if nome_salvo:
            for i in range(self.combo_mic.count()):
                idx, nome = self._mic_item_data(i)
                if nome == nome_salvo:
                    return i
            log.warning(
                f"Microfone salvo ('{nome_salvo}') não está disponível agora; "
                "caindo para o padrão do sistema."
            )
            return 0  # item "Padrão do Sistema"

        if indice_salvo is not None:
            for i in range(self.combo_mic.count()):
                idx, _nome = self._mic_item_data(i)
                if idx == indice_salvo:
                    return i

        return -1

    def _mic_item_data(self, i):
        """
        Normaliza o dado de um item do combo_mic para (indice, nome).

        Tolera o formato ANTIGO (só o índice int), que pode aparecer em itens
        inseridos por código/testes legados — sem isso, um dado int puro
        causava `TypeError: 'int' object is not subscriptable`.
        """
        dado = self.combo_mic.itemData(i)
        if dado is None:
            return None, None
        if isinstance(dado, tuple):
            return dado[0], dado[1]
        return dado, None  # formato legado: apenas o índice

    def _sync_input_device(self):
        """Emite input_device_changed só quando o device realmente mudou."""
        # Compara pelo NOME quando disponível (o índice pode mudar sem o
        # dispositivo mudar); cai para o índice em itens de formato legado.
        idx, nome = self._mic_item_data(self.combo_mic.currentIndex())
        novo_device = nome if nome is not None else idx
        if self._last_input_device is _UNSET:
            self._last_input_device = novo_device
            return  # primeira inicialização: nada para "trocar" ainda
        if novo_device != self._last_input_device:
            self._last_input_device = novo_device
            self.input_device_changed.emit()

    def set_btn_color(self, btn, color_hex):
        btn.setStyleSheet(f"border-left: 8px solid {QColor(color_hex).name()};")
        btn.setToolTip(QColor(color_hex).name())

    def pick_color(self, config_key, btn):
        cor_atual = QColor(self.config.get_visual(config_key, "#FF0000"))
        cor_escolhida = QColorDialog.getColor(cor_atual, self, tr('Escolha a cor'))
        if cor_escolhida.isValid():
            self.config.set_visual(config_key, cor_escolhida.name())
            self.set_btn_color(btn, cor_escolhida.name())
            self.save_settings()

    def refresh_models_combo(self, models=None):
        """
        Repopula o combo de modelos.

        NÃO gerencia blockSignals aqui: blockSignals(bool) é estado absoluto,
        não um contador reentrante. Se este método travasse e destravasse por
        conta própria, ele desbloquearia o combo mesmo quando chamado de
        dentro de _load_profile_into_widgets/block_all(True) — o
        setCurrentIndex() logo em seguida disparava currentIndexChanged e
        vazava save_settings() no meio do carregamento do perfil. Quem chama
        este método é responsável por blockSignals ao redor da chamada.
        """
        if models is None:
            models = self.config.get("models", [])
        self.combo_models.clear()
        if not models:
            self.combo_models.addItem(tr('Nenhum modelo configurado'))
        else:
            for m in models:
                self.combo_models.addItem(m.get("label", tr('Modelo')), m.get("path"))

    def add_model(self):
        diretorio = QFileDialog.getExistingDirectory(self, tr('Selecione a pasta do Vosk'))
        if diretorio:
            nome, ok = QInputDialog.getText(self, tr('Nome'), tr('Dê um nome (ex: Vosk PT-BR):'))
            if ok and nome:
                language = self._ask_model_language(nome)
                if not language:
                    return
                models.add_model(self.config, diretorio, nome, language)

                self._save_now()
                self._load_profile_into_widgets()
                self.model_changed.emit()
                self.config_updated.emit()

    def _ask_model_language(self, label, current=None):
        languages = {}
        for locale in QLocale.matchingLocales(QLocale.AnyLanguage, QLocale.AnyScript, QLocale.AnyCountry):
            code = locale.name().split('_')[0]
            if code != 'C':
                name = QLocale.languageToString(locale.language())
                languages.setdefault(code, f'{name} / {locale.nativeLanguageName()} ({code})')
        items = [tr('Selecione o idioma do modelo')] + sorted(languages.values(), key=str.casefold)
        current_item = languages.get(current)
        index = items.index(current_item) if current_item in items else 0
        value, ok = QInputDialog.getItem(
            self, tr('Idioma do modelo'),
            tr('Idioma falado no modelo "{0}":', label), items, index, False)
        if not ok:
            return None
        match = re.search(r'\(([a-z]{2,3})\)$', value)
        return match.group(1) if match else None

    def _ensure_model_language(self, force=False):
        if getattr(self, '_model_language_prompt_open', False):
            return
        path = self.config.get_audio('selected_model_path')
        if not path:
            return
        model = models.find_model(self.config, path)
        if model.get('language') and not force:
            return
        self._model_language_prompt_open = True
        try:
            language = self._ask_model_language(model.get('label', path), model.get('language'))
        finally:
            self._model_language_prompt_open = False
        if language:
            models.set_model_language(self.config, path, language)
            self._save_now()
            self.config_updated.emit()
        self._refresh_translation_targets()
        self.refresh_model_language()

    def _refresh_translation_targets(self):
        source = self.config.get_audio('source_lang')
        pairs = self._language_pairs or []
        idiomas = sorted({(name, code) for origin, name, code in pairs
                          if origin == source and code != source})
        self._on_languages_loaded(idiomas)
        self.combo_lang.setEnabled(bool(source and idiomas))

    def _on_language_catalog_loaded(self, pairs):
        self._language_pairs = pairs
        self._refresh_translation_targets()

    def delete_model(self):
        path = self.combo_models.currentData()
        if not path:
            return

        model = models.find_model(self.config, path)
        model_label = model.get('label')

        if not model:
            return

        reply = QMessageBox.question(self, tr('Remover Modelo'), tr("Remover '{0}'?", model_label), QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        models.remove_model(self.config, path)

        self._save_now()
        self._load_profile_into_widgets()
        self.model_changed.emit()
        self.config_updated.emit()

    def pick_txt_dir(self):
        diretorio = QFileDialog.getExistingDirectory(self, tr('Onde salvar os relatórios (.txt)'))
        if diretorio:
            self.config.set("save_dir", diretorio)
            self.lbl_txt_path.setText(diretorio)
            self._save_now()

    def populate_languages(self):
        """
        Dispara o carregamento ASSÍNCRONO da lista de idiomas.

        Antes isso era síncrono no __init__ e congelava a janela (I/O de rede).
        """
        self.combo_lang.blockSignals(True)
        self.combo_lang.clear()

        if not ARGOS_GUI_AVAILABLE:
            self.combo_lang.addItem(tr('Inglês (Argos não detectado)'), "en")
            self.combo_lang.blockSignals(False)
            return

        self.combo_lang.addItem(tr('Carregando idiomas...'), None)
        self.combo_lang.blockSignals(False)

        self._lang_loader = LanguageLoadThread(self)
        self._lang_loader.loaded.connect(self._on_language_catalog_loaded)
        self._lang_loader.failed.connect(self._on_languages_failed)
        self._lang_loader.start()

    def _on_languages_loaded(self, idiomas):
        self.combo_lang.blockSignals(True)
        self.combo_lang.clear()
        if idiomas:
            for nome, codigo in idiomas:
                # Tela mostra "English", mas o Python guarda "en"
                self.combo_lang.addItem(nome, codigo)
        else:
            self.combo_lang.addItem(tr('Nenhuma tradução disponível para este modelo'), None)

        # Reaplica o idioma salvo no perfil, agora que a lista existe.
        salvo = self.config.get_audio("target_lang", "en")
        idx = self.combo_lang.findData(salvo)
        if idx < 0:
            self.combo_lang.addItem(tr('{0} (indisponível)', salvo), salvo)
            idx = self.combo_lang.count() - 1
            self.combo_lang.model().item(idx).setEnabled(False)
        self.combo_lang.setCurrentIndex(idx)
        self.combo_lang.blockSignals(False)

    def _on_languages_failed(self, msg):
        # O fallback mantém o idioma do perfil; salvar outro campo não deve
        # transformar uma falha de rede em mudança permanente de idioma.
        self._language_pairs = None
        self._refresh_translation_targets()
        log.warning(f"Lista de idiomas indisponível: {msg}")

    def check_and_download_lang(self, index):
        self.save_settings()
        if not ARGOS_GUI_AVAILABLE: return

        # Extrai o "en" ou "es" que escondemos no item
        target_lang = self.combo_lang.itemData(index)
        if not target_lang: return
        source = self.config.get_audio('source_lang')
        if not source or not any(origin == source and code == target_lang
                                 for origin, _, code in (self._language_pairs or [])):
            return

        # Um download já em andamento não deve ser atropelado: a thread antiga
        # continuaria rodando e escreveria no diálogo de progresso novo.
        if getattr(self, "installer", None) is not None and self.installer.isRunning():
            QMessageBox.information(
                self, tr('Aguarde'),
                tr('Já existe um download de idioma em andamento. Aguarde a conclusão.')
            )
            return

        try:
            if models.has_translation(source, target_lang):
                return
        except Exception as e:
            log.exception(f"Falha ao consultar idiomas instalados: {e}")
            return

        nome_idioma = self.combo_lang.itemText(index)
        reply = QMessageBox.question(self, tr('Baixar Idioma'), tr("O idioma '{0}' não está instalado.\nDeseja baixar? (Aprox. 30MB)", nome_idioma), QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.progress = QProgressDialog(tr('Baixando pacote... Aguarde.'), None, 0, 0, self)
            self.progress.setWindowTitle("Argos")
            self.progress.setModal(True); self.progress.show()
            if self.installer is not None:
                self.installer.deleteLater()
            self.installer = PackageInstallThread(self.config.get_audio("source_lang", "pt"), target_lang)
            self.installer.setParent(self)
            self.installer.finished.connect(self.on_install_finished)

            self.installer.start()

    def on_install_finished(self, success, msg):
        progress = getattr(self, "progress", None)
        if progress is not None:
            progress.close()
            self.progress = None
        if success: QMessageBox.information(self, tr('Sucesso'), tr('Idioma instalado!'))
        else: QMessageBox.warning(self, tr('Erro'), tr('Falha no download:\n{0}', msg))

    def show_warning(self, msg):
        """Slot para avisos de permissão/hardware vindos das threads."""
        log.warning(msg)
        self.lbl_battery.setText(f" {msg}")

    def clear_warning(self, msg):
        if self.lbl_battery.text() == f" {msg}":
            self.lbl_battery.setText(self._battery_text)

    def stop_threads(self):
        """
        #9: as QThreads auxiliares da GUI (download de idioma e carregamento
        do índice do Argos) não participavam da limpeza. Se o app fosse
        encerrado durante um download, o processo saía com a thread viva.
        """
        for nome, thread in (("instalador de idioma", self.installer),
                             ("carregador de idiomas", self._lang_loader)):
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    log.info(f"Aguardando {nome} encerrar...")
                    if not thread.wait(3000):
                        log.error(f"{nome} não encerrou em 3s; forçando terminate().")
                        thread.terminate()
                        thread.wait(1000)
            except RuntimeError:
                # O objeto Qt pode já ter sido destruído por deleteLater.
                pass
        self.installer = None
        self._lang_loader = None

    def request_uninstall(self):
        """Abre o aviso no terminal; o aplicativo só fecha após a confirmação."""
        if getattr(self, "_uninstall_pending", False):
            return
        target = Path(__file__).resolve().parents[1]
        try:
            register_desktop(target)
            terminal = shutil.which("xterm") or shutil.which("x-terminal-emulator")
            if not terminal:
                raise RuntimeError(tr('Nenhum terminal encontrado. Use o atalho Desinstalar Baseus Presenter no menu de aplicativos.'))
            result = QProcess.startDetached(
                terminal, ["-e", "/bin/bash", str(target / "uninstall.sh")], str(target.parent))
            started = result[0] if isinstance(result, tuple) else result
            if not started:
                raise RuntimeError(tr('Não foi possível abrir o terminal de desinstalação.'))
            if isinstance(result, tuple) and result[1] > 0:
                pid = result[1]
                self._uninstall_pending = True
                self.btn_uninstall.setEnabled(False)
                self.btn_uninstall.setText(tr('Desinstalação aberta…'))
                timer = QTimer(self)
                self._uninstall_timer = timer

                def check_terminal():
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        timer.stop()
                        timer.deleteLater()
                        self._uninstall_pending = False
                        self.btn_uninstall.setEnabled(True)
                        self.btn_uninstall.setText(tr('Desinstalar Baseus Presenter…'))
                    except PermissionError:
                        pass

                timer.timeout.connect(check_terminal)
                timer.start(500)
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, tr('Desinstalação'), str(error))

    def closeEvent(self, event):
        self.flush_pending_save()
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
        self.battery_action = menu.addAction(tr('🔋 Bateria: Aguardando passador...'))
        self.battery_action.setEnabled(False)
        menu.addSeparator()

        menu.addAction(tr('Configurações')).triggered.connect(self.main_window.showNormal)
        menu.addAction(tr('Sair')).triggered.connect(qApp.quit)
        self.setContextMenu(menu)
        self.show()

    def update_battery(self, msg):
        self.battery_action.setText(msg)
        self.setToolTip(f"Baseus Presenter - {msg}")
