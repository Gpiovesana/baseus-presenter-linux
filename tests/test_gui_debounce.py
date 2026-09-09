"""Regressões de persistência com o event loop e temporizadores reais do Qt."""
import copy
from unittest import mock

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox

from app import config as cfg
from test_gui_profiles import GuiTestCase


class TestSaveDebounce(GuiTestCase):
    def make_window(self, data=None):
        win = super().make_window(data)
        self.addCleanup(win._save_timer.stop)
        return win

    def test_arraste_reinicia_prazo_e_grava_uma_vez(self):
        win = self.make_window()
        with mock.patch.object(win.config, "save", wraps=win.config.save) as save:
            for value in range(31, 61):
                win.laser_slider.setValue(value)
            self.assertEqual(win.config.get_visual("laser_size"), 60)
            save.assert_not_called()
            QTest.qWait(250)
            win.laser_slider.setValue(75)
            QTest.qWait(250)
            save.assert_not_called()  # Já passou o prazo do primeiro evento.
            QTest.qWait(250)
            save.assert_called_once_with()
            self.assertEqual(cfg.load_config()["profiles"]["Padrão"]["visual"]["laser_size"], 75)
            QTest.qWait(450)
            save.assert_called_once_with()  # Timer não pode repetir.

    def test_combos_emitem_sinais_imediatos_e_compartilham_debounce(self):
        data = copy.deepcopy(cfg.DEFAULT_CONFIG)
        data["models"] = [{"label": "M1", "path": "/tmp/m1"},
                          {"label": "M2", "path": "/tmp/m2"}]
        data["profiles"]["Padrão"]["audio"]["selected_model_path"] = "/tmp/m1"
        win = self.make_window(data)
        win.combo_mic.addItem("Microfone USB", (7, "Microfone USB"))
        mic_changes, model_changes = [], []
        win.input_device_changed.connect(lambda: mic_changes.append(True))
        win.model_changed.connect(lambda: model_changes.append(True))
        with mock.patch.object(win.config, "save", wraps=win.config.save) as save:
            win.combo_mic.setCurrentIndex(win.combo_mic.count() - 1)
            win.combo_models.setCurrentIndex(win.combo_models.findData("/tmp/m2"))
            self.assertEqual(mic_changes, [True])
            self.assertEqual(model_changes, [True])
            self.assertEqual(win.config.get_audio("input_device_name"), "Microfone USB")
            self.assertEqual(win.config.get_audio("selected_model_path"), "/tmp/m2")
            save.assert_not_called()
            QTest.qWait(500)
            save.assert_called_once_with()

    def test_operacoes_de_perfil_salvam_imediatamente_sem_escrita_extra(self):
        for action in ("change", "create", "delete"):
            with self.subTest(action=action):
                data = copy.deepcopy(cfg.DEFAULT_CONFIG)
                data["profiles"]["Aula"] = copy.deepcopy(data["profiles"]["Padrão"])
                win = self.make_window(data)
                with mock.patch.object(win.config, "save", wraps=win.config.save) as save:
                    win.laser_slider.setValue(77)
                    if action == "change":
                        win.change_profile("Aula")
                    elif action == "create":
                        with mock.patch("app.gui.QInputDialog.getText", return_value=("Novo", True)):
                            win.new_profile()
                    else:
                        with mock.patch("app.gui.QMessageBox.question", return_value=QMessageBox.Yes):
                            win.delete_profile()
                    save.assert_called_once_with()
                    self.assertEqual(cfg.load_config(), win.config.snapshot())
                    if action != "delete":
                        self.assertEqual(cfg.load_config()["profiles"]["Padrão"]["visual"]["laser_size"], 77)
                    QTest.qWait(500)
                    save.assert_called_once_with()

    def test_fechar_janela_grava_pendente_tanto_na_bandeja_como_na_saida(self):
        for behavior in ("tray", "quit"):
            with self.subTest(behavior=behavior):
                win = self.make_window()
                win.combo_close.setCurrentIndex(1 if behavior == "quit" else 0)
                with mock.patch.object(win.config, "save", wraps=win.config.save) as save, \
                     mock.patch("app.gui.qApp") as app:
                    win.laser_slider.setValue(78)
                    win.closeEvent(QCloseEvent())
                    if behavior == "quit":
                        app.quit.assert_called_once_with()
                    else:
                        app.quit.assert_not_called()
                    save.assert_called_once_with()
                    self.assertEqual(cfg.load_config()["profiles"]["Padrão"]["visual"]["laser_size"], 78)
                    win.flush_pending_save()  # Cleanup após closeEvent não duplica.
                    QTest.qWait(500)
                    save.assert_called_once_with()

    def test_flush_sem_alteracao_nao_grava(self):
        win = self.make_window()
        with mock.patch.object(win.config, "save") as save:
            win.flush_pending_save()
            QTest.qWait(500)
            save.assert_not_called()
