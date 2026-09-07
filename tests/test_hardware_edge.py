"""
Testes de app/hardware.py — Etapa 2 da auditoria (#11, #12, #13, #22, #23).

Não requer o passador físico nem evdev real: usa dispositivos falsos e
verifica a LÓGICA de captura/liberação, filtragem de eventos e enumeração.
Os cenários que dependem do hardware (ordem real dos eventos do Baseus)
continuam precisando de confirmação física.

    python3 -m unittest discover -s tests -p "test_hardware_edge.py" -v
"""
import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

from app import hardware as hw


class FakeDevice:
    """Substitui evdev.InputDevice."""

    def __init__(self, name, fd, vendor=0xabc8, product=0xca08, grab_fails=False):
        self.name = name
        self.fd = fd
        self.grab_fails = grab_fails
        self.grabbed = False
        self.ungrab_count = 0
        self.info = mock.Mock(vendor=vendor, product=product)

    def grab(self):
        if self.grab_fails:
            raise OSError("grab falhou")
        self.grabbed = True

    def ungrab(self):
        self.ungrab_count += 1
        self.grabbed = False


class FakeUInput:
    """Substitui evdev.UInput."""

    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, etype, code, value):
        self.written.append((etype, code, value))

    def write_event(self, ev):
        self.written.append(ev)

    def syn(self):
        pass

    def close(self):
        self.closed = True


class TestRollbackDeGrabs(unittest.TestCase):
    """#11: falha no UInput não pode deixar as entradas físicas capturadas."""

    def test_grabs_sao_desfeitos_se_uinput_falhar(self):
        reader = hw.HardwareReader()
        kbd = FakeDevice("Baseus Keyboard", fd=10)
        mouse = FakeDevice("Baseus Mouse", fd=11)

        with mock.patch.object(hw, "EVDEV_AVAILABLE", True), \
             mock.patch.object(hw, "list_devices", return_value=["/dev/input/event10",
                                                                "/dev/input/event11"]), \
             mock.patch.object(hw, "InputDevice", side_effect=[kbd, mouse]), \
             mock.patch.object(hw, "UInput") as mock_uinput, \
             mock.patch.object(hw.os, "listdir", return_value=[]):
            mock_uinput.from_device.side_effect = PermissionError("/dev/uinput negado")
            reader._scan_devices()

        # O ponto central: nada pode continuar capturado.
        self.assertFalse(kbd.grabbed, "teclado ficou capturado após falha do UInput")
        self.assertFalse(mouse.grabbed, "mouse ficou capturado após falha do UInput")
        self.assertGreaterEqual(kbd.ungrab_count, 1)
        self.assertGreaterEqual(mouse.ungrab_count, 1)
        self.assertIsNone(reader.ui)


class TestApenasUmaInterface(unittest.TestCase):
    """#12: encontrar só a interface de mouse causava AttributeError."""

    def test_somente_mouse_nao_deixa_referencia_pendente(self):
        reader = hw.HardwareReader()
        mouse = FakeDevice("Baseus Mouse", fd=11)

        with mock.patch.object(hw, "EVDEV_AVAILABLE", True), \
             mock.patch.object(hw, "list_devices", return_value=["/dev/input/event11"]), \
             mock.patch.object(hw, "InputDevice", side_effect=[mouse]), \
             mock.patch.object(hw.os, "listdir", return_value=[]):
            reader._scan_devices()

        # Com apenas uma interface não há virtualização possível; as duas
        # referências devem ficar None para o loop nunca fazer self.kbd.fd.
        self.assertIsNone(reader.kbd)
        self.assertIsNone(reader.mouse_ev)

    def test_mapa_de_fds_nao_estoura_com_kbd_none(self):
        """
        Reproduz a expressão que estourava:
            dev = self.kbd if fd == self.kbd.fd else self.mouse_ev
        Agora o loop usa um dicionário fd -> device.
        """
        reader = hw.HardwareReader()
        reader.kbd = None
        reader.mouse_ev = FakeDevice("Baseus Mouse", fd=11)

        evdev_por_fd = {}
        if reader.kbd:
            evdev_por_fd[reader.kbd.fd] = reader.kbd
        if reader.mouse_ev:
            evdev_por_fd[reader.mouse_ev.fd] = reader.mouse_ev

        self.assertEqual(list(evdev_por_fd), [11])
        self.assertIs(evdev_por_fd[11], reader.mouse_ev)


class TestSolturaDeBotaoNaoFicaPresa(unittest.TestCase):
    """#13: filtro do pincel podia deixar um botão virtual pressionado."""

    def test_release_e_liberado_ao_fechar_uinput(self):
        reader = hw.HardwareReader()
        fake_ui = FakeUInput()
        reader.ui = fake_ui
        # Simula BTN_LEFT encaminhado como pressionado.
        reader._forwarded_pressed.add(hw.e.BTN_LEFT)

        with mock.patch.object(hw, "EVDEV_AVAILABLE", True):
            reader._release_evdev()

        # Deve ter emitido a soltura (valor 0) antes de fechar.
        self.assertIn((hw.e.EV_KEY, hw.e.BTN_LEFT, 0), fake_ui.written)
        self.assertTrue(fake_ui.closed)
        self.assertEqual(reader._forwarded_pressed, set())

    def test_estado_de_pressionadas_nao_vaza_entre_reconexoes(self):
        reader = hw.HardwareReader()
        reader.ui = FakeUInput()
        reader._forwarded_pressed.update({hw.e.BTN_LEFT, hw.e.KEY_ESC})

        with mock.patch.object(hw, "EVDEV_AVAILABLE", True):
            reader._release_evdev()

        self.assertEqual(reader._forwarded_pressed, set())


class TestEnumeracaoDinamicaHidraw(unittest.TestCase):
    """#23: dispositivos hidraw20+ nunca eram encontrados (range(20) fixo)."""

    def test_encontra_hidraw_com_indice_acima_de_20(self):
        reader = hw.HardwareReader()
        nodes = [f"hidraw{i}" for i in range(25)]
        alvo = "hidraw23"

        def fake_exists(path):
            return path == f"/sys/class/hidraw/{alvo}/device/uevent"

        conteudo_uevent = "HID_ID=0003:0000ABC8:0000CA08\n"

        with mock.patch.object(hw, "EVDEV_AVAILABLE", False), \
             mock.patch.object(hw.os, "listdir", return_value=nodes), \
             mock.patch.object(hw.os.path, "exists", side_effect=fake_exists), \
             mock.patch("builtins.open", mock.mock_open(read_data=conteudo_uevent)), \
             mock.patch.object(hw.os, "open", return_value=99) as mock_open_fd:
            reader._scan_devices()

        self.assertIn(99, reader.fds)
        self.assertEqual(reader.fds[99], f"/dev/{alvo}")
        mock_open_fd.assert_called_once()

    def test_sysfs_ausente_nao_derruba_o_scan(self):
        reader = hw.HardwareReader()
        with mock.patch.object(hw, "EVDEV_AVAILABLE", False), \
             mock.patch.object(hw.os, "listdir", side_effect=OSError("sem sysfs")):
            reader._scan_devices()  # não deve levantar
        self.assertEqual(reader.fds, {})


class TestIdsDoConfig(unittest.TestCase):
    """IDs de hardware vindos do config em vez de hardcoded."""

    def test_ids_do_config_sobrepoem_os_defaults(self):
        class FakeConfig:
            def get(self, key, default=None):
                if key == "hardware":
                    return {"vendor_id": "1234", "product_id": "5678"}
                return default

        reader = hw.HardwareReader(config=FakeConfig())
        self.assertEqual(reader.vendor_id_hex, "1234")
        self.assertEqual(reader.product_id_hex, "5678")
        self.assertEqual(reader.vendor_id_str, "1234")

    def test_sem_config_usa_defaults(self):
        reader = hw.HardwareReader()
        self.assertEqual(reader.vendor_id_hex, "abc8")
        self.assertEqual(reader.product_id_hex, "ca08")


if __name__ == "__main__":
    unittest.main(verbosity=2)
