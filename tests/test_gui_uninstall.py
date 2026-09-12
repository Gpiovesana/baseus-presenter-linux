"""O botão abre um processo separado, sem desinstalar ou encerrar por si só."""
from unittest import mock
from test_gui_profiles import GuiTestCase
from app import gui


class TestGuiUninstall(GuiTestCase):
    def test_botao_desativado_em_checkout(self):
        win = self.make_window()
        self.assertFalse(win.btn_uninstall.isEnabled())

    def test_botao_abre_terminal_sem_confirmacao_automatica(self):
        win = self.make_window()
        with mock.patch.object(gui, "register_desktop"), \
                mock.patch.object(gui.shutil, "which", return_value="/usr/bin/xterm"), \
                mock.patch.object(gui.QProcess, "startDetached", return_value=(True, 123)) as start, \
                mock.patch.object(gui, "QTimer") as timer_type, \
                mock.patch.object(gui.qApp, "quit") as quit:
            win.request_uninstall()
            self.assertFalse(win.btn_uninstall.isEnabled())
            win.request_uninstall()
            self.assertEqual(start.call_count, 1)
            callback = timer_type.return_value.timeout.connect.call_args.args[0]
            with mock.patch.object(gui.os, "kill", side_effect=ProcessLookupError):
                callback()
            self.assertTrue(win.btn_uninstall.isEnabled())
        args = start.call_args.args
        self.assertEqual(args[0], "/usr/bin/xterm")
        self.assertEqual(args[1][:2], ["-e", "/bin/bash"])
        self.assertTrue(args[1][2].endswith("/uninstall.sh"))
        self.assertEqual(len(args[1]), 3)
        quit.assert_not_called()

    def test_falha_ao_abrir_terminal_avisa_sem_fechar_app(self):
        win = self.make_window()
        with mock.patch.object(gui, "register_desktop"), \
                mock.patch.object(gui.shutil, "which", return_value="/usr/bin/xterm"), \
                mock.patch.object(gui.QProcess, "startDetached", return_value=(False, 0)), \
                mock.patch.object(gui.QMessageBox, "warning") as warning, \
                mock.patch.object(gui.qApp, "quit") as quit:
            win.request_uninstall()
        warning.assert_called_once()
        quit.assert_not_called()
