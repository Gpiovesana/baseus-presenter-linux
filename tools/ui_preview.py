"""Prévia visual isolada: não importa o app, lê hardware ou salva configurações."""
import argparse
from ui_effects_preview import DEFAULT_VISUAL, EffectsPage
from ui_audio_preview import DEFAULT_AUDIO, AudioPage
from ui_settings_preview import SettingsPage
from pathlib import Path
import sys

from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QPushButton, QSlider, QVBoxLayout, QWidget, QComboBox, QInputDialog, QMessageBox, QStackedWidget)

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = {
    "laser": ("Laser digital", "Segure para apontar", "SEGURAR", "Ativa a ferramenta visual selecionada enquanto o botão estiver pressionado.", "CLIQUE DUPLO", "Alterna entre laser, lupa e spotlight."),
    "next": ("Avançar", "Próximo slide", "CLIQUE", "Avança a apresentação usando o comando nativo do passador.", "SEGURAR", "Alterna a tela preta para trazer a atenção de volta a você."),
    "back": ("Voltar", "Slide anterior", "CLIQUE", "Volta ao slide anterior usando o comando nativo do passador.", "DICA", "A navegação continua sob controle do aplicativo de apresentação."),
    "pen": ("Pincel", "Desenhar e apagar", "SEGURAR", "Ativa o desenho sobre a apresentação.", "APAGAR", "O comando de borracha do passador limpa os traços."),
    "mic": ("Microfone", "Transcrição de voz", "CLIQUE", "Inicia ou encerra a gravação da transcrição.", "PROCESSAMENTO LOCAL", "O reconhecimento usa o modelo de voz selecionado nas configurações."),
    "translate": ("Tradução", "Legendas traduzidas", "CLIQUE", "Ativa ou desativa as legendas traduzidas.", "IDIOMA", "O idioma de destino é definido em Áudio e tradução."),
}

STYLE = """
QWidget { background: #181b20; color: #e6eaf1; font-family: 'DejaVu Sans'; font-size: 13px; }
QFrame#header { background: #15181c; border-bottom: 1px solid #303640; }
QFrame#sidebar, QFrame#details { background: #1e2229; }
QFrame#sidebar { border-right: 1px solid #303640; }
QFrame#details { border-left: 1px solid #303640; }
QFrame#profiles { background: #1e2229; border-bottom: 1px solid #303640; }
QComboBox { background: #252b34; border: 1px solid #45566d; border-radius: 7px; padding: 9px 12px; }
QComboBox QAbstractItemView { background: #252b34; selection-background-color: #233b58; }
QLabel { background: transparent; }
QLabel#muted { color: #9aa6b6; font-size: 12px; }
QLabel#section { color: #8b9bb0; font-size: 10px; font-weight: bold; }
QLabel#heading { font-size: 23px; font-weight: bold; }
QLabel#title { font-size: 20px; font-weight: bold; }
QPushButton { padding: 12px 14px; border: 1px solid #37404d; border-radius: 8px; background: #252b34; text-align: left; }
QPushButton:hover { background: #303b4b; border-color: #6887af; }
QPushButton:checked { background: #233b58; color: #b5d6ff; border-color: #548fdb; }
QPushButton:focus { border: 2px solid #98bdff; }
QPushButton:disabled { color: #788390; border: none; background: transparent; }
QSlider::groove:horizontal { background: #364150; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #69a4f7; border-radius: 2px; }
QSlider::handle:horizontal { background: #c1d9ff; width: 14px; margin: -5px 0; border-radius: 7px; }
"""


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class Device(QWidget):
    selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 520)
        self.active = "laser"
        self.buttons = {}
        for key, info in CONTROLS.items():
            button = QPushButton(info[0] + "\n" + info[1], self)
            button.setCheckable(True)
            button.setAccessibleName(info[0])
            button.clicked.connect(lambda _checked, key=key: self.selected.emit(key))
            self.buttons[key] = button

    def select(self, key):
        self.active = key
        for name, button in self.buttons.items():
            button.setChecked(name == key)
        self.update()

    def mousePressEvent(self, event):
        for key, fraction in [('laser',.18),('next',.29),('back',.40),('pen',.51),('mic',.62),('translate',.73)]:
            point = QPointF(self.width()/2, self.height()*fraction+5)
            delta = QPointF(event.pos())-point
            if delta.x()**2+delta.y()**2 <= 25**2:
                self.selected.emit(key)
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        for key, (left, fraction) in {
            "laser": (True, .18), "next": (False, .29), "back": (True, .40),
            "pen": (False, .51), "mic": (True, .62), "translate": (False, .73),
        }.items():
            self.buttons[key].setGeometry(14 if left else w-178, int(h*fraction)-24, 164, 62)
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        center, top = w/2, h*.08
        body = QRectF(center-57, top, 114, h*.82)
        gradient = QLinearGradient(body.topLeft(), body.topRight())
        gradient.setColorAt(0, QColor('#343b45'))
        gradient.setColorAt(.45, QColor('#242a32'))
        gradient.setColorAt(1, QColor('#15191f'))
        p.setPen(QPen(QColor('#4a535f'), 1.5))
        p.setBrush(gradient)
        p.drawRoundedRect(body, 48, 48)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#f5a34a'))
        p.drawRoundedRect(QRectF(center-15, top+16, 30, 5), 2, 2)
        glyphs = {'laser': '●', 'next': '↓', 'back': '↑', 'pen': '✎', 'mic': 'M', 'translate': 'A'}
        for key, fraction in [('laser',.18),('next',.29),('back',.40),('pen',.51),('mic',.62),('translate',.73)]:
            y = h*fraction+5
            left = key in ('laser','back','mic')
            chosen = key == self.active
            color = QColor('#77adff' if chosen else '#4c5868')
            p.setPen(QPen(color, 1.7 if chosen else 1))
            p.drawLine(QPointF(center+(-28 if left else 28), y), QPointF(178 if left else w-178, y))
            p.setBrush(QColor('#243d5c' if chosen else '#151a21'))
            p.drawEllipse(QPointF(center,y),25,25)
            p.setPen(QColor('#b4d3ff' if chosen else '#d0d6df'))
            p.setFont(QFont('DejaVu Sans',16))
            p.drawText(QRectF(center-25,y-25,50,50),Qt.AlignCenter,glyphs[key])
        p.setPen(QColor('#a2aab7'))
        p.setFont(QFont('DejaVu Sans',9))
        p.drawText(QRectF(center-50,body.bottom()-44,100,22),Qt.AlignCenter,'BASEUS')
        p.end()


class Preview(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Baseus Presenter — Prévia da interface')
        self.setWindowIcon(QIcon(str(ROOT/'app/resources/baseus-presenter.png')))
        self.resize(1280, 850)
        self.setMinimumSize(1120, 800)
        self.setStyleSheet(STYLE)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        header = QFrame(objectName='header')
        row = QHBoxLayout(header)
        row.setContentsMargins(26,20,26,20)
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(38,38))
        row.addWidget(logo)
        names = QVBoxLayout()
        names.addWidget(label('Baseus Presenter','title'))
        names.addWidget(label('Orange Dot AI · Seu controle de apresentação','muted'))
        row.addLayout(names)
        row.addStretch()
        self.battery_label = label('▰  Bateria 85% · exemplo')
        self.battery_label.setAccessibleName('Bateria do passador: 85 por cento, valor de exemplo')
        self.battery_label.setToolTip('Dado ilustrativo. Na integração, será atualizado pelo passador.')
        self.battery_label.setStyleSheet('color: #a6dcbb; background: #23332d; border: 1px solid #3b5b4a; border-radius: 14px; padding: 7px 12px;')
        row.addWidget(self.battery_label)
        row.addSpacing(12)
        row.addWidget(label('PRÉVIA · Sem conexão','muted'))
        layout.addWidget(header)
        self.profiles = {'Padrão': dict(DEFAULT_VISUAL, **DEFAULT_AUDIO)}
        self.active_profile = 'Padrão'
        profile_bar = QFrame(objectName='profiles')
        profiles_layout = QHBoxLayout(profile_bar)
        profiles_layout.setContentsMargins(24,12,24,12)
        profiles_layout.setSpacing(12)
        profiles_layout.addWidget(label('Perfil'))
        self.combo_profiles = QComboBox()
        self.combo_profiles.setAccessibleName('Perfil ativo')
        self.combo_profiles.setMinimumWidth(210)
        self.combo_profiles.addItem('Padrão')
        profiles_layout.addWidget(self.combo_profiles)
        self.new_profile_button = QPushButton('+ Novo perfil')
        self.new_profile_button.clicked.connect(self.new_profile)
        profiles_layout.addWidget(self.new_profile_button)
        self.delete_profile_button = QPushButton('Excluir')
        self.delete_profile_button.setEnabled(False)
        self.delete_profile_button.clicked.connect(self.delete_profile)
        profiles_layout.addWidget(self.delete_profile_button)
        profiles_layout.addStretch()
        profiles_layout.addWidget(label('Perfis manuais · Demonstração sem salvar','muted'))
        layout.addWidget(profile_bar)
        body = QHBoxLayout()
        body.setSpacing(0)
        sidebar = QFrame(objectName='sidebar')
        sidebar.setFixedWidth(192)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(16,28,16,20)
        navigation.setSpacing(12)
        navigation.addWidget(label('DISPOSITIVO','section'))
        self.nav_buttons = []
        for i,text in enumerate(['Botões','Ponteiro e efeitos','Áudio e tradução','Configurações']):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(i==0)
            button.setEnabled(True)
            self.nav_buttons.append(button)
            button.clicked.connect(lambda checked,index=i:self.show_page(index))
            navigation.addWidget(button)
        navigation.addStretch()
        navigation.addWidget(label('Uma interface mais clara\npara apresentar.','muted',True))
        body.addWidget(sidebar)
        self.pages = QStackedWidget()
        buttons_page = QWidget()
        buttons_layout = QHBoxLayout(buttons_page)
        buttons_layout.setContentsMargins(0,0,0,0)
        buttons_layout.setSpacing(0)
        center = QVBoxLayout()
        center.setContentsMargins(24,24,24,16)
        center.addWidget(label('Conheça seu passador','heading'))
        center.addWidget(label('Selecione um botão para ver como ele funciona.','muted'))
        self.device = Device()
        center.addWidget(self.device,1)
        center.addWidget(label('Ilustração esquemática · Funções atuais, sem remapeamento de botões.','muted',True))
        buttons_layout.addLayout(center,1)
        details = QFrame(objectName='details')
        details.setFixedWidth(306)
        panel = QVBoxLayout(details)
        panel.setContentsMargins(24,28,24,24)
        panel.setSpacing(16)
        panel.addWidget(label('BOTÃO SELECIONADO','section'))
        self.title = label('','heading',True)
        panel.addWidget(self.title)
        self.action1, self.desc1 = label('','section'),label('',wrap=True)
        self.action2, self.desc2 = label('','section'),label('',wrap=True)
        for widget in [self.action1,self.desc1,self.action2,self.desc2]:
            panel.addWidget(widget)
        self.laser_options = QWidget()
        options = QVBoxLayout(self.laser_options)
        options.setContentsMargins(0,18,0,0)
        options.addWidget(label('AJUSTE VISUAL','section'))
        self.laser_color_label = label('Cor do laser   #FF0000')
        options.addWidget(self.laser_color_label)
        self.size = label('Tamanho     40')
        options.addWidget(self.size)
        self.laser_slider = QSlider(Qt.Horizontal)
        self.laser_slider.setAccessibleName('Tamanho do laser')
        self.laser_slider.setRange(10,100)
        self.laser_slider.setValue(40)
        self.laser_slider.valueChanged.connect(self.set_size)
        options.addWidget(self.laser_slider)
        options.addWidget(label('Demonstração: este ajuste não é salvo.','muted',True))
        panel.addWidget(self.laser_options)
        panel.addStretch()
        panel.addWidget(label('Configurações e atalhos existentes serão preservados na integração.','muted',True))
        buttons_layout.addWidget(details)
        self.pages.addWidget(buttons_page)
        self.effects = EffectsPage()
        self.effects.changed.connect(self.update_visual)
        self.pages.addWidget(self.effects)
        self.audio_page = AudioPage()
        self.audio_page.changed.connect(self.update_audio)
        self.pages.addWidget(self.audio_page)
        self.settings_page = SettingsPage()
        self.settings_page.subtitles_changed.connect(lambda enabled:self.update_audio('show_subtitles',enabled))
        self.pages.addWidget(self.settings_page)
        body.addWidget(self.pages,1)
        layout.addLayout(body,1)
        self.device.selected.connect(self.select)
        self.select('laser')
        self.combo_profiles.currentTextChanged.connect(self.change_profile)

    def select(self,key):
        title, _, action1, desc1, action2, desc2 = CONTROLS[key]
        for widget,text in [(self.title,title),(self.action1,action1),(self.desc1,desc1),(self.action2,action2),(self.desc2,desc2)]:
            widget.setText(text)
        self.laser_options.setVisible(key=='laser')
        self.device.select(key)


    def show_page(self,index):
        self.pages.setCurrentIndex(index)
        for i,button in enumerate(self.nav_buttons):
            button.setChecked(i==index)

    def update_visual(self,key,value):
        self.profiles[self.active_profile][key] = value
        if key=='laser_color':
            self.laser_color_label.setText('Cor do laser   '+value.upper())
        if key=='laser_size':
            self.laser_slider.blockSignals(True)
            self.laser_slider.setValue(value)
            self.laser_slider.blockSignals(False)
            self.size.setText(f'Tamanho     {value}')

    def update_audio(self,key,value):
        self.profiles[self.active_profile][key] = value

    def set_size(self, value):
        self.size.setText(f'Tamanho     {value}')
        self.profiles[self.active_profile]["laser_size"] = value
        self.effects.set_settings(self.profiles[self.active_profile])

    def change_profile(self, name):
        if name not in self.profiles:
            return
        self.active_profile = name
        self.laser_slider.blockSignals(True)
        self.laser_slider.setValue(self.profiles[name]["laser_size"])
        self.laser_slider.blockSignals(False)
        self.size.setText(f'Tamanho     {self.profiles[name]["laser_size"]}')
        self.effects.set_settings(self.profiles[name])
        self.audio_page.set_settings(self.profiles[name])
        self.settings_page.set_subtitles(self.profiles[name]["show_subtitles"])
        self.laser_color_label.setText('Cor do laser   '+self.profiles[name]["laser_color"].upper())
        self.delete_profile_button.setEnabled(len(self.profiles)>1)

    def new_profile(self):
        name, accepted = QInputDialog.getText(self, 'Novo perfil', 'Nome do perfil:')
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.profiles:
            QMessageBox.warning(self, 'Perfil existente', 'Já existe um perfil com esse nome.')
            return
        self.profiles[name] = self.profiles[self.active_profile].copy()
        self.combo_profiles.addItem(name)
        self.combo_profiles.setCurrentText(name)

    def delete_profile(self):
        if len(self.profiles)<=1:
            return
        name = self.active_profile
        if QMessageBox.question(self, 'Excluir perfil', f"Excluir o perfil '{name}'?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        del self.profiles[name]
        self.combo_profiles.removeItem(self.combo_profiles.currentIndex())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot',type=Path)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--page',choices=('buttons','effects','audio','settings'),default='buttons')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = Preview()
    window.show()
    app.processEvents()
    if args.check:
        assert not window.windowIcon().isNull()
        for key,info in CONTROLS.items():
            window.device.buttons[key].click()
            assert window.title.text()==info[0]
            assert sum(b.isChecked() for b in window.device.buttons.values())==1
        from PyQt5.QtTest import QTest
        from PyQt5.QtCore import QPoint
        QTest.mouseClick(window.device, Qt.LeftButton, pos=QPoint(window.device.width()//2, int(window.device.height()*.51+5)))
        assert window.title.text() == CONTROLS['pen'][0]
        window.select('laser')
        assert window.laser_options.isVisible()
        from unittest.mock import patch
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        assert window.combo_profiles.currentText() == 'Padrão'
        assert not window.delete_profile_button.isEnabled()
        window.laser_slider.setValue(64)
        with patch.object(QInputDialog, 'getText', return_value=('Aula', True)):
            window.new_profile_button.click()
        assert window.combo_profiles.currentText() == 'Aula'
        assert window.laser_slider.value() == 64
        window.laser_slider.setValue(25)
        window.combo_profiles.setCurrentText('Padrão')
        assert window.laser_slider.value() == 64
        window.combo_profiles.setCurrentText('Aula')
        assert window.laser_slider.value() == 25
        with patch.object(QInputDialog, 'getText', return_value=('Aula', True)), patch.object(QMessageBox, 'warning') as warning:
            window.new_profile_button.click()
            warning.assert_called_once()
        assert window.combo_profiles.count() == 2
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            window.delete_profile_button.click()
        assert window.combo_profiles.count() == 2
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            window.delete_profile_button.click()
        assert window.combo_profiles.currentText() == 'Padrão'
        assert window.laser_slider.value() == 64
        assert not window.delete_profile_button.isEnabled()
        window.laser_slider.setValue(40)
        window.nav_buttons[1].click()
        assert window.pages.currentIndex() == 1
        for mode in ('laser','lupa','spotlight','pincel'):
            window.effects.mode_buttons[mode].click()
            assert window.effects.canvas.mode == mode
        window.effects.sliders['laser_size'].setValue(72)
        assert window.laser_slider.value() == 72
        with patch.object(QInputDialog, 'getText', return_value=('Efeitos', True)):
            window.new_profile_button.click()
        window.effects.sliders['lupa_size'].setValue(420)
        with patch('ui_effects_preview.QColorDialog.getColor', return_value=QColor('#00cc88')):
            window.effects.color_buttons['pincel_color'].click()
        window.combo_profiles.setCurrentText('Padrão')
        assert window.effects.sliders['lupa_size'].value() == 250
        assert window.effects.settings['pincel_color'] == '#FF0000'
        window.combo_profiles.setCurrentText('Efeitos')
        assert window.effects.sliders['lupa_size'].value() == 420
        assert window.effects.settings['pincel_color'] == '#00cc88'
        with patch('ui_effects_preview.QColorDialog.getColor', return_value=QColor()):
            window.effects.color_buttons['pincel_color'].click()
        assert window.effects.settings['pincel_color'] == '#00cc88'
        with patch('ui_effects_preview.QColorDialog.getColor', return_value=QColor('#2255cc')):
            window.effects.color_buttons['laser_color'].click()
        assert '#2255CC' in window.laser_color_label.text()
        for slider in window.effects.sliders.values():
            slider.setValue(slider.maximum())
            app.processEvents()
        for mode in window.effects.mode_buttons:
            window.effects.mode_buttons[mode].click()
            assert not window.effects.canvas.grab().isNull()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            window.delete_profile_button.click()
        window.laser_slider.setValue(40)
        window.effects.mode_buttons['laser'].click()
        window.nav_buttons[0].click()
    if args.check:
        window.nav_buttons[2].click()
        assert window.pages.currentIndex() == 2
        assert window.audio_page.target.currentData() == 'en'
        with patch.object(QInputDialog, 'getText', return_value=('Áudio', True)):
            window.new_profile_button.click()
        window.audio_page.target.setCurrentIndex(window.audio_page.target.findData('es'))
        window.audio_page.microphone.setCurrentIndex(1)
        window.audio_page.model.setCurrentIndex(1)
        assert "Inglês" in window.audio_page.source.text()
        window.combo_profiles.setCurrentText('Padrão')
        assert window.audio_page.target.currentData() == 'en'
        assert window.audio_page.microphone.currentData() is None
        window.combo_profiles.setCurrentText('Áudio')
        assert window.audio_page.target.currentData() == 'es'
        assert window.audio_page.microphone.currentIndex() == 1
        assert window.audio_page.model.currentIndex() == 1
        with patch('ui_audio_preview.QInputDialog.getText', return_value=('/tmp/exemplo-transcricoes', True)):
            window.audio_page.folder_button.click()
        window.combo_profiles.setCurrentText('Padrão')
        assert window.audio_page.folder.text() == '/tmp/exemplo-transcricoes'
        with patch('ui_audio_preview.QInputDialog.getText', return_value=('', False)):
            window.audio_page.folder_button.click()
        assert window.audio_page.folder.text() == '/tmp/exemplo-transcricoes'
        for button in (window.audio_page.add_model_button,window.audio_page.remove_model_button,window.audio_page.language_button):
            with patch('ui_audio_preview.QMessageBox.information') as info:
                button.click()
                info.assert_called_once()
        window.audio_page.save_dir = '~/Documentos/Transcrições (exemplo)'
        window.audio_page.folder.setText(window.audio_page.save_dir)
        window.combo_profiles.setCurrentText('Áudio')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            window.delete_profile_button.click()
    if args.check:
        window.nav_buttons[3].click()
        assert window.pages.currentIndex() == 3
        assert window.battery_label.isVisible()
        assert '85%' in window.battery_label.text()
        assert 'exemplo' in window.battery_label.text()
        window.settings_page.language.setCurrentIndex(2)
        window.settings_page.close_behavior.setCurrentIndex(0)
        with patch.object(QInputDialog, 'getText', return_value=('Configurações', True)):
            window.new_profile_button.click()
        window.settings_page.subtitles.setChecked(False)
        window.combo_profiles.setCurrentText('Padrão')
        assert window.settings_page.subtitles.isChecked()
        assert window.settings_page.language.currentData() == 'en'
        assert window.settings_page.close_behavior.currentData() == 'tray'
        window.combo_profiles.setCurrentText('Configurações')
        assert not window.settings_page.subtitles.isChecked()
        for button in (window.settings_page.update_button,window.settings_page.uninstall_button):
            with patch('ui_settings_preview.QMessageBox.information') as info:
                button.click()
                info.assert_called_once()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            window.delete_profile_button.click()
        window.settings_page.language.setCurrentIndex(0)
        window.settings_page.close_behavior.setCurrentIndex(1)
        for index in range(4):
            window.nav_buttons[index].click()
            assert window.battery_label.isVisible()
    window.show_page({'buttons':0,'effects':1,'audio':2,'settings':3}[args.page])
    if args.screenshot:
        app.processEvents()
        assert window.grab().save(str(args.screenshot))
    if args.check or args.screenshot:
        window.close()
        return
    sys.exit(app.exec_())


if __name__=='__main__':
    main()
