"""Ilustrações locais da GUI; não captura pixels do desktop."""
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QWidget, QPushButton
from .i18n import tr


def control_descriptions():
    return {
        'laser': (tr('Laser digital'), tr('Segure para apontar'), tr('SEGURAR'), tr('Ativa a ferramenta visual selecionada enquanto o botão estiver pressionado.'), tr('CLIQUE DUPLO'), tr('Alterna entre laser, lupa e spotlight.')),
        'next': (tr('Avançar'), tr('Próximo slide'), tr('CLIQUE'), tr('Avança a apresentação usando o comando nativo do passador.'), tr('SEGURAR'), tr('Alterna a tela preta para trazer a atenção de volta a você.')),
        'back': (tr('Voltar'), tr('Slide anterior'), tr('CLIQUE'), tr('Volta ao slide anterior usando o comando nativo do passador.'), tr('DICA'), tr('A navegação continua sob controle do aplicativo de apresentação.')),
        'pen': (tr('Pincel'), tr('Desenhar e apagar'), tr('SEGURAR'), tr('Ativa o desenho sobre a apresentação.'), tr('APAGAR'), tr('O comando de borracha do passador limpa os traços.')),
        'mic': (tr('Microfone'), tr('Transcrição de voz'), tr('CLIQUE'), tr('Inicia ou encerra a gravação da transcrição.'), tr('PROCESSAMENTO LOCAL'), tr('O reconhecimento usa o modelo de voz selecionado nas configurações.')),
        'translate': (tr('Tradução'), tr('Legendas traduzidas'), tr('CLIQUE'), tr('Ativa ou desativa as legendas traduzidas.'), tr('IDIOMA'), tr('O idioma de destino é definido em Áudio e tradução.')),
    }


class Device(QWidget):
    selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(510, 440)
        self.active = "laser"
        self.buttons = {}
        for key, info in control_descriptions().items():
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
