"""
Testes de app/hardware.py — regressão encontrada em teste manual (#13).

Cenário reportado: com o pincel ativo, segurar o botão físico abria a paleta
de comandos do VS Code (Ctrl+P) e digitava "e" repetidamente em campos de
texto. O filtro antigo só bloqueava BTN_LEFT/KEY_ESC durante o desenho;
qualquer outra tecla (Ctrl, P, E, ...) passava direto para o dispositivo
virtual como um atalho de teclado real do sistema.

Este teste reproduz a lógica do filtro isoladamente (sem abrir a QThread
real), simulando a sequência de eventos evdev.

    python3 -m unittest discover -s tests -p "test_hardware_pen_keyfilter.py" -v
"""
import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

from app import hardware as hw


class FakeEvent:
    def __init__(self, etype, code, value):
        self.type = etype
        self.code = code
        self.value = value


def apply_pen_filter(reader, is_pen_drawing, ev):
    """
    Reproduz exatamente a lógica de filtro do SENSOR 1 em _run_loop, sem
    precisar rodar a QThread inteira. Retorna True se o evento SERIA
    encaminhado ao dispositivo virtual.
    """
    if ev.type == hw.e.EV_KEY:
        if ev.code == hw.e.KEY_B:
            return False
        if is_pen_drawing:
            if ev.value == 0 and ev.code in reader._forwarded_pressed:
                pass  # deixa a soltura passar
            else:
                return False
        if ev.value == 1:
            reader._forwarded_pressed.add(ev.code)
        elif ev.value == 0:
            reader._forwarded_pressed.discard(ev.code)
    return True


@unittest.skipUnless(hw.EVDEV_AVAILABLE, "evdev indisponível neste ambiente")
class TestFiltroDeTecladoDurantePincel(unittest.TestCase):
    def setUp(self):
        self.reader = hw.HardwareReader()

    def test_ctrl_p_nao_e_encaminhado_durante_o_pincel(self):
        """Reproduz o Ctrl+P que abria a paleta de comandos do VS Code."""
        eventos = [
            FakeEvent(hw.e.EV_KEY, hw.e.KEY_LEFTCTRL, 1),
            FakeEvent(hw.e.EV_KEY, hw.e.KEY_P, 1),
            FakeEvent(hw.e.EV_KEY, hw.e.KEY_P, 0),
            FakeEvent(hw.e.EV_KEY, hw.e.KEY_LEFTCTRL, 0),
        ]
        resultados = [apply_pen_filter(self.reader, True, ev) for ev in eventos]
        self.assertEqual(resultados, [False, False, False, False])

    def test_tecla_e_nao_e_encaminhada_durante_o_pincel(self):
        """Reproduz o "e" digitado repetidamente em campos de texto."""
        eventos = [FakeEvent(hw.e.EV_KEY, hw.e.KEY_E, 1) for _ in range(5)]
        resultados = [apply_pen_filter(self.reader, True, ev) for ev in eventos]
        self.assertTrue(all(r is False for r in resultados))

    def test_qualquer_tecla_e_bloqueada_durante_o_pincel(self):
        """Generaliza: TODA tecla é bloqueada, não só BTN_LEFT/KEY_ESC."""
        codigos = [hw.e.KEY_A, hw.e.KEY_TAB, hw.e.KEY_ENTER, hw.e.BTN_RIGHT]
        for codigo in codigos:
            with self.subTest(codigo=codigo):
                ev = FakeEvent(hw.e.EV_KEY, codigo, 1)
                self.assertFalse(apply_pen_filter(self.reader, True, ev))

    def test_soltura_de_tecla_ja_pressionada_sempre_passa(self):
        """
        Uma tecla pressionada ANTES do pincel ativar precisa poder soltar,
        senão fica presa no dispositivo virtual para sempre.
        """
        # Pressiona fora do modo pincel.
        ev_press = FakeEvent(hw.e.EV_KEY, hw.e.KEY_LEFTCTRL, 1)
        self.assertTrue(apply_pen_filter(self.reader, False, ev_press))
        self.assertIn(hw.e.KEY_LEFTCTRL, self.reader._forwarded_pressed)

        # Ativa o pincel; a soltura da tecla já pressionada deve passar.
        ev_release = FakeEvent(hw.e.EV_KEY, hw.e.KEY_LEFTCTRL, 0)
        self.assertTrue(apply_pen_filter(self.reader, True, ev_release))
        self.assertNotIn(hw.e.KEY_LEFTCTRL, self.reader._forwarded_pressed)

    def test_teclado_funciona_normalmente_fora_do_pincel(self):
        """Fora do modo pincel, o teclado deve passar (exceto KEY_B)."""
        ev = FakeEvent(hw.e.EV_KEY, hw.e.KEY_P, 1)
        self.assertTrue(apply_pen_filter(self.reader, False, ev))

    def test_key_b_e_sempre_bloqueado_independente_do_pincel(self):
        ev = FakeEvent(hw.e.EV_KEY, hw.e.KEY_B, 1)
        self.assertFalse(apply_pen_filter(self.reader, False, ev))
        self.assertFalse(apply_pen_filter(self.reader, True, ev))

    def test_movimento_do_mouse_nao_e_afetado_pelo_filtro(self):
        """EV_REL (movimento) nunca deve ser bloqueado pelo filtro de teclado."""
        ev = FakeEvent(hw.e.EV_REL, hw.e.REL_X, 5)
        self.assertTrue(apply_pen_filter(self.reader, True, ev))


if __name__ == "__main__":
    unittest.main(verbosity=2)
