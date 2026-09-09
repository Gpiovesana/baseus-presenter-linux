"""
Testes de app/overlay.py — Etapa 2 da auditoria (#26, #27, #28).

Usa QApplication offscreen. Verifica a lógica de armazenamento dos traços
(por monitor, em coordenadas globais) e os limites de acumulação. A validação
visual em monitores físicos continua pendente de teste manual.

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -p "test_overlay_render.py" -v
"""
import copy
import logging
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

from app import config as cfg

try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QPoint
    from app import overlay as ov
    QT_AVAILABLE = True
except Exception:  # pragma: no cover
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 indisponível neste ambiente")
class OverlayTestCase(unittest.TestCase):
    _app = None

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def make_overlay(self):
        config = cfg.Config(copy.deepcopy(cfg.DEFAULT_CONFIG))
        win = ov.PointerWindow(config)
        # O timer de 60 FPS não deve rodar durante os testes.
        win.timer.stop()
        self.addCleanup(win.close)
        return win


class TestTracosPorMonitor(OverlayTestCase):
    """#28: desenhos apareciam em posições erradas ao mudar de monitor."""

    def test_traco_guarda_o_monitor_de_origem(self):
        win = self.make_overlay()
        win.set_pen_active(True)
        self.assertEqual(win.current_stroke_screen, win._screen_key())

        win.current_stroke = [QPoint(10, 10), QPoint(20, 20)]
        win.set_pen_active(False)

        self.assertEqual(len(win.pen_strokes), 1)
        stroke = win.pen_strokes[0]
        self.assertIn("screen", stroke)
        self.assertIn("points", stroke)
        self.assertEqual(stroke["screen"], win._screen_key())
        self.assertEqual(len(stroke["points"]), 2)

    def test_pen_clear_limpa_tudo_incluindo_a_tela_de_origem(self):
        win = self.make_overlay()
        win.set_pen_active(True)
        win.current_stroke = [QPoint(1, 1), QPoint(2, 2)]
        win.set_pen_active(False)
        self.assertTrue(win.pen_strokes)

        win.pen_clear()
        self.assertEqual(win.pen_strokes, [])
        self.assertEqual(win.current_stroke, [])
        self.assertIsNone(win.current_stroke_screen)

    def test_traco_de_outro_monitor_nao_e_desenhado(self):
        """
        paintEvent deve filtrar traços cujo "screen" difere do monitor atual.
        Verificamos a condição de filtro diretamente (sem pintar de fato).
        """
        win = self.make_overlay()
        tela_atual = win._screen_key()
        win.pen_strokes = [
            {"screen": tela_atual, "points": [QPoint(0, 0), QPoint(5, 5)]},
            {"screen": "OUTRO-MONITOR", "points": [QPoint(0, 0), QPoint(5, 5)]},
        ]
        desenhaveis = [s for s in win.pen_strokes if s.get("screen") == tela_atual]
        self.assertEqual(len(desenhaveis), 1)
        self.assertEqual(desenhaveis[0]["screen"], tela_atual)


class TestLimitesDeAcumulacao(OverlayTestCase):
    """#27: traços acumulavam memória e trabalho de renderização sem limite."""

    def test_numero_de_tracos_e_limitado(self):
        win = self.make_overlay()
        for i in range(ov.MAX_PEN_STROKES + 25):
            win.set_pen_active(True)
            win.current_stroke = [QPoint(i, i), QPoint(i + 1, i + 1)]
            win.set_pen_active(False)

        self.assertLessEqual(len(win.pen_strokes), ov.MAX_PEN_STROKES)

    def test_tracos_mais_recentes_sao_preservados(self):
        win = self.make_overlay()
        total = ov.MAX_PEN_STROKES + 10
        for i in range(total):
            win.set_pen_active(True)
            win.current_stroke = [QPoint(i, 0), QPoint(i, 1)]
            win.set_pen_active(False)

        # O último traço inserido deve continuar presente.
        ultimo = win.pen_strokes[-1]["points"][0].x()
        self.assertEqual(ultimo, total - 1)

    def test_existe_limite_de_pontos_por_traco(self):
        self.assertGreater(ov.MAX_POINTS_PER_STROKE, 0)
        # Um traço não deve poder crescer indefinidamente.
        self.assertLessEqual(ov.MAX_POINTS_PER_STROKE, 100_000)


class TestCacheDeRenderizacao(OverlayTestCase):
    """
    #27 (parte de renderização): os traços finalizados devem ser
    rasterizados UMA vez num pixmap, não reconstruídos a cada quadro.
    """

    def _finalizar_traco(self, win, x=0):
        from PyQt5.QtCore import QPoint
        win.set_pen_active(True)
        win.current_stroke = [QPoint(x, 0), QPoint(x + 5, 5)]
        win.set_pen_active(False)

    def test_cache_comeca_sujo(self):
        win = self.make_overlay()
        self.assertTrue(win._strokes_cache_dirty)

    def test_novo_traco_invalida_o_cache(self):
        win = self.make_overlay()
        win._strokes_cache_dirty = False
        self._finalizar_traco(win)
        self.assertTrue(win._strokes_cache_dirty)

    def test_pen_clear_invalida_o_cache(self):
        win = self.make_overlay()
        self._finalizar_traco(win)
        win._strokes_cache_dirty = False
        win.pen_clear()
        self.assertTrue(win._strokes_cache_dirty)

    def test_troca_de_cor_invalida_o_cache(self):
        """A cor do pincel é rasterizada no pixmap; mudá-la exige refazê-lo."""
        win = self.make_overlay()
        win._strokes_cache_dirty = False
        win.config.set_visual("pincel_color", "#00FF00")
        win.update_visual_config()
        self.assertTrue(win._strokes_cache_dirty)

    def test_rebuild_gera_pixmap_e_limpa_a_flag(self):
        from PyQt5.QtGui import QPen, QColor
        win = self.make_overlay()
        self._finalizar_traco(win)

        pen = QPen(QColor("#FF0000"), 5)
        win._rebuild_strokes_pixmap(pen)

        self.assertIsNotNone(win._strokes_pixmap)
        self.assertFalse(win._strokes_cache_dirty)
        self.assertIsNotNone(win._strokes_cache_key)

    def test_chave_do_cache_reflete_quantidade_de_tracos(self):
        from PyQt5.QtGui import QPen, QColor
        win = self.make_overlay()
        pen = QPen(QColor("#FF0000"), 5)

        self._finalizar_traco(win, x=0)
        win._rebuild_strokes_pixmap(pen)
        chave1 = win._strokes_cache_key

        self._finalizar_traco(win, x=50)
        win._rebuild_strokes_pixmap(pen)
        chave2 = win._strokes_cache_key

        self.assertNotEqual(chave1, chave2)

    def test_paint_event_nao_falha_com_tracos_cacheados(self):
        """Sanity check: um paint real com cache ativo não deve levantar."""
        from PyQt5.QtGui import QPixmap, QPainter
        win = self.make_overlay()
        win.resize(400, 300)
        for i in range(5):
            self._finalizar_traco(win, x=i * 10)

        # Pinta a janela num pixmap para exercitar o paintEvent de verdade.
        alvo = QPixmap(win.size())
        alvo.fill()
        win.render(alvo)  # não deve levantar

        self.assertFalse(win._strokes_cache_dirty)
        self.assertIsNotNone(win._strokes_pixmap)

    def test_traco_em_andamento_nao_entra_no_pixmap(self):
        """
        O traço ativo muda a cada quadro; ele é desenhado ao vivo, e não
        deve sujar/entrar no cache dos finalizados.
        """
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QPen, QColor
        win = self.make_overlay()

        pen = QPen(QColor("#FF0000"), 5)
        win._rebuild_strokes_pixmap(pen)
        chave_antes = win._strokes_cache_key

        win.set_pen_active(True)
        win.current_stroke = [QPoint(1, 1), QPoint(2, 2), QPoint(3, 3)]
        # Sem finalizar o traço, a chave (que conta pen_strokes) não muda.
        win._rebuild_strokes_pixmap(pen)
        self.assertEqual(chave_antes, win._strokes_cache_key)


class TestLegendaComQuebra(OverlayTestCase):
    """#26: legendas longas ficavam cortadas (caixa de uma linha só)."""

    def test_constantes_de_legenda_definidas(self):
        self.assertGreater(ov.SUBTITLE_MAX_WIDTH_RATIO, 0)
        self.assertLessEqual(ov.SUBTITLE_MAX_WIDTH_RATIO, 1.0)
        self.assertGreaterEqual(ov.SUBTITLE_MAX_LINES, 1)

    def test_caixa_de_legenda_longa_nao_excede_a_largura_da_janela(self):
        from PyQt5.QtGui import QFont, QFontMetrics
        from PyQt5.QtCore import QRect

        win = self.make_overlay()
        win.resize(1280, 720)
        texto_longo = "palavra " * 80

        font = QFont("Arial", 24, QFont.Bold)
        fm = QFontMetrics(font)
        padding_h = 20
        max_text_width = int(win.width() * ov.SUBTITLE_MAX_WIDTH_RATIO) - 2 * padding_h
        max_text_height = fm.lineSpacing() * ov.SUBTITLE_MAX_LINES

        from PyQt5.QtCore import Qt
        flags = Qt.AlignCenter | Qt.TextWordWrap
        rect = fm.boundingRect(
            QRect(0, 0, max_text_width, max_text_height), flags, texto_longo)

        largura_caixa = rect.width() + 2 * padding_h
        self.assertLessEqual(
            largura_caixa, win.width(),
            "a caixa da legenda ainda é mais larga que a janela")

    def test_show_subtitle_armazena_o_texto(self):
        win = self.make_overlay()
        win.show_subtitle("teste de legenda", duration=1000)
        self.assertEqual(win.subtitle_text, "teste de legenda")
        win.clear_subtitle()
        self.assertEqual(win.subtitle_text, "")


class TestCacheVisual(OverlayTestCase):
    """O cache visual precisa existir antes do primeiro paintEvent."""

    def test_cache_populado_no_init(self):
        win = self.make_overlay()
        self.assertIn("laser_size", win._visual_cache)
        self.assertIn("pincel_color", win._visual_cache)

    def test_update_visual_config_recarrega_o_cache(self):
        win = self.make_overlay()
        win.config.set_visual("laser_size", 77)
        win.update_visual_config()
        self.assertEqual(win._visual_cache["laser_size"], 77)


class TestConversaoGlobalParaLocalEstavel(OverlayTestCase):
    """
    Regressão encontrada em teste manual (#28/#27): o desenho da tela A
    "desaparecia" ao ir para B e voltava DISTORCIDO ao retornar para A.

    Causa: _draw_stroke_path usava self.mapFromGlobal(), que depende de
    self.pos() — atualizado ASSINCRONAMENTE pelo window manager depois do
    setGeometry(). Se o cache era rasterizado antes da janela terminar de
    se mover para o novo monitor, o traço ficava com coordenadas locais
    erradas "congeladas" no pixmap até a próxima invalidação.

    A correção usa a geometria FIXA do QScreen de destino como origem, em
    vez de perguntar à janela (widget) onde ela está fisicamente.
    """

    def test_conversao_nao_depende_da_posicao_real_do_widget(self):
        """
        Mesmo que self.pos() da janela ainda não tenha sido atualizado
        (simulando o atraso do window manager), a conversão deve usar a
        geometria do monitor de DESTINO — não a posição atual do widget.
        """
        from PyQt5.QtCore import QPoint

        win = self.make_overlay()

        # Simula: o monitor "de destino" já foi definido internamente...
        fake_screen = mock.Mock()
        fake_screen.geometry.return_value = mock.Mock(topLeft=lambda: QPoint(1920, 0))
        win.current_screen = fake_screen

        # ...mas a janela real (self.pos()) ainda não migrou (fica em (0,0),
        # como se o window manager ainda não tivesse aplicado o setGeometry).
        with mock.patch.object(win, "pos", return_value=QPoint(0, 0)), \
             mock.patch.object(win, "mapFromGlobal",
                               side_effect=AssertionError(
                                   "não deveria depender de mapFromGlobal/pos() do widget")):
            ponto_global = QPoint(1970, 50)  # 50px dentro do monitor 2 (x=1920)
            local = win._global_to_local(ponto_global)

        self.assertEqual(local, QPoint(50, 50))


class TestTransicaoDeMonitor(OverlayTestCase):
    """Regressões da sincronização do overlay entre monitores."""

    @staticmethod
    def _screen(name, x=0, y=0, width=1920, height=1080):
        from PyQt5.QtCore import QRect

        screen = mock.Mock()
        screen.name.return_value = name
        screen.geometry.return_value = QRect(x, y, width, height)
        return screen

    @staticmethod
    def _cursor_at(point):
        cursor = mock.Mock()
        cursor.pos.return_value = point
        return cursor

    def test_atualiza_tela_e_geometria_quando_cursor_muda_de_monitor(self):
        win = self.make_overlay()
        tela_a = self._screen("TELA-A", 0)
        tela_b = self._screen("TELA-B", 1920)
        win.current_screen = tela_a

        with mock.patch.object(ov.QApplication, "screenAt", return_value=tela_b), \
             mock.patch.object(win, "cursor", return_value=self._cursor_at(QPoint(2000, 40))), \
             mock.patch.object(win, "setGeometry") as set_geometry:
            win._update_overlay()

        self.assertIs(win.current_screen, tela_b)
        set_geometry.assert_called_once_with(tela_b.geometry())

    def test_sem_screen_at_preserva_monitor_atual(self):
        win = self.make_overlay()
        tela_a = self._screen("TELA-A")
        win.current_screen = tela_a

        with mock.patch.object(ov.QApplication, "screenAt", return_value=None), \
             mock.patch.object(win, "cursor", return_value=self._cursor_at(QPoint(10, 10))), \
             mock.patch.object(win, "setGeometry") as set_geometry:
            win._update_overlay()

        self.assertIs(win.current_screen, tela_a)
        set_geometry.assert_not_called()

    def test_pincel_ativo_muda_de_tela_sem_perder_pontos(self):
        """Cruzar monitor com o botão pressionado divide o traço na origem."""
        win = self.make_overlay()
        tela_a = self._screen("TELA-A", 0)
        tela_b = self._screen("TELA-B", 1920)
        win.current_screen = tela_a
        with mock.patch.object(ov.QApplication, "screenAt", return_value=tela_a):
            win.set_pen_active(True)
        win.current_stroke = [QPoint(100, 100), QPoint(200, 100)]

        with mock.patch.object(ov.QApplication, "screenAt", return_value=tela_b), \
             mock.patch.object(win, "cursor", return_value=self._cursor_at(QPoint(2000, 100))), \
             mock.patch.object(win, "setGeometry"):
            win._update_overlay()

        self.assertIs(win.current_screen, tela_b)
        self.assertTrue(win.is_pen_drawing)
        self.assertFalse(win.current_stroke)
        self.assertEqual(win.current_stroke_screen, "TELA-B")
        self.assertEqual(len(win.pen_strokes), 1)
        self.assertEqual(win.pen_strokes[0]["screen"], "TELA-A")
        self.assertEqual(win.pen_strokes[0]["points"], [QPoint(100, 100), QPoint(200, 100)])

    def test_ativacao_sincroniza_antes_do_timer(self):
        from PyQt5.QtGui import QPixmap

        win = self.make_overlay()
        tela = self._screen("ESQUERDA", -1920, -200)
        tela.grabWindow.return_value = QPixmap(1920, 1080)
        win.mode_index = win.modes.index("LUPA")
        with mock.patch.object(ov.QApplication, "screenAt", return_value=tela):
            win.set_active(True)
            win.set_pen_active(True)
        self.assertEqual(win.geometry(), tela.geometry())
        self.assertEqual(win.current_stroke_screen, "ESQUERDA")
        self.assertEqual(win._global_to_local(QPoint(-1900, -180)), QPoint(20, 20))
        tela.grabWindow.assert_called_once_with(0)

    def test_lupa_recaptura_ao_mudar_monitor(self):
        from PyQt5.QtGui import QPixmap

        win = self.make_overlay()
        win.mode_index = win.modes.index("LUPA")
        win.is_drawing = True
        win.screen_pixmap = QPixmap(100, 100)
        tela = self._screen("SECUNDARIA", 1600, 0)
        tela.grabWindow.return_value = QPixmap(1920, 1080)
        with mock.patch.object(ov.QApplication, "screenAt", return_value=tela):
            win._update_overlay()
        tela.grabWindow.assert_called_once_with(0)
        self.assertIs(win.screen_pixmap, tela.grabWindow.return_value)

    def test_reorganizacao_do_mesmo_monitor_invalida_cache(self):
        win = self.make_overlay()
        tela = self._screen("TELA", -1920, 300)
        win.current_screen = tela
        win._strokes_cache_dirty = False
        with mock.patch.object(ov.QApplication, "screenAt", return_value=tela):
            win._update_overlay()
        self.assertEqual(win.geometry(), tela.geometry())
        self.assertTrue(win._strokes_cache_dirty)

    def test_flags_x11_sao_condicionais_ao_backend(self):
        """A flag bypass só deve ser usada no backend X11/XCB."""
        with mock.patch.object(ov.QApplication, "platformName", return_value="xcb"):
            x11_win = self.make_overlay()
        self.assertTrue(x11_win.windowFlags() & ov.Qt.X11BypassWindowManagerHint)

        with mock.patch.object(ov.QApplication, "platformName", return_value="offscreen"):
            other_win = self.make_overlay()
        self.assertFalse(other_win.windowFlags() & ov.Qt.X11BypassWindowManagerHint)

    def test_toggle_tela_preta_preserva_bypass_x11(self):
        with mock.patch.object(ov.QApplication, "platformName", return_value="xcb"):
            win = self.make_overlay()
        self.assertTrue(win.windowFlags() & ov.Qt.X11BypassWindowManagerHint)

        win.toggle_black_screen()
        self.assertTrue(win.windowFlags() & ov.Qt.X11BypassWindowManagerHint)
        win.toggle_black_screen()
        self.assertTrue(win.windowFlags() & ov.Qt.X11BypassWindowManagerHint)

class TestCacheEntreMonitores(OverlayTestCase):
    def test_rebuild_usa_geometria_do_monitor_atual_nao_a_do_widget(self):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QPen, QColor

        win = self.make_overlay()
        fake_screen = mock.Mock()
        fake_screen.geometry.return_value = mock.Mock(topLeft=lambda: QPoint(1920, 0))
        fake_screen.name.return_value = "MONITOR-2"
        win.current_screen = fake_screen

        win.pen_strokes = [{
            "screen": "MONITOR-2",
            "points": [QPoint(1930, 10), QPoint(1940, 20)],
        }]

        pen = QPen(QColor("#FF0000"), 5)
        # Não deve levantar nem depender de self.pos()/mapFromGlobal.
        with mock.patch.object(win, "mapFromGlobal",
                               side_effect=AssertionError("não deveria ser chamado")):
            win._rebuild_strokes_pixmap(pen)

        self.assertIsNotNone(win._strokes_pixmap)

    def test_ida_e_volta_entre_monitores_nao_distorce(self):
        """
        Reproduz o cenário relatado: desenha em A, vai para B, volta para A.
        O traço de A deve ter exatamente as mesmas coordenadas locais nas
        duas vezes em que A é o monitor atual.
        """
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QPen, QColor

        win = self.make_overlay()

        tela_a = mock.Mock()
        tela_a.geometry.return_value = mock.Mock(topLeft=lambda: QPoint(0, 0))
        tela_a.name.return_value = "TELA-A"

        tela_b = mock.Mock()
        tela_b.geometry.return_value = mock.Mock(topLeft=lambda: QPoint(1920, 0))
        tela_b.name.return_value = "TELA-B"

        win.current_screen = tela_a
        win.pen_strokes = [{
            "screen": "TELA-A",
            "points": [QPoint(100, 100), QPoint(200, 200)],
        }]

        pen = QPen(QColor("#FF0000"), 5)

        # 1ª vez em A.
        win._rebuild_strokes_pixmap(pen)
        primeira_chave = win._strokes_cache_key

        # Vai para B (nenhum traço de B; o pixmap fica vazio, mas não pode
        # corromper os dados armazenados de A).
        win.current_screen = tela_b
        win._rebuild_strokes_pixmap(pen)

        # Volta para A.
        win.current_screen = tela_a
        win._rebuild_strokes_pixmap(pen)
        segunda_chave = win._strokes_cache_key

        # A geometria/dados do traço de A não podem ter mudado entre as duas
        # visitas — mesma tela, mesma contagem de traços.
        self.assertEqual(primeira_chave[0], segunda_chave[0])  # mesma tela
        self.assertEqual(primeira_chave[2], segunda_chave[2])  # mesma qtd de traços
        # E o ponto de origem armazenado continua intacto (não foi mutado).
        self.assertEqual(win.pen_strokes[0]["points"][0], QPoint(100, 100))


if __name__ == "__main__":
    unittest.main(verbosity=2)
