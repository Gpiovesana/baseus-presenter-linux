"""Ilustrações locais da GUI; não captura pixels do desktop."""
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (QWidget, QPushButton, QLabel, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QStackedLayout)
from .i18n import tr
from .device_3d import ModelView, MODEL_PATH


def control_descriptions():
    return {
        'laser': (tr('Mouse e efeitos digitais'), tr('Botão com símbolo de mouse'), tr('SEGURAR'), tr('Ativa a ferramenta visual selecionada enquanto o botão estiver pressionado.'), tr('CLIQUE DUPLO'), tr('Alterna entre laser, lupa e spotlight.')),
        'physical_laser': (tr('Laser físico'), tr('Botão laranja do passador'), tr('APONTADOR FÍSICO'), tr('Aciona o laser emitido pelo próprio passador.'), tr('HARDWARE'), tr('Esse controle funciona diretamente no dispositivo.')),
        'next': (tr('Avançar'), tr('Próximo slide'), tr('CLIQUE'), tr('Avança a apresentação usando o comando nativo do passador.'), tr('SEGURAR'), tr('Alterna a tela preta para trazer a atenção de volta a você.')),
        'back': (tr('Voltar'), tr('Slide anterior'), tr('CLIQUE'), tr('Volta ao slide anterior usando o comando nativo do passador.'), tr('DICA'), tr('A navegação continua sob controle do aplicativo de apresentação.')),
        'screen': (tr('Links e janelas'), tr('Botão pequeno ao lado de Voltar'), tr('CLIQUE / DUPLO CLIQUE'), tr('Um clique abre o hyperlink selecionado; dois cliques navegam entre hyperlinks.'), tr('SEGURAR'), tr('Abre a visão de múltiplas janelas.')),
        'pen': (tr('Pincel'), tr('Desenhar e apagar'), tr('SEGURAR'), tr('Ativa o desenho sobre a apresentação.'), tr('APAGAR'), tr('O comando de borracha do passador limpa os traços.')),
        'mic': (tr('Microfone'), tr('Transcrição de voz'), tr('CLIQUE'), tr('Inicia ou encerra a gravação da transcrição.'), tr('PROCESSAMENTO LOCAL'), tr('O reconhecimento usa o modelo de voz selecionado nas configurações.')),
        'translate': (tr('Tradução'), tr('Legendas traduzidas'), tr('CLIQUE'), tr('Ativa ou desativa as legendas traduzidas.'), tr('IDIOMA'), tr('O idioma de destino é definido em Áudio e tradução.')),
        'volume_up': (tr('Volume +'), tr('Botão lateral de aumentar volume'), tr('CLIQUE'), tr('Aumenta o volume usando o comando nativo do passador.'), tr('SISTEMA'), tr('O ajuste é feito pelo controle de volume do sistema.')),
        'volume_down': (tr('Volume −'), tr('Botão lateral de diminuir volume'), tr('CLIQUE'), tr('Diminui o volume usando o comando nativo do passador.'), tr('SISTEMA'), tr('O ajuste é feito pelo controle de volume do sistema.')),
        'power': (tr('Ligar / desligar'), tr('Chave ON/OFF na lateral'), tr('DESLIZAR'), tr('Liga ou desliga o passador.'), tr('HARDWARE'), tr('A chave controla a alimentação do dispositivo.')),
    }


class Device(QWidget):
    selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(400,440)
        self.active='laser';self.buttons={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.stack=QStackedLayout();layout.addLayout(self.stack,1)
        self.view=ModelView(self);self.stack.addWidget(self.view)
        self.fallback=QLabel();self.fallback.setAlignment(Qt.AlignCenter)
        self._preview=QPixmap(str(MODEL_PATH.with_name('device-preview.png')))
        self.stack.addWidget(self.fallback)
        self.view.unavailable.connect(self.show_fallback)
        self.view.control_clicked.connect(self.selected.emit)
        toolbar=QHBoxLayout()
        self.hint=QLabel(tr('Clique em um botão do modelo para selecioná-lo · Arraste para girar · Roda para zoom'))
        self.hint.setWordWrap(True);toolbar.addWidget(self.hint,1)
        self.reset_button=QPushButton(tr('Restaurar vista'))
        self.reset_button.clicked.connect(self.view.reset_view);toolbar.addWidget(self.reset_button)
        layout.addLayout(toolbar)
        controls=QGridLayout();layout.addLayout(controls)
        for index,(key,info) in enumerate(control_descriptions().items()):
            button=QPushButton(info[0]);button.setCheckable(True)
            button.setAccessibleName(info[0]);button.setToolTip(info[1])
            button.clicked.connect(lambda _checked,key=key:self._select_from_menu(key))
            controls.addWidget(button,index//4,index%4);self.buttons[key]=button
        if QGuiApplication.platformName() in ('offscreen','minimal'):
            self.show_fallback()

    def _select_from_menu(self,key):
        self.select(key,focus=True)
        self.selected.emit(key)

    def select(self,key,focus=False):
        if focus:self.view.focus_control(key)
        elif key!=self.active:self.view.orient_for_control(key)
        self.active=key;self.view.active=key
        for name,button in self.buttons.items():button.setChecked(name==key)
        self.view.update()

    def show_fallback(self):
        self.stack.setCurrentWidget(self.fallback)
        self.hint.setText(tr('Visualização 3D indisponível. Use os botões abaixo para conhecer os controles.'))
        self.reset_button.setEnabled(False)
        self._resize_preview()

    def _resize_preview(self):
        self.fallback.setPixmap(self._preview.scaled(self.width(),max(1,self.height()-140),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.stack.currentWidget()==self.fallback:self._resize_preview()


class EffectCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(510,440)
        self.setMouseTracking(True)
        self.mode = 'laser'
        self.settings = {'laser_size': 30, 'laser_color': '#FF0000', 'lupa_size': 250, 'lupa_shape': 'circular', 'spotlight_size': 300, 'spotlight_opacity': 160, 'pincel_color': '#FF0000'}
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
        p.drawText(QPointF(46,70),tr('APRESENTAÇÃO DE EXEMPLO'))
        p.setPen(QColor('#172f49'))
        p.setFont(QFont('DejaVu Sans',20,QFont.Bold))
        p.drawText(QRectF(46,91,self.width()-92,85),Qt.TextWordWrap,tr('Dê destaque ao que importa.'))
        p.setFont(QFont('DejaVu Sans',11))
        p.setPen(QColor('#53677d'))
        p.drawText(QRectF(46,172,self.width()-92,60),Qt.TextWordWrap,tr('Uma ideia por vez. Mais clareza para acompanhar sua apresentação.'))
        base = self.height()-104
        for i,(height,color) in enumerate([(56,'#bbcee4'),(90,'#82a9da'),(128,'#4d82c4'),(161,'#265b98')]):
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(55+i*76,base-height,46,height),5,5)
        p.setPen(QColor('#9bacbc'))
        p.drawLine(QPointF(46,base+10),QPointF(self.width()-46,base+10))
        p.setFont(QFont('DejaVu Sans',9))
        p.drawText(QPointF(46,self.height()-55),tr('01  /  CLAREZA NA APRESENTAÇÃO'))
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
            if settings.get('lupa_shape', 'circular') == 'square':
                clip.addRect(target)
            else:
                clip.addEllipse(target)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(target,slide,source)
            p.restore()
            p.setPen(QPen(QColor('#548fdb'),2))
            p.setBrush(Qt.NoBrush)
            if settings.get('lupa_shape', 'circular') == 'square':
                p.drawRect(target)
            else:
                p.drawEllipse(target)
        elif self.mode == 'pincel':
            path = QPainterPath(QPointF(55,self.height()*.52))
            path.cubicTo(145,self.height()*.75,230,self.height()*.36,self.width()-55,self.height()*.59)
            p.setPen(QPen(QColor(settings['pincel_color']),5,Qt.SolidLine,Qt.RoundCap))
            p.drawPath(path)
        p.end()
