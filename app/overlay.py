# ~/Documentos/Projetos/baseus-presenter-linux/app/overlay.py
import sys
from PyQt5.QtWidgets import QMainWindow, QApplication
from PyQt5.QtCore import Qt, QPoint, QRect, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QPainterPath, QRegion, QFont, QFontMetrics

from .logger import get_logger

log = get_logger(__name__)

class PointerWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # O teletransporte inteligente para múltiplos monitores (Criado na v1.1)
        self.current_screen = QApplication.screenAt(self.cursor().pos())
        if not self.current_screen: self.current_screen = QApplication.primaryScreen()
        self.setGeometry(self.current_screen.geometry())

        self.is_drawing = False
        self.modes = ["LASER", "LUPA", "SPOTLIGHT"]
        self.mode_index = 0

        self.is_pen_drawing = False
        self.pen_path = QPainterPath()
        self.last_pen_pos = None

        self.is_recording = False
        self.is_translating = False
        self.subtitle_text = ""
        self.subtitle_timer = QTimer()
        self.subtitle_timer.setSingleShot(True)
        self.subtitle_timer.timeout.connect(self.clear_subtitle)

        # Loop infinito (60 FPS) para rastrear o mouse e a tela atual
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_overlay)
        self.timer.start(16)
        
        log.info("Overlay visual (PointerWindow) inicializado com suporte a multi-telas.")

    def _update_overlay(self):
        """Rastreia o mouse e pula de monitor se necessário"""
        screen = QApplication.screenAt(self.cursor().pos())
        if screen and screen != self.current_screen:
            log.debug("Mudança de monitor detectada. Movendo overlay...")
            self.current_screen = screen
            self.setGeometry(screen.geometry())
            if hasattr(self, 'screen_pixmap') and self.is_drawing and self.modes[self.mode_index] == "LUPA":
                self.screen_pixmap = screen.grabWindow(0)
        self.update()

    # --- SLOTS: Funções que recebem os sinais do HardwareReader ---

    def set_active(self, active):
        self.is_drawing = active
        if active and self.modes[self.mode_index] == "LUPA":
            self.screen_pixmap = self.current_screen.grabWindow(0)
            
    def switch_mode(self):
        self.mode_index = (self.mode_index + 1) % len(self.modes)
        log.info(f"Modo do ponteiro alterado para: {self.modes[self.mode_index]}")
        if self.is_drawing and self.modes[self.mode_index] == "LUPA":
            self.screen_pixmap = self.current_screen.grabWindow(0)

    def set_pen_active(self, active):
        self.is_pen_drawing = active
        if not active: 
            self.last_pen_pos = None
            # Aqui está o segredo: Manda a caneta se levantar da folha!
            if not self.pen_path.isEmpty():
                self.pen_path.moveTo(self.cursor().pos())

    def pen_clear(self):
        self.pen_path = QPainterPath()
        log.debug("Tela limpa (Pincel apagado).")

    def set_recording(self, state):
        self.is_recording = state
        self.show_subtitle("[GRAVANDO]" if state else "[PAUSADO]", duration=2000)

    def set_translating(self, state):
        self.is_translating = state
        self.show_subtitle("[TRADUÇÃO ON]" if state else "[TRADUÇÃO OFF]", duration=2000)

    def show_subtitle(self, text, duration=5000):
        self.subtitle_text = text
        self.subtitle_timer.start(duration)

    def clear_subtitle(self):
        self.subtitle_text = ""

    # --- O MOTOR DE DESENHO ---

    def paintEvent(self, event):
        # Transforma a coordenada global do mouse na coordenada local da tela atual
        pos = self.mapFromGlobal(self.cursor().pos())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        v_config = self.config.get("visual", {})

        # 1. Desenhar a ferramenta principal (Laser, Lupa ou Spotlight)
        if self.is_drawing:
            mode = self.modes[self.mode_index]
            
            if mode == "LASER":
                size = v_config.get("laser_size", 30)
                color = QColor(v_config.get("laser_color", "#FF0000"))
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(pos, size // 2, size // 2)

            elif mode == "SPOTLIGHT":
                size = v_config.get("spotlight_size", 300)
                opacity = v_config.get("spotlight_opacity", 160)
                painter.fillRect(self.rect(), QColor(0, 0, 0, opacity))
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.setBrush(Qt.transparent)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(pos, size // 2, size // 2)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            elif mode == "LUPA" and hasattr(self, 'screen_pixmap'):
                size = v_config.get("lupa_size", 250)
                shape = v_config.get("lupa_shape", "circular")
                
                # A Lupa desenha a tela com zoom baseada na posição GLOBAL do mouse
                global_pos = self.cursor().pos()
                screen_rect = self.current_screen.geometry()
                local_x = global_pos.x() - screen_rect.x()
                local_y = global_pos.y() - screen_rect.y()
                
                src_rect = QRect(local_x - size//4, local_y - size//4, size//2, size//2)
                dst_rect = QRect(pos.x() - size//2, pos.y() - size//2, size, size)

                painter.setPen(QPen(Qt.white, 3))
                if shape == "circular":
                    path = QPainterPath()
                    path.addEllipse(pos, size // 2, size // 2)
                    painter.setClipPath(path)
                    painter.drawPixmap(dst_rect, self.screen_pixmap, src_rect)
                    painter.setClipping(False)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(pos, size // 2, size // 2)
                else:
                    painter.drawPixmap(dst_rect, self.screen_pixmap, src_rect)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(dst_rect)

        # 2. Desenhar o Pincel Livre
        if self.is_pen_drawing:
            if self.last_pen_pos:
                self.pen_path.lineTo(pos)
            else:
                self.pen_path.moveTo(pos)
            self.last_pen_pos = pos

        if not self.pen_path.isEmpty():
            p_color = QColor(v_config.get("pincel_color", "#FF0000"))
            painter.setPen(QPen(p_color, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(self.pen_path)

        # 3. Desenhar a Legenda (Transcrição/Tradução)
        if self.subtitle_text:
            font = QFont("Arial", 24, QFont.Bold)
            painter.setFont(font)
            fm = QFontMetrics(font)
            text_rect = fm.boundingRect(self.subtitle_text)
            
            # Caixa preta translúcida no rodapé do monitor atual
            bg_rect = QRect(
                (self.width() - text_rect.width()) // 2 - 20,
                self.height() - 100,
                text_rect.width() + 40,
                text_rect.height() + 20
            )
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 10, 10)
            
            painter.setPen(Qt.white)
            painter.drawText(bg_rect, Qt.AlignCenter, self.subtitle_text)
