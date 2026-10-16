"""Demonstração local dos efeitos; não captura a tela nem cria um overlay."""
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (QColorDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QSlider, QVBoxLayout, QWidget)

DEFAULT_VISUAL = dict(laser_size=40, laser_color='#FF0000', lupa_size=250,
                      spotlight_size=300, spotlight_opacity=160, pincel_color='#FF0000')
MODES = {
    'laser': ('Laser', 'Laser digital', 'Ajuste a cor e o tamanho do ponto usado para destacar detalhes.'),
    'lupa': ('Lupa', 'Lupa', 'Escolha o tamanho da área ampliada. A demonstração amplia apenas o slide de exemplo.'),
    'spotlight': ('Spotlight', 'Spotlight', 'Controle a área iluminada e o escurecimento ao redor para concentrar a atenção.'),
    'pincel': ('Pincel', 'Pincel', 'Escolha a cor dos traços. O desenho abaixo é uma amostra, sem escrever sobre sua tela.'),
}


def text(value, name=None):
    widget = QLabel(value)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


class EffectCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(510,440)
        self.setMouseTracking(True)
        self.mode = 'laser'
        self.settings = DEFAULT_VISUAL.copy()
        self.pointer = None

    def mouseMoveEvent(self, event):
        self.pointer = QPointF(event.pos())
        self.update()

    def paintEvent(self, event):
        # A lupa reutiliza este pixmap local, sem ler pixels do desktop.
        slide = QPixmap(self.size())
        slide.fill(QColor('#181b20'))
        p = QPainter(slide)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(20,30,self.width()-40,self.height()-60)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#f1f4f8'))
        p.drawRoundedRect(rect,12,12)
        p.setPen(QColor('#537193'))
        p.setFont(QFont('DejaVu Sans',10))
        p.drawText(QPointF(46,70),'APRESENTAÇÃO DE EXEMPLO')
        p.setPen(QColor('#172f49'))
        p.setFont(QFont('DejaVu Sans',20,QFont.Bold))
        p.drawText(QRectF(46,91,self.width()-92,85),Qt.TextWordWrap,'Dê destaque ao que importa.')
        p.setFont(QFont('DejaVu Sans',11))
        p.setPen(QColor('#53677d'))
        p.drawText(QRectF(46,172,self.width()-92,60),Qt.TextWordWrap,'Uma ideia por vez. Mais clareza para acompanhar sua apresentação.')
        base = self.height()-104
        for i,(height,color) in enumerate([(56,'#bbcee4'),(90,'#82a9da'),(128,'#4d82c4'),(161,'#265b98')]):
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(55+i*76,base-height,46,height),5,5)
        p.setPen(QColor('#9bacbc'))
        p.drawLine(QPointF(46,base+10),QPointF(self.width()-46,base+10))
        p.setFont(QFont('DejaVu Sans',9))
        p.drawText(QPointF(46,self.height()-55),'01  /  CLAREZA NA APRESENTAÇÃO')
        p.end()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(0,0,slide)
        pos = self.pointer or QPointF(self.width()*.43,self.height()*.62)
        settings = self.settings
        if self.mode == 'laser':
            p.setBrush(QColor(settings['laser_color']))
            p.setPen(Qt.NoPen)
            radius = settings['laser_size']/2
            p.drawEllipse(pos,radius,radius)
        elif self.mode == 'spotlight':
            radius = settings['spotlight_size']/2
            path = QPainterPath()
            path.addRect(rect)
            path.addEllipse(pos,radius,radius)
            p.setClipRect(rect)
            p.fillPath(path,QColor(0,0,0,settings['spotlight_opacity']))
        elif self.mode == 'lupa':
            diameter = settings['lupa_size']
            target = QRectF(pos.x()-diameter/2,pos.y()-diameter/2,diameter,diameter)
            source = QRectF(pos.x()-diameter/4,pos.y()-diameter/4,diameter/2,diameter/2)
            clip = QPainterPath()
            clip.addEllipse(target)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(target,slide,source)
            p.restore()
            p.setPen(QPen(QColor('#548fdb'),2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(target)
        elif self.mode == 'pincel':
            path = QPainterPath(QPointF(55,self.height()*.52))
            path.cubicTo(145,self.height()*.75,230,self.height()*.36,self.width()-55,self.height()*.59)
            p.setPen(QPen(QColor(settings['pincel_color']),5,Qt.SolidLine,Qt.RoundCap))
            p.drawPath(path)
        p.end()


class EffectsPage(QWidget):
    changed = pyqtSignal(str,object)

    def __init__(self):
        super().__init__()
        self.settings = DEFAULT_VISUAL.copy()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        preview = QVBoxLayout()
        preview.setContentsMargins(24,24,24,16)
        preview.addWidget(text('Ponteiro e efeitos','heading'))
        preview.addWidget(text('Escolha uma ferramenta e veja os ajustes no slide de exemplo.','muted'))
        modes = QHBoxLayout()
        self.mode_buttons = {}
        for key,(name,_,__) in MODES.items():
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda checked,key=key:self.set_mode(key))
            self.mode_buttons[key] = button
            modes.addWidget(button)
        preview.addLayout(modes)
        self.canvas = EffectCanvas()
        preview.addWidget(self.canvas,1)
        preview.addWidget(text('Mova o mouse sobre o slide para experimentar. Nenhuma captura de tela é feita.','muted'))
        layout.addLayout(preview,1)
        details = QFrame(objectName='details')
        details.setFixedWidth(306)
        panel = QVBoxLayout(details)
        panel.setContentsMargins(24,28,24,24)
        panel.setSpacing(18)
        panel.addWidget(text('AJUSTES DA FERRAMENTA','section'))
        self.title = text('','heading')
        self.description = text('')
        panel.addWidget(self.title)
        panel.addWidget(self.description)
        self.sliders, self.values, self.fields, self.color_buttons = {},{},{},{}
        for key,name,low,high in [('laser_size','Tamanho do laser',10,100),('lupa_size','Tamanho da lupa',100,500),('spotlight_size','Área iluminada',100,800),('spotlight_opacity','Escurecimento',50,255)]:
            field = QWidget()
            row = QVBoxLayout(field)
            row.setContentsMargins(0,8,0,0)
            value = text('')
            row.addWidget(value)
            slider = QSlider(Qt.Horizontal)
            slider.setAccessibleName(name)
            slider.setRange(low,high)
            slider.valueChanged.connect(lambda value,key=key:self.update_setting(key,value))
            row.addWidget(slider)
            self.values[key] = (value,name)
            self.sliders[key] = slider
            self.fields[key] = field
            panel.addWidget(field)
        for key,name in [('laser_color','Cor do laser'),('pincel_color','Cor do pincel')]:
            button = QPushButton(name)
            button.setAccessibleName(name)
            button.clicked.connect(lambda checked,key=key:self.pick_color(key))
            self.color_buttons[key] = button
            self.fields[key] = button
            panel.addWidget(button)
        panel.addStretch()
        panel.addWidget(text('Ajustes do perfil selecionado. Nesta prévia, as alterações ficam somente em memória.','muted'))
        layout.addWidget(details)
        self.set_settings(self.settings)
        self.set_mode('laser')

    def set_settings(self, settings):
        self.settings = settings.copy()
        for key,slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(settings[key])
            slider.blockSignals(False)
            value,name = self.values[key]
            suffix = f"{round(settings[key]/255*100)}%" if key=='spotlight_opacity' else f"{settings[key]} px"
            value.setText(f'{name}   {suffix}')
        for key,button in self.color_buttons.items():
            button.setText(('Cor do laser' if key=='laser_color' else 'Cor do pincel')+'   '+settings[key].upper())
            button.setStyleSheet('border-left: 8px solid '+settings[key]+';')
        self.canvas.settings = settings.copy()
        self.canvas.update()

    def update_setting(self,key,value):
        self.settings[key] = value
        self.set_settings(self.settings)
        self.changed.emit(key,value)

    def pick_color(self,key):
        color = QColorDialog.getColor(QColor(self.settings[key]),self,'Escolher cor')
        if color.isValid():
            self.update_setting(key,color.name())

    def set_mode(self,mode):
        for key,button in self.mode_buttons.items():
            button.setChecked(key==mode)
        self.title.setText(MODES[mode][1])
        self.description.setText(MODES[mode][2])
        visible = {'laser':('laser_size','laser_color'),'lupa':('lupa_size',),'spotlight':('spotlight_size','spotlight_opacity'),'pincel':('pincel_color',)}[mode]
        for key,field in self.fields.items():
            field.setVisible(key in visible)
        self.canvas.mode = mode
        self.canvas.update()
