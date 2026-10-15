"""Prévia de áudio: dados de exemplo; sem gravação, downloads ou escrita em disco."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QInputDialog,
                             QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from ui_effects_preview import text

DEFAULT_AUDIO = dict(input_device_name=None, selected_model_path='demo-pt', target_lang='en', show_subtitles=True)
LANGUAGES = [('Português','pt'),('Inglês','en'),('Espanhol','es'),('Francês','fr')]
EXAMPLES = {
    'pt': 'Uma ideia por vez. Vamos observar o próximo exemplo.',
    'en': 'One idea at a time. Let’s look at the next example.',
    'es': 'Una idea a la vez. Veamos el siguiente ejemplo.',
    'fr': 'Une idée à la fois. Regardons le prochain exemple.',
}


def card(title,subtitle):
    frame = QFrame(objectName='audioCard')
    frame.setStyleSheet('QFrame#audioCard { background: #20262f; border: 1px solid #35404e; border-radius: 10px; }')
    frame.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18,16,18,16)
    layout.setSpacing(10)
    layout.addWidget(text(title,'title'))
    layout.addWidget(text(subtitle,'muted'))
    return frame,layout


class AudioPage(QWidget):
    changed = pyqtSignal(str,object)

    def __init__(self):
        super().__init__()
        self.settings = DEFAULT_AUDIO.copy()
        self.save_dir = '~/Documentos/Transcrições (exemplo)'
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(24,24,24,16)
        main.setSpacing(14)
        main.addWidget(text('Áudio e tradução','heading'))
        main.addWidget(text('Prepare a transcrição e as legendas do seu próximo encontro.','muted'))
        frame,fields = card('Entrada e reconhecimento','Estas escolhas acompanham o perfil selecionado.')
        fields.addWidget(text('Microfone'))
        self.microphone = QComboBox()
        self.microphone.setAccessibleName('Microfone')
        self.microphone.addItem('Padrão do sistema (automático)',None)
        self.microphone.addItem('Microfone do passador — exemplo','demo-presenter-mic')
        self.microphone.currentIndexChanged.connect(lambda:self.update_setting('input_device_name',self.microphone.currentData()))
        fields.addWidget(self.microphone)
        fields.addWidget(text('Modelo de reconhecimento de voz'))
        self.model = QComboBox()
        self.model.setAccessibleName('Modelo de reconhecimento de voz')
        self.model.addItem('Português · modelo de exemplo','demo-pt')
        self.model.addItem('Inglês · modelo de exemplo','demo-en')
        self.model.currentIndexChanged.connect(lambda:self.update_setting('selected_model_path',self.model.currentData()))
        fields.addWidget(self.model)
        self.source = text('Idioma de origem: Português','muted')
        fields.addWidget(self.source)
        buttons = QHBoxLayout()
        self.add_model_button = QPushButton('Adicionar modelo')
        self.remove_model_button = QPushButton('Remover')
        self.language_button = QPushButton('Idioma do modelo')
        for button,title,description in [
            (self.add_model_button,'Adicionar modelo','Na versão integrada, você selecionará a pasta de um modelo de voz já baixado. Nesta prévia, nenhuma pasta será aberta ou adicionada.'),
            (self.remove_model_button,'Remover modelo','Na versão integrada, esta ação removerá o modelo do catálogo do aplicativo. Nesta prévia, os exemplos permanecem disponíveis.'),
            (self.language_button,'Idioma do modelo','Na versão integrada, você poderá informar ou corrigir o idioma de origem do modelo selecionado. Este é diferente do idioma de tradução.'),
        ]:
            button.clicked.connect(lambda checked,title=title,description=description:QMessageBox.information(self,title,description))
            buttons.addWidget(button)
        fields.addLayout(buttons)
        main.addWidget(frame)
        frame,fields = card('Legendas traduzidas','O idioma de origem vem do modelo de voz. Escolha aqui o destino.')
        row = QHBoxLayout()
        row.addWidget(text('Traduzir para'))
        self.target = QComboBox()
        self.target.setAccessibleName('Idioma de destino das legendas')
        for name,code in LANGUAGES:
            self.target.addItem(name,code)
        self.target.currentIndexChanged.connect(lambda:self.update_setting('target_lang',self.target.currentData()))
        row.addWidget(self.target,1)
        fields.addLayout(row)
        fields.addWidget(text('Idiomas ilustrativos. Na integração, a lista e os downloads seguirão os pacotes de tradução disponíveis.','muted'))
        main.addWidget(frame)
        frame,fields = card('Arquivos de transcrição','Pasta compartilhada por todos os perfis · arquivos .txt')
        self.folder = text(self.save_dir)
        self.folder.setStyleSheet('font-family: monospace; color: #b5cbe5;')
        fields.addWidget(self.folder)
        self.folder_button = QPushButton('Alterar pasta…')
        self.folder_button.clicked.connect(self.change_folder)
        fields.addWidget(self.folder_button)
        main.addWidget(frame)
        main.addStretch()
        main.addWidget(text('Microfones, modelos e idiomas são exemplos. Nenhum áudio é capturado nesta prévia.','muted'))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet('QScrollBar:vertical { background: #181b20; width: 10px; margin: 3px; } QScrollBar::handle:vertical { background: #4b5c72; min-height: 30px; border-radius: 2px; } QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; } QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }')
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll,1)
        side = QFrame(objectName='details')
        side.setFixedWidth(306)
        panel = QVBoxLayout(side)
        panel.setContentsMargins(24,28,24,24)
        panel.setSpacing(18)
        panel.addWidget(text('NO SEU PASSADOR','section'))
        panel.addWidget(text('Sua voz, em texto','heading'))
        panel.addWidget(text('MICROFONE','section'))
        panel.addWidget(text('Clique para iniciar ou encerrar a transcrição.'))
        panel.addWidget(text('TRADUÇÃO','section'))
        panel.addWidget(text('Clique para ativar ou desativar as legendas traduzidas.'))
        panel.addSpacing(12)
        panel.addWidget(text('EXEMPLO DE LEGENDA','section'))
        self.subtitle = text('')
        self.subtitle.setStyleSheet('background: #263950; border: 1px solid #426183; border-radius: 9px; padding: 16px; color: #d5e6ff; font-size: 16px;')
        panel.addWidget(self.subtitle)
        panel.addWidget(text('Texto ilustrativo; não é uma transcrição em andamento.','muted'))
        panel.addStretch()
        panel.addWidget(text('Reconhecimento e tradução locais após a preparação dos modelos.','muted'))
        layout.addWidget(side)
        for combo in (self.microphone,self.model,self.target):
            combo.setMinimumHeight(38)
        for button in (self.add_model_button,self.remove_model_button,self.language_button,self.folder_button):
            button.setMinimumHeight(40)
        self.set_settings(self.settings)

    def set_settings(self,settings):
        self.settings = {key:settings[key] for key in DEFAULT_AUDIO}
        for key,combo in [('input_device_name',self.microphone),('selected_model_path',self.model),('target_lang',self.target)]:
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0,combo.findData(settings[key])))
            combo.blockSignals(False)
        self.source.setText('Idioma de origem: '+('Português' if settings['selected_model_path']=='demo-pt' else 'Inglês'))
        self.subtitle.setText(EXAMPLES[settings['target_lang']])

    def update_setting(self,key,value):
        self.settings[key] = value
        self.set_settings(self.settings)
        self.changed.emit(key,value)

    def change_folder(self):
        value,accepted = QInputDialog.getText(self,'Pasta de demonstração','Caminho de exemplo (nenhuma pasta será criada):',text=self.save_dir)
        if accepted and value.strip():
            self.save_dir = value.strip()
            self.folder.setText(self.save_dir)
