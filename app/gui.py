# ~/Documentos/Projetos/baseus-presenter-linux/app/gui.py
import os
import re
import copy
import contextlib
import socket
import threading
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QSlider, QComboBox, QPushButton, QSystemTrayIcon, QMenu,
                             qApp, QTabWidget, QColorDialog, QFileDialog, QFormLayout, QInputDialog, QMessageBox, QCheckBox, QProgressDialog, QStyle)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QColor, QIcon, QPixmap, QPainter, QPen
import sounddevice as sd

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_GUI_AVAILABLE = True
except ImportError:
    ARGOS_GUI_AVAILABLE = False

from .logger import get_logger
from .config import Config

log = get_logger(__name__)

SAVE_DEBOUNCE_MS = 400

# Sentinela para distinguir "ainda não carregado" de "microfone padrão do
# sistema" (que é representado por None no combo_mic).
_UNSET = object()

# #25: timeouts para as operações de rede do Argos. A biblioteca usa urllib
# internamente e NÃO expõe parâmetro de timeout, então o único ponto de
# controle é o default de socket. Sem isto, uma conexão que "pendura"
# (servidor aceita o TCP mas nunca responde) deixa a thread viva
# indefinidamente — e o stop_threads() do encerramento acaba tendo de
# recorrer a terminate().
ARGOS_INDEX_TIMEOUT_S = 15      # listar/atualizar o índice de pacotes
ARGOS_DOWNLOAD_TIMEOUT_S = 120  # baixar o pacote (~30MB)


_socket_timeout_lock = threading.RLock()


@contextlib.contextmanager
def socket_timeout(seconds):
    """
    Aplica um timeout de socket ao redor de uma operação de rede.

    ATENÇÃO: setdefaulttimeout é GLOBAL do processo. Isso só é aceitável
    aqui porque o Argos é a única origem de I/O de rede do aplicativo e
    porque essas chamadas são serializadas (um download por vez, garantido
    por check_and_download_lang). O valor anterior é sempre restaurado.
    """
    with _socket_timeout_lock:
        anterior = socket.getdefaulttimeout()
        socket.setdefaulttimeout(seconds)
        try:
            yield
        finally:
            socket.setdefaulttimeout(anterior)


class LanguageLoadThread(QThread):
    """
    Carrega o índice de idiomas do Argos FORA da thread da GUI.

    populate_languages() rodava síncrono no __init__ da MainWindow. Como
    get_available_packages() faz I/O de rede/disco, a janela congelava até o
    timeout quando não havia internet — sem qualquer feedback ao usuário.
    """
    loaded = pyqtSignal(list)   # [(nome_exibido, codigo), ...]
    failed = pyqtSignal(str)

    def run(self):
        try:
            # #25: sem timeout, esta thread podia ficar pendurada para
            # sempre numa conexão lenta/travada, sobrevivendo ao
            # encerramento do app.
            with socket_timeout(ARGOS_INDEX_TIMEOUT_S):
                pacotes = argostranslate.package.get_available_packages()
            idiomas = [(p.to_name, p.to_code) for p in pacotes if p.from_code == "pt"]
            self.loaded.emit(idiomas)
        except Exception as e:
            log.exception(f"Erro ao carregar idiomas do Argos: {e}")
            self.failed.emit(str(e))


class PackageInstallThread(QThread):
    finished = pyqtSignal(bool, str)
    def __init__(self, from_code, to_code):
        super().__init__()
        self.from_code = from_code
        self.to_code = to_code

    def run(self):
        try:
            # #25: `update_package_index()` e `download()` fazem I/O de rede
            # sem timeout próprio. Um servidor que aceita a conexão mas
            # nunca responde mantinha esta thread viva indefinidamente,
            # forçando o terminate() no encerramento do app.
            with socket_timeout(ARGOS_INDEX_TIMEOUT_S):
                argostranslate.package.update_package_index()
                available = argostranslate.package.get_available_packages()

            pkg = next((p for p in available if p.from_code == self.from_code and p.to_code == self.to_code), None)
            if not pkg:
                self.finished.emit(False, "Pacote não encontrado no servidor.")
                return

            # Timeout mais generoso: aqui são ~30MB. O timeout do socket é
            # por operação de leitura, não para o download inteiro, então
            # ele interrompe um servidor travado sem abortar um download
            # legítimo porém lento.
            with socket_timeout(ARGOS_DOWNLOAD_TIMEOUT_S):
                path = pkg.download()

            argostranslate.package.install_from_path(path)
            self.finished.emit(True, "Instalação concluída!")
        except socket.timeout:
            log.error("Timeout de rede ao baixar o pacote de idioma do Argos.")
            self.finished.emit(
                False, "Tempo de conexão esgotado. Verifique sua internet e tente de novo.")
        except Exception as e:
            log.exception(f"Falha na instalação do pacote de idioma: {e}")
            self.finished.emit(False, str(e))


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
        # Mesmo padrão de overlay.py/audio.py: aceita tanto o dict cru quanto
        # o wrapper já embrulhado, para não depender de quem instancia primeiro.
        self.config = config if isinstance(config, Config) else Config(config)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_now)
        self.setWindowTitle("Baseus Presenter - Configurações (v2.0)")
        self.setWindowIcon(QIcon.fromTheme("input-mouse"))
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

        # 🔋 O Visor de Bateria
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
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    self.combo_mic.addItem(f"{idx} - {dev['name']}", (idx, dev['name']))
        except Exception as exc:
            log.warning(f"Não foi possível listar microfones: {exc}")
        self.combo_mic.currentIndexChanged.connect(self.save_settings)

        box_modelos = QHBoxLayout()
        self.combo_models = QComboBox()
        self.combo_models.currentIndexChanged.connect(self.save_settings)

        btn_add = QPushButton("Adicionar"); btn_add.clicked.connect(self.add_model)
        btn_del = QPushButton("Remover"); btn_del.clicked.connect(self.delete_model)
        box_modelos.addWidget(self.combo_models); box_modelos.addWidget(btn_add); box_modelos.addWidget(btn_del)
        # Guarda o path selecionado para só emitir model_changed quando o
        # modelo REALMENTE mudar (evita reload do Vosk ao trocar outro campo
        # qualquer que também dispare save_settings indiretamente). Setado de
        # verdade em _load_profile_into_widgets(), chamado logo abaixo.
        self._last_model_path = None

        row_txt = QHBoxLayout()
        self.lbl_txt_path = QLabel(self.config.get("save_dir", os.path.expanduser("~")))
        btn_txt = QPushButton("Alterar Destino")
        btn_txt.clicked.connect(self.pick_txt_dir)
        row_txt.addWidget(self.lbl_txt_path); row_txt.addWidget(btn_txt)

        self.combo_lang = QComboBox()
        self.populate_languages()
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

        self.btn_check_update = QPushButton("Verificar Atualizações")
        self.btn_check_update.clicked.connect(self.manual_update_requested.emit)

        form_geral.addRow("Ao clicar no X da janela:", self.combo_close)
        form_geral.addRow("Visual:", self.check_legenda)
        form_geral.addRow("Software:", self.btn_check_update)
        tabs.addTab(tab_geral, "Geral")

        # Injeção inicial dos dados na tela
        self.populate_profiles_combo()
        self._load_profile_into_widgets()

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
        self.lbl_battery.setText(f" Bateria: {percent}%")

    # --- CONTROLES DE ATUALIZAÇÃO ---
    def set_update_checking_state(self, is_checking):
        self.btn_check_update.setEnabled(not is_checking)
        self.btn_check_update.setText("Buscando no GitHub..." if is_checking else "Verificar Atualizações")

    def prompt_update(self, version):
        reply = QMessageBox.question(
            self,
            "Atualização Disponível",
            f"A versão {version} do Baseus Presenter foi lançada.\n\nDeseja fechar o aplicativo e atualizar agora?",
            QMessageBox.Yes | QMessageBox.No
        )
        return reply == QMessageBox.Yes

    def show_up_to_date(self):
        QMessageBox.information(self, "Atualização", "Você já está rodando a versão mais recente.")

    def show_update_error(self, error):
        QMessageBox.warning(self, "Erro de Conexão", f"Não foi possível consultar o GitHub:\n\n{error}")

    # ==========================================
    # LÓGICA DE PERFIS (A MÁGICA)
    # ==========================================
    def populate_profiles_combo(self):
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        self.combo_profiles.addItems(list(self.config.get("profiles", {}).keys()))
        self.combo_profiles.setCurrentText(self.config.get("active_profile", "Padrão"))
        self.combo_profiles.blockSignals(False)

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
        nome, ok = QInputDialog.getText(self, "Novo Perfil", "Nome do novo perfil (ex: Aula IFMG):")
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
            QMessageBox.warning(self, "Erro", "Já existe um perfil com esse nome.")
            return

        self._save_now()
        self.populate_profiles_combo()
        self._load_profile_into_widgets()
        self.model_changed.emit()
        self.config_updated.emit()

    def delete_profile(self):
        current = self.config.get("active_profile")

        if len(self.config.get("profiles", {})) <= 1:
            QMessageBox.warning(self, "Aviso", "Você não pode excluir o único perfil existente.")
            return

        reply = QMessageBox.question(self, "Excluir", f"Excluir o perfil '{current}'?", QMessageBox.Yes | QMessageBox.No)
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
            self.spotlight_slider.blockSignals(block); self.spotlight_opacity.blockSignals(block)
            self.combo_lang.blockSignals(block); self.combo_mic.blockSignals(block)
            self.combo_models.blockSignals(block); self.check_legenda.blockSignals(block)
            self.combo_close.blockSignals(block)

        self._loading_widgets = True
        block_all(True)

        self.laser_slider.setValue(p["visual"].get("laser_size", 30))
        self.lupa_slider.setValue(p["visual"].get("lupa_size", 250))
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
            self.combo_models.addItem(saved_path or "Nenhum modelo selecionado", saved_path)
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
        self.config_updated.emit()

        # save_settings() é chamado por QUALQUER slider/combo (laser, spotlight,
        # idioma...), não só pelo combo de modelo. Sem essa checagem, trocar o
        # tamanho do laser também dispararia um reload desnecessário do Vosk.
        if model_path_changed:
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
        btn.setStyleSheet(f"background-color: {color_hex}; color: white; font-weight: bold; border: 1px solid black;")

    def pick_color(self, config_key, btn):
        cor_atual = QColor(self.config.get_visual(config_key, "#FF0000"))
        cor_escolhida = QColorDialog.getColor(cor_atual, self, "Escolha a cor")
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
            self.combo_models.addItem("Nenhum modelo configurado")
        else:
            for m in models:
                self.combo_models.addItem(m.get("label", "Modelo"), m.get("path"))

    def add_model(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Selecione a pasta do Vosk")
        if diretorio:
            nome, ok = QInputDialog.getText(self, "Nome", "Dê um nome (ex: Vosk PT-BR):")
            if ok and nome:
                with self.config.mutate() as data:
                    models = data.setdefault("models", [])
                    models.append({"label": nome, "path": diretorio})
                    active = data["active_profile"]
                    data["profiles"][active]["audio"]["selected_model_path"] = diretorio

                self._save_now()
                self._load_profile_into_widgets()
                self.model_changed.emit()
                self.config_updated.emit()

    def delete_model(self):
        path = self.combo_models.currentData()
        if not path:
            return

        model_label = None
        with self.config.mutate() as data:
            models = data.get("models", [])
            model = next((m for m in models if m.get("path") == path), None)
            if model:
                model_label = model.get("label")

        if not model:
            return

        reply = QMessageBox.question(self, "Remover Modelo", f"Remover '{model_label}'?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        with self.config.mutate() as data:
            models = data.get("models", [])
            data["models"] = [m for m in models if m.get("path") != path]
            for p_data in data["profiles"].values():
                if p_data["audio"].get("selected_model_path") == path:
                    p_data["audio"]["selected_model_path"] = ""

        self._save_now()
        self._load_profile_into_widgets()
        self.model_changed.emit()
        self.config_updated.emit()

    def pick_txt_dir(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Onde salvar os relatórios (.txt)")
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
            self.combo_lang.addItem("Inglês (Argos não detectado)", "en")
            self.combo_lang.blockSignals(False)
            return

        self.combo_lang.addItem("Carregando idiomas...", None)
        self.combo_lang.blockSignals(False)

        self._lang_loader = LanguageLoadThread(self)
        self._lang_loader.loaded.connect(self._on_languages_loaded)
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
            self.combo_lang.addItem("Inglês (nenhum pacote encontrado)", "en")

        # Reaplica o idioma salvo no perfil, agora que a lista existe.
        salvo = self.config.get_audio("target_lang", "en")
        idx = self.combo_lang.findData(salvo)
        if idx < 0:
            self.combo_lang.addItem(salvo, salvo)
            idx = self.combo_lang.count() - 1
        self.combo_lang.setCurrentIndex(idx)
        self.combo_lang.blockSignals(False)

    def _on_languages_failed(self, msg):
        # O fallback mantém o idioma do perfil; salvar outro campo não deve
        # transformar uma falha de rede em mudança permanente de idioma.
        self._on_languages_loaded([])
        log.warning(f"Lista de idiomas indisponível: {msg}")

    def check_and_download_lang(self, index):
        self.save_settings()
        if not ARGOS_GUI_AVAILABLE: return

        # Extrai o "en" ou "es" que escondemos no item
        target_lang = self.combo_lang.itemData(index)
        if not target_lang: return

        # Um download já em andamento não deve ser atropelado: a thread antiga
        # continuaria rodando e escreveria no diálogo de progresso novo.
        if getattr(self, "installer", None) is not None and self.installer.isRunning():
            QMessageBox.information(
                self, "Aguarde",
                "Já existe um download de idioma em andamento. Aguarde a conclusão."
            )
            return

        try:
            installed = argostranslate.translate.get_installed_languages()
            source_lang = self.config.get_audio("source_lang", "pt")
            from_lang = next((l for l in installed if l.code == source_lang), None)
            to_lang = next((l for l in installed if l.code == target_lang), None)
            if from_lang and to_lang and from_lang.get_translation(to_lang):
                return
        except Exception as e:
            log.exception(f"Falha ao consultar idiomas instalados: {e}")
            return

        nome_idioma = self.combo_lang.itemText(index)
        reply = QMessageBox.question(self, "Baixar Idioma", f"O idioma '{nome_idioma}' não está instalado.\nDeseja baixar? (Aprox. 30MB)", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.progress = QProgressDialog("Baixando pacote... Aguarde.", None, 0, 0, self)
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
        if success: QMessageBox.information(self, "Sucesso", "Idioma instalado!")
        else: QMessageBox.warning(self, "Erro", f"Falha no download:\n{msg}")

    def show_warning(self, msg):
        """Slot para avisos de permissão/hardware vindos das threads."""
        log.warning(msg)
        self.lbl_battery.setText(f" {msg}")

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
