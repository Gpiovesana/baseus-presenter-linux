# ~/Documentos/Projetos/baseus-presenter-linux/app/overlay.py
import sys
from PyQt5.QtWidgets import QMainWindow, QApplication
from PyQt5.QtCore import Qt, QPoint, QRect, QTimer
from PyQt5.QtGui import (QPainter, QColor, QPen, QPainterPath, QRegion, QFont,
                         QFontMetrics, QPixmap)

from .logger import get_logger
from .config import Config

log = get_logger(__name__)

# Limite de traços guardados. Antes a lista crescia sem limite: uma sessão
# longa com muito desenho livre consumia RAM indefinidamente se o usuário
# nunca acionasse a borracha.
MAX_PEN_STROKES = 500

# Limite de pontos por traço. Protege contra um único traço "infinito"
# (usuário mantém o pincel apertado por minutos) — a 60 FPS isso acumula
# ~3600 pontos por minuto, todos reprocessados a cada quadro.
MAX_POINTS_PER_STROKE = 2000

# #26: fração da largura da tela que a caixa de legenda pode ocupar antes de
# quebrar em várias linhas.
SUBTITLE_MAX_WIDTH_RATIO = 0.8
# Máximo de linhas visíveis da legenda (o excesso é elidido com "…").
SUBTITLE_MAX_LINES = 3


class PointerWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config if isinstance(config, Config) else Config(config)
        flags = (Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint |
                 Qt.Tool | Qt.WindowTransparentForInput)
        # Como na v1.1: no X11, o WM não deve reposicionar este overlay
        # ao aplicar suas regras de janelas. Não aplicar a outros backends.
        if QApplication.platformName() == "xcb":
            flags |= Qt.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.tela_preta_ativa = False

        # O teletransporte inteligente para múltiplos monitores (Criado na v1.1)
        self.current_screen = QApplication.screenAt(self.cursor().pos())
        if not self.current_screen:
            self.current_screen = QApplication.primaryScreen()
        self._screen_geometry = self.current_screen.geometry()
        self.setGeometry(self._screen_geometry)

        self.is_drawing = False
        self.modes = ["LASER", "LUPA", "SPOTLIGHT"]
        self.mode_index = 0

        # --- A NOVA LÓGICA DO PINCEL ---
        # #28: os traços agora guardam coordenadas GLOBAIS e o nome do monitor
        # onde foram feitos. Antes eram coordenadas locais sem identificação
        # de tela: ao mover o cursor para outro monitor, a janela mudava de
        # geometria e os traços antigos reapareciam em posições erradas.
        self.is_pen_drawing = False
        self.pen_strokes = []      # [{"screen": nome, "points": [QPoint global]}]
        self.current_stroke = []   # Pontos GLOBAIS do traço em andamento
        self.current_stroke_screen = None

        # #27: cache de renderização dos traços JÁ FINALIZADOS. Antes, o
        # paintEvent reconstruía TODOS os QPainterPath de TODOS os traços a
        # cada quadro — a 60 FPS, com o limite de 500 traços × 2000 pontos,
        # isso chegava a ~1 milhão de pontos reprocessados por quadro.
        # Agora eles são rasterizados uma única vez num QPixmap; só o traço
        # em andamento é desenhado ao vivo.
        self._strokes_pixmap = None
        self._strokes_cache_dirty = True
        self._strokes_cache_key = None  # (tela, cor, qtd_tracos, tamanho)
        # -------------------------------

        self.is_recording = False
        self.is_translating = False

        # Cache visual precisa existir ANTES do timer de repintura começar.
        self._visual_cache = {}
        self.refresh_visual_cache()

        self.subtitle_text = ""
        self.subtitle_timer = QTimer()
        self.subtitle_timer.setSingleShot(True)
        self.subtitle_timer.timeout.connect(self.clear_subtitle)

        # Loop infinito (60 FPS) para rastrear o mouse e a tela atual
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_overlay)
        self.timer.start(16)

        log.info(
            "Overlay visual (PointerWindow) inicializado com suporte a multi-telas.")

    def closeEvent(self, event):
        """Para o timer ao fechar para evitar crash por acesso a objeto deletado"""
        self.timer.stop()
        self.subtitle_timer.stop()
        super().closeEvent(event)

    def _update_overlay(self):
        """Rastreia o mouse e pula de monitor se necessário"""
        self._sync_screen()
        self.update()

    def _sync_screen(self):
        """Sincroniza o destino antes de pintar ou ativar uma ferramenta."""
        screen = QApplication.screenAt(self.cursor().pos())
        if screen is None:
            return
        geometry = screen.geometry()
        changed = screen != self.current_screen
        if changed or geometry != self._screen_geometry:
            log.debug("Mudança de monitor detectada. Movendo overlay...")
            # Um gesto contínuo vira segmentos independentes por monitor.
            # Não juntar pontos de telas diferentes num mesmo traço.
            resume_pen = changed and self.is_pen_drawing
            if resume_pen:
                self.set_pen_active(False)
            self.current_screen = screen
            self._screen_geometry = geometry
            self.setGeometry(geometry)
            self._invalidate_strokes_cache()
            if resume_pen:
                self.is_pen_drawing = True
                self.current_stroke_screen = self._screen_key()
            if hasattr(self, 'screen_pixmap') and self.is_drawing and self.modes[self.mode_index] == "LUPA":
                self.screen_pixmap = screen.grabWindow(0)

    # --- SLOTS: Funções que recebem os sinais do HardwareReader ---

    
    
    def set_active(self, active):
        if active:
            self._sync_screen()
        self.is_drawing = active
        if active and self.modes[self.mode_index] == "LUPA":
            self.screen_pixmap = self.current_screen.grabWindow(0)

    def switch_mode(self):
        self._sync_screen()
        self.mode_index = (self.mode_index + 1) % len(self.modes)
        log.info(
            f"Modo do ponteiro alterado para: {self.modes[self.mode_index]}")
        if self.is_drawing and self.modes[self.mode_index] == "LUPA":
            self.screen_pixmap = self.current_screen.grabWindow(0)

    

    def toggle_black_screen(self):
        """Alterna entre mostrar a tela normal e uma tela totalmente preta"""
        self.tela_preta_ativa = not getattr(self, "tela_preta_ativa", False)
        log.info(f"Tela Preta: {'LIGADA' if self.tela_preta_ativa else 'DESLIGADA'}")
        
        if self.tela_preta_ativa:
            # Tira o modo fantasma para podermos capturar e esconder o mouse
            self.setWindowFlag(Qt.WindowTransparentForInput, False)
            self.setCursor(Qt.BlankCursor)
        else:
            # Devolve o modo fantasma para os cliques passarem direto
            self.setWindowFlag(Qt.WindowTransparentForInput, True)
            self.unsetCursor()
        
        # No Linux (principalmente Wayland), alterar Flags de janela exige um .show() para atualizar
        self.show()
        self.update()

    
    def set_pen_active(self, active):
        if active:
            self._sync_screen()
        if active and not self.is_pen_drawing:
            self.current_stroke = []
            self.current_stroke_screen = self._screen_key()

        self.is_pen_drawing = active

        if not active:
            if self.current_stroke:
                # Acabou de desenhar? Salva na memória sem perguntar!
                self.pen_strokes.append({
                    "screen": self.current_stroke_screen,
                    "points": self.current_stroke,
                })
                if len(self.pen_strokes) > MAX_PEN_STROKES:
                    # Descarta os traços mais antigos para limitar o uso de RAM.
                    del self.pen_strokes[:-MAX_PEN_STROKES]
                # #27: o conjunto de traços finalizados mudou — o pixmap
                # precisa ser regerado (uma vez, não a cada quadro).
                self._invalidate_strokes_cache()
            self.current_stroke = []
            self.current_stroke_screen = None

    def _invalidate_strokes_cache(self):
        """Marca o pixmap de traços finalizados para ser regerado (#27)."""
        self._strokes_cache_dirty = True

    def _screen_key(self):
        """Identificador estável do monitor atual (#28)."""
        if self.current_screen:
            return self.current_screen.name()
        return None

    def pen_clear(self):
        self.pen_strokes = []
        self.current_stroke = []
        self.current_stroke_screen = None
        self._invalidate_strokes_cache()
        log.debug("Tela limpa (Pincel apagado via Smart Eraser).")

    def set_recording(self, state):
        if self.is_recording == state:
            return
        self.is_recording = state
        self.show_subtitle(
            "[GRAVANDO]" if state else "[PAUSADO]", duration=2000)

    def set_translating(self, state):
        self.is_translating = state
        self.show_subtitle(
            "[TRADUÇÃO ON]" if state else "[TRADUÇÃO OFF]", duration=2000)

    def show_subtitle(self, text, duration=5000):
        self.subtitle_text = text
        self.subtitle_timer.start(duration)

    def clear_subtitle(self):
        self.subtitle_text = ""

    # --- O MOTOR DE DESENHO ---

    def refresh_visual_cache(self):
        """
        Recarrega as configurações visuais do perfil ativo.

        paintEvent roda a 60 FPS; ler o config (com lock e deepcopy) a cada
        quadro seria desperdício. O cache é invalidado pelo sinal
        config_updated da GUI, via update_visual_config.
        """
        self._visual_cache = {
            "laser_size": self.config.get_visual("laser_size", 30),
            "laser_color": self.config.get_visual("laser_color", "#FF0000"),
            "pincel_color": self.config.get_visual("pincel_color", "#FF0000"),
            "lupa_size": self.config.get_visual("lupa_size", 250),
            "lupa_shape": self.config.get_visual("lupa_shape", "circular"),
            "spotlight_size": self.config.get_visual("spotlight_size", 300),
            "spotlight_opacity": self.config.get_visual("spotlight_opacity", 160),
        }

    def update_visual_config(self):
        """Slot para config_updated: invalida o cache e repinta."""
        self.refresh_visual_cache()
        # A cor do pincel pode ter mudado: o pixmap dos traços finalizados
        # foi rasterizado com a cor antiga e precisa ser refeito (#27).
        self._invalidate_strokes_cache()
        self.update()

    def _global_to_local(self, global_pos, origin=None):
        """
        Converte um ponto GLOBAL para coordenada local da janela.

        BUG encontrado em teste manual (#28/#27): usar self.mapFromGlobal()
        depende de self.pos() — a posição REAL da janela na tela, atualizada
        de forma ASSÍNCRONA pelo window manager depois do setGeometry() (no
        X11/Wayland o resize/move não é instantâneo). Quando o pincel troca
        de monitor, _rebuild_strokes_pixmap() podia rodar ANTES da janela
        terminar de se mover, calculando coordenadas locais erradas — o
        traço ficava "congelado" distorcido no cache até a próxima
        invalidação, mesmo depois da janela já estar no lugar certo.

        A correção: usa a geometria do monitor de DESTINO (já conhecida via
        QScreen, sem depender do estado assíncrono do widget) como origem,
        em vez de perguntar à própria janela onde ela está.
        """
        if origin is None:
            origin = self.current_screen.geometry().topLeft() if self.current_screen else QPoint(0, 0)
        return global_pos - origin

    def _draw_stroke_path(self, painter, pontos, origin=None):
        """Desenha um único traço (lista de QPoint GLOBAIS) no painter."""
        if len(pontos) < 2:
            return
        path = QPainterPath()
        path.moveTo(self._global_to_local(pontos[0], origin))
        for pt in pontos[1:]:
            path.lineTo(self._global_to_local(pt, origin))
        painter.drawPath(path)

    def _rebuild_strokes_pixmap(self, pen):
        """
        #27: rasteriza os traços finalizados do monitor atual em um QPixmap.

        Chamado apenas quando o cache está sujo (novo traço, borracha, troca
        de cor/monitor/tamanho) — não a cada quadro.
        """
        tela_atual = self._screen_key()
        # Origem fixa da tela de destino: nunca depende de self.pos(),
        # eliminando a corrida de timing descrita em _global_to_local.
        origem = self.current_screen.geometry().topLeft() if self.current_screen else QPoint(0, 0)

        self._strokes_pixmap = QPixmap(self.size())
        self._strokes_pixmap.fill(Qt.transparent)

        cache_painter = QPainter(self._strokes_pixmap)
        try:
            cache_painter.setRenderHint(QPainter.Antialiasing)
            cache_painter.setPen(pen)
            for stroke in self.pen_strokes:
                # #28: só os traços feitos NESTE monitor.
                if stroke.get("screen") != tela_atual:
                    continue
                self._draw_stroke_path(cache_painter, stroke.get("points", ()), origem)
        finally:
            cache_painter.end()

        self._strokes_cache_dirty = False
        self._strokes_cache_key = (
            tela_atual, pen.color().name(), len(self.pen_strokes), self.size())

    def paintEvent(self, event):
        # Transforma a coordenada global do mouse na coordenada local da tela atual
        pos = self.mapFromGlobal(self.cursor().pos())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        v_config = self._visual_cache
        # Se a tela preta estiver ativada, pinta TUDO de preto e encerra o desenho!
        if getattr(self, "tela_preta_ativa", False):
            painter.fillRect(self.rect(), Qt.black)
            painter.end()
            return
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

                src_rect = QRect(local_x - size//4, local_y -
                                 size//4, size//2, size//2)
                dst_rect = QRect(pos.x() - size//2,
                                 pos.y() - size//2, size, size)

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
        # #28: pontos são armazenados em coordenadas GLOBAIS e convertidos
        # para locais só na hora de pintar. Assim eles permanecem ancorados
        # ao monitor correto mesmo depois de a janela mudar de geometria.
        global_pos_pen = self.cursor().pos()
        if self.is_pen_drawing:
            # Só salva o ponto se o mouse realmente andou (evita lixo na memória)
            if not self.current_stroke or self.current_stroke[-1] != global_pos_pen:
                # #27: limita o tamanho de um traço individual.
                if len(self.current_stroke) < MAX_POINTS_PER_STROKE:
                    self.current_stroke.append(global_pos_pen)

        if self.pen_strokes or self.current_stroke:
            p_color = QColor(v_config.get("pincel_color", "#FF0000"))
            # Pincel mais suave e redondo
            pen = QPen(p_color, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)

            tela_atual = self._screen_key()

            # #27: os traços FINALIZADOS vêm de um pixmap já rasterizado.
            # A chave detecta mudanças que exigem regerar (troca de monitor,
            # de cor, de quantidade de traços ou de tamanho da janela).
            chave_atual = (
                tela_atual, p_color.name(), len(self.pen_strokes), self.size())
            if self._strokes_cache_dirty or self._strokes_cache_key != chave_atual:
                self._rebuild_strokes_pixmap(pen)

            if self._strokes_pixmap is not None:
                painter.drawPixmap(0, 0, self._strokes_pixmap)

            # Só o traço EM ANDAMENTO é desenhado ao vivo a cada quadro —
            # ele é curto e muda constantemente, então não vale cachear.
            if self.current_stroke and self.current_stroke_screen == tela_atual:
                painter.setPen(pen)
                self._draw_stroke_path(painter, self.current_stroke)

        # 3. Desenhar a Legenda (Transcrição/Tradução)
        # #26: antes a caixa era calculada como UMA linha só, com
        # fm.boundingRect(texto) — uma fala longa gerava uma caixa mais larga
        # que o monitor e o texto ficava cortado nas duas pontas.
        if self.subtitle_text:
            font = QFont("Arial", 24, QFont.Bold)
            painter.setFont(font)
            fm = QFontMetrics(font)

            padding_h, padding_v = 20, 10
            max_text_width = int(self.width() * SUBTITLE_MAX_WIDTH_RATIO) - 2 * padding_h
            max_text_height = fm.lineSpacing() * SUBTITLE_MAX_LINES

            # Mede o texto COM quebra de linha, respeitando a largura máxima.
            flags = Qt.AlignCenter | Qt.TextWordWrap
            text_rect = fm.boundingRect(
                QRect(0, 0, max_text_width, max_text_height), flags, self.subtitle_text)

            # Elide o excesso se passar do número máximo de linhas.
            texto = self.subtitle_text
            if text_rect.height() > max_text_height:
                text_rect.setHeight(max_text_height)

            bg_rect = QRect(
                (self.width() - text_rect.width()) // 2 - padding_h,
                self.height() - 100,
                text_rect.width() + 2 * padding_h,
                text_rect.height() + 2 * padding_v,
            )
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 10, 10)

            painter.setPen(Qt.white)
            painter.drawText(bg_rect, flags, texto)
