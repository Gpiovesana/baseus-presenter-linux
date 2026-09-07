# ~/Documentos/Projetos/baseus-presenter-linux/app/gui.py
import os
import re
import copy
import socket
import contextlib
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QSlider, QComboBox, QPushButton, QSystemTrayIcon, QMenu, 
                             qApp, QTabWidget, QColorDialog, QFileDialog, QFormLayout, QInputDialog, QMessageBox, QCheckBox, QProgressDialog, QStyle)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer, QSignalBlocker
from PyQt5.QtGui import QColor,QIcon, QPixmap, QPainter, QPen
import sounddevice as sd

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_GUI_AVAILABLE = True
except ImportError:
    ARGOS_GUI_AVAILABLE = False

from .logger import get_logger
from .config import Config, active_profile, DEFAULT_CONFIG

log = get_logger(__name__)

# Intervalo de debounce para persistir configurações em disco.
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


@contextlib.contextmanager
def socket_timeout(seconds):
    """
    Aplica um timeout de socket ao redor de uma operação de rede.

    ATENÇÃO: setdefaulttimeout é GLOBAL do processo. Isso só é aceitável
    aqui porque o Argos é a única origem de I/O de rede do aplicativo e
    porque essas chamadas são serializadas (um download por vez, garantido
    por check_and_download_lang). O valor anterior é sempre restaurado.
    """
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
    # #16: emitido quando o microfone efetivamente muda (seleção manual ou
    # troca de perfil com device diferente). A AudioThread escuta este
    # sinal para fechar/reabrir o RawInputStream com o novo device_id —
    # antes, trocar o microfone na tela não tinha efeito até reiniciar o app.
    input_device_changed = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config if isinstance(config, Config) else Config(config)

        # Debounce: valueChanged dispara a cada unidade de arraste do slider.
        # Antes, arrastar de 30 a 250 fazia ~220 gravações em disco (cada uma
        # com deepcopy + json.dump completo). Agora o disco é tocado uma vez,
        # SAVE_DEBOUNCE_MS após o usuário parar de mexer.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._flush_settings)
        self._loading_widgets = False
        self.installer = None
        self.progress = None
        self._lang_loader = None
        # Rastreia a última seleção efetiva do combo de modelos para só emitir
        # model_changed quando o caminho realmente mudar (não a cada evento
        # de repopulação/seleção redundante do combo).
        self._last_selected_model_path = None
        # Idem para o microfone (#16). Sentinela distinta de None: o valor
        # "Padrão do Sistema" do combo_mic é justamente None, então não dá
        # para usar None como "ainda não inicializado" sem gerar um falso
        # positivo na primeira emissão (antes de existir uma AudioThread
        # para reagir, o que seria inofensivo, mas deixaria o teste/uso
        # ambíguo).
        self._last_input_device = _UNSET

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
        # O dado de cada item guarda (indice, nome). O NOME é o que será
        # persistido: índices do PortAudio não são estáveis entre execuções
        # (mudam quando dispositivos aparecem/desaparecem), e um índice
        # obsoleto apontava silenciosamente para o microfone ERRADO.
        self.combo_mic.addItem("Padrão do Sistema (Automático)", None)
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    self.combo_mic.addItem(f"{idx} - {dev['name']}", (idx, dev['name']))
        except Exception as exc:
            log.error(f"Falha ao listar dispositivos de áudio: {exc}")
        self.combo_mic.currentIndexChanged.connect(self.on_mic_selected)

        box_modelos = QHBoxLayout()
        self.combo_models = QComboBox()
        self.combo_models.currentIndexChanged.connect(self.on_model_selected)
        
        btn_add = QPushButton("Adicionar"); btn_add.clicked.connect(self.add_model)
        btn_del = QPushButton("Remover"); btn_del.clicked.connect(self.delete_model)
        box_modelos.addWidget(self.combo_models); box_modelos.addWidget(btn_add); box_modelos.addWidget(btn_del)

        row_txt = QHBoxLayout()
        self.lbl_txt_path = QLabel(self.config.get("save_dir", os.path.expanduser("~")))
        btn_txt = QPushButton("Alterar Destino")
        btn_txt.clicked.connect(self.pick_txt_dir)
        row_txt.addWidget(self.lbl_txt_path); row_txt.addWidget(btn_txt)

        self.combo_lang = QComboBox()
        self.populate_languages() # Dispara o carregamento assíncrono
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
        with self.config.mutate() as data:
            nomes = list(data["profiles"].keys())
            ativo = data["active_profile"]
        self.combo_profiles.addItems(nomes)
        self.combo_profiles.setCurrentText(ativo)
        self.combo_profiles.blockSignals(False)

    def change_profile(self, profile_name):
        with self.config.mutate() as data:
            existe = bool(profile_name) and profile_name in data["profiles"]
            if existe:
                data["active_profile"] = profile_name
        if existe:
            # #20: persiste active_profile IMEDIATAMENTE. Antes, se o usuário
            # só trocasse de perfil e encerrasse o app sem tocar em nenhum
            # widget, a troca nunca chegava ao disco (nada chamava save())
            # e desaparecia no próximo início.
            self.config.save()
            self._load_profile_into_widgets()
            
            # Avisa os outros módulos que tudo mudou!
            self.model_changed.emit()
            self.config_updated.emit()

    def new_profile(self):
        nome, ok = QInputDialog.getText(self, "Novo Perfil", "Nome do novo perfil (ex: Aula IFMG):")
        if ok and nome:
            nome = nome.strip()
            if not nome:
                QMessageBox.warning(self, "Erro", "O nome do perfil não pode ser vazio.")
                return

            with self.config.mutate() as data:
                if nome in data["profiles"]:
                    duplicado = True
                else:
                    duplicado = False
                    # Clona o perfil atual
                    current = data["active_profile"]
                    data["profiles"][nome] = copy.deepcopy(data["profiles"][current])
                    data["active_profile"] = nome

            if duplicado:
                QMessageBox.warning(self, "Erro", "Já existe um perfil com esse nome.")
                return

            # #1/#2: NUNCA chamar save_settings() (orientado pelos widgets)
            # depois de uma mutação direta do config. Os widgets ainda
            # refletem o perfil ANTERIOR nesse ponto; salvar aqui gravaria o
            # perfil clonado com os valores do perfil de origem só por causa
            # de um evento de sinal fora de ordem. A ordem correta é:
            # persistir os dados que já mutamos, DEPOIS recarregar os widgets.
            self.config.save()
            self.populate_profiles_combo()
            self._load_profile_into_widgets()
            self.model_changed.emit()
            self.config_updated.emit()

    def delete_profile(self):
        with self.config.mutate() as data:
            current = data["active_profile"]
            unico = len(data["profiles"]) <= 1
        if unico:
            QMessageBox.warning(self, "Aviso", "Você não pode excluir o único perfil existente.")
            return
            
        reply = QMessageBox.question(self, "Excluir", f"Excluir o perfil '{current}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            with self.config.mutate() as data:
                data["profiles"].pop(current, None)
                if not data["profiles"]:
                    # Nunca deixe o app sem nenhum perfil.
                    data["profiles"]["Padrão"] = copy.deepcopy(
                        DEFAULT_CONFIG["profiles"]["Padrão"])
                data["active_profile"] = next(iter(data["profiles"]))

            # #1: Excluir um perfil sobrescrevia outro perfil. A ordem antiga
            # chamava save_settings() (que lê os SLIDERS/COMBOS ATUAIS,
            # ainda com os valores do perfil excluído) depois de já ter
            # trocado active_profile para o sobrevivente — persistindo os
            # valores errados por cima dele. Agora só persistimos o que já
            # está correto em memória e SÓ DEPOIS recarregamos os widgets.
            self.config.save()
            self.populate_profiles_combo()
            self._load_profile_into_widgets()
            self.model_changed.emit()
            self.config_updated.emit()

    def _load_profile_into_widgets(self):
        # Antes havia aqui o "truque do espelho", que copiava
        # profiles[ativo]["visual"/"audio"] para a raiz do config. Isso criava
        # duas fontes de verdade e fazia config["audio"] existir só depois da
        # GUI rodar (KeyError na AudioThread). Agora os consumidores leem o
        # perfil ativo direto, via os acessadores de config.py.
        with self.config.mutate() as data:
            p = copy.deepcopy(active_profile(data))

        # Guarda extra: os QSignalBlocker abaixo cobrem os widgets listados,
        # mas esta flag garante que nenhum save_settings disparado
        # indiretamente grave dados incompletos no perfil.
        self._loading_widgets = True

        # #2: Antes, refresh_models_combo() chamava blockSignals(True)/(False)
        # PRÓPRIO no combo_models, dentro do bloco block_all(True)/(False)
        # externo. blockSignals() não é uma pilha — é um booleano simples — e
        # o unblock interno de refresh_models_combo desbloqueava o combo
        # ANTES do restante desta função terminar, expondo uma janela onde
        # selecionar um índice (ex. ao repopular) disparava save_settings()
        # com os OUTROS widgets ainda no valor do perfil anterior.
        # QSignalBlocker restaura o estado anterior ao sair de escopo (em vez
        # de simplesmente desbloquear), então blocos aninhados funcionam
        # corretamente mesmo se uma função interna também usar um.
        blockers = [
            QSignalBlocker(self.laser_slider), QSignalBlocker(self.lupa_slider),
            QSignalBlocker(self.spotlight_slider), QSignalBlocker(self.spotlight_opacity),
            QSignalBlocker(self.combo_lang), QSignalBlocker(self.combo_mic),
            QSignalBlocker(self.combo_models), QSignalBlocker(self.check_legenda),
            QSignalBlocker(self.combo_close),
        ]
        try:
            self.laser_slider.setValue(p["visual"].get("laser_size", 30))
            self.lupa_slider.setValue(p["visual"].get("lupa_size", 250))
            self.spotlight_slider.setValue(p["visual"].get("spotlight_size", 300))
            self.spotlight_opacity.setValue(p["visual"].get("spotlight_opacity", 160))
            self.set_btn_color(self.btn_laser_color, p["visual"].get("laser_color", "#FF0000"))
            self.set_btn_color(self.btn_pincel_color, p["visual"].get("pincel_color", "#FF0000"))

            lang = p["audio"].get("target_lang", "en")
            idx_lang = self.combo_lang.findData(lang)
            if idx_lang >= 0: self.combo_lang.setCurrentIndex(idx_lang)

            # Restaura o microfone casando pelo NOME (estável). O índice
            # salvo serve apenas como fallback para configs legadas, que
            # ainda não tinham 'input_device_name'.
            idx_mic = self._find_mic_item(
                p["audio"].get("input_device_name"),
                p["audio"].get("input_device"),
            )
            if idx_mic >= 0: self.combo_mic.setCurrentIndex(idx_mic)
            # #16: também cobre a troca de PERFIL (não só a seleção manual
            # no combo, que fica bloqueada por QSignalBlocker durante este
            # carregamento). Perfis diferentes podem ter microfones
            # diferentes; sem isto, mudar de perfil não reabria o stream.
            self._sync_input_device()

            self.refresh_models_combo()
            model_path = p["audio"].get("selected_model_path", "")
            idx_mod = self.combo_models.findData(model_path)
            if idx_mod >= 0:
                self.combo_models.setCurrentIndex(idx_mod)
            self._last_selected_model_path = model_path

            self.check_legenda.setChecked(p["audio"].get("show_subtitles", True))
            self.combo_close.setCurrentIndex(1 if self.config.get("close_behavior", "tray") == "quit" else 0)
        finally:
            blockers.clear()  # libera os QSignalBlocker (restaura o estado anterior)
            self._loading_widgets = False

    def save_settings(self, immediate=False):
        """
        Aplica os widgets no config em memória e AGENDA a gravação em disco.

        Escreve direto no perfil ativo — o espelho na raiz do config não existe
        mais. A gravação é debounced porque valueChanged dispara a cada unidade
        de arraste do slider (eram ~220 json.dump por arraste).
        """
        if self._loading_widgets:
            return  # Estamos populando a UI; não é uma edição do usuário.

        with self.config.mutate() as data:
            prof = active_profile(data)
            visual = prof.setdefault("visual", {})
            audio = prof.setdefault("audio", {})

            visual["laser_size"] = self.laser_slider.value()
            visual["lupa_size"] = self.lupa_slider.value()
            visual["spotlight_size"] = self.spotlight_slider.value()
            visual["spotlight_opacity"] = self.spotlight_opacity.value()

            audio["target_lang"] = self.combo_lang.currentData() or "en"
            audio["show_subtitles"] = self.check_legenda.isChecked()
            # Persiste NOME + índice. O nome é a fonte de verdade na hora de
            # reabrir o stream; o índice fica apenas por compatibilidade.
            mic_idx, mic_nome = self._mic_item_data(self.combo_mic.currentIndex())
            audio["input_device"] = mic_idx
            audio["input_device_name"] = mic_nome
            audio["selected_model_path"] = self.combo_models.currentData() or ""

            data["close_behavior"] = "quit" if self.combo_close.currentIndex() == 1 else "tray"

        # Consumidores (overlay) atualizam na hora; só o disco é debounced.
        self.config_updated.emit()

        if immediate:
            self._save_timer.stop()
            self._flush_settings()
        else:
            self._save_timer.start()  # reinicia a contagem a cada alteração

    def _flush_settings(self):
        """Grava de fato em disco (chamado pelo timer de debounce)."""
        self.config.save()

    def flush_pending_save(self):
        """Força a gravação de alterações pendentes (usado no encerramento)."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush_settings()

    # ==========================================
    # LÓGICAS ANTIGAS (Modelos, Cores e Idiomas)
    # ==========================================
    def set_btn_color(self, btn, color_hex):
        btn.setStyleSheet(f"background-color: {color_hex}; color: white; font-weight: bold; border: 1px solid black;")

    def pick_color(self, config_key, btn):
        cor_atual = QColor(self.config.get_visual(config_key, "#FF0000"))
        cor_escolhida = QColorDialog.getColor(cor_atual, self, "Escolha a cor")
        if cor_escolhida.isValid():
            self.config.set_visual(config_key, cor_escolhida.name())
            self.set_btn_color(btn, cor_escolhida.name())
            self.save_settings(immediate=True)

    def refresh_models_combo(self):
        """
        Repopula combo_models a partir do catálogo global.

        Usa QSignalBlocker (não blockSignals cru) para que, quando esta
        função é chamada de DENTRO de _load_profile_into_widgets (que também
        protege combo_models com seu próprio QSignalBlocker), o desbloqueio
        ocorra na ordem certa em vez de reabrir o combo prematuramente (#2).
        """
        blocker = QSignalBlocker(self.combo_models)
        self.combo_models.clear()
        models = self.config.get("models", [])
        if not models:
            self.combo_models.addItem("Nenhum modelo configurado", "")
        else:
            for m in models:
                self.combo_models.addItem(m.get("label", "Modelo"), m.get("path"))
        del blocker

    def on_model_selected(self, index):
        """
        #4: Selecionar outro modelo no combo não recarregava o reconhecedor.
        save_settings() só grava a configuração; a AudioThread só relê o
        modelo quando recebe trigger_reload() via o sinal model_changed. Sem
        emitir esse sinal aqui, o áudio continuava usando o modelo anterior
        até a próxima troca de perfil.
        """
        self.save_settings()
        if self._loading_widgets:
            return  # Repopulação/carregamento de perfil, não uma escolha do usuário.

        novo_path = self.combo_models.currentData() or ""
        if novo_path != self._last_selected_model_path:
            self._last_selected_model_path = novo_path
            self.model_changed.emit()

    def on_mic_selected(self, index):
        """
        #16: selecionar outro microfone precisa reabrir o stream de áudio.
        A AudioThread lia o device_id uma única vez antes do loop de
        captura; sem emitir um sinal aqui, a troca no combo não tinha
        NENHUM efeito prático até o app ser reiniciado.
        """
        self.save_settings()
        if self._loading_widgets:
            return  # Repopulação/carregamento de perfil, não uma escolha do usuário.

        self._sync_input_device()

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

    def _persist_profile_and_reload(self):
        """
        Persiste o config atual (já mutado em memória) e só então recarrega
        os widgets a partir dele.

        Usada depois de qualquer mutação direta (add/delete de modelo), para
        nunca deixar save_settings() — orientado pelos widgets ainda "antigos"
        — sobrescrever por engano o que acabamos de mutar (#1/#3/#19).
        """
        self.config.save()
        self._load_profile_into_widgets()

    def add_model(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Selecione a pasta do Vosk")
        if diretorio:
            nome, ok = QInputDialog.getText(self, "Nome", "Dê um nome (ex: Vosk PT-BR):")
            if ok and nome:
                with self.config.mutate() as data:
                    data.setdefault("models", []).append({"label": nome, "path": diretorio})
                    active_profile(data).setdefault("audio", {})["selected_model_path"] = diretorio

                # #3: Antes, com o catálogo vazio, save_settings() lia
                # combo_models.currentData() ANTES do combo ser repopulado
                # com o novo item — currentData() do combo antigo/vazio é
                # None, e isso sobrescrevia selected_model_path de volta
                # para "". _persist_profile_and_reload() persiste o que já
                # está correto em memória e SÓ DEPOIS recarrega (e seleciona)
                # o combo a partir dele.
                self._persist_profile_and_reload()
                self.model_changed.emit()

    def delete_model(self):
        path = self.combo_models.currentData()
        if not path: return
        models = self.config.get("models", [])
        model = next((m for m in models if m.get("path") == path), None)
        
        if model:
            reply = QMessageBox.question(self, "Remover Modelo", f"Remover '{model.get('label')}'?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                with self.config.mutate() as data:
                    data["models"] = [m for m in data.get("models", []) if m.get("path") != path]

                    # Desvincula de todos os perfis se for deletado globalmente
                    for p_data in data.get("profiles", {}).values():
                        audio = p_data.setdefault("audio", {})
                        if audio.get("selected_model_path") == path:
                            audio["selected_model_path"] = ""

                # #19: mesma causa do #3, na direção inversa — save_settings()
                # lia combo_models.currentData() ainda apontando para o
                # modelo JÁ REMOVIDO do catálogo (o combo só seria
                # repopulado depois), restaurando esse caminho morto no
                # perfil ativo.
                self._persist_profile_and_reload()
                self.model_changed.emit()

    def pick_txt_dir(self):
        diretorio = QFileDialog.getExistingDirectory(self, "Onde salvar os relatórios (.txt)")
        if diretorio:
            self.config.set("save_dir", diretorio)
            self.lbl_txt_path.setText(diretorio)
            self.save_settings(immediate=True)

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
        if idx >= 0:
            self.combo_lang.setCurrentIndex(idx)
        self.combo_lang.blockSignals(False)

    def _on_languages_failed(self, msg):
        self.combo_lang.blockSignals(True)
        self.combo_lang.clear()
        self.combo_lang.addItem("Inglês (erro ao ler índice)", "en")
        self.combo_lang.blockSignals(False)
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
            from_lang = next((l for l in installed if l.code == "pt"), None)
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
            self.installer = PackageInstallThread("pt", target_lang)
            self.installer.finished.connect(self.on_install_finished)
            self.installer.finished.connect(self.installer.deleteLater)  # Cleanup
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
        # Não perca alterações que ainda estavam no debounce.
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