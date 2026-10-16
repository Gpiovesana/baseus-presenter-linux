"""Contratos da nova composição; usa configuração temporária, sem hardware."""
from unittest import mock
from test_gui_profiles import GuiTestCase
from app import gui


class TestGuiLayout(GuiTestCase):
    def test_navegar_nao_modifica_configuracao(self):
        win = self.make_window()
        before = win.config.snapshot()
        with mock.patch.object(win.config, 'save') as save:
            for index, button in enumerate(win.nav_buttons):
                button.click()
                self.assertEqual(win.pages.currentIndex(), index)
            save.assert_not_called()
        self.assertEqual(before, win.config.snapshot())

    def test_bateria_real_compartilhada(self):
        win = self.make_window()
        self.assertNotIn('85%', win.lbl_battery.text())
        win.update_battery('Bateria: 17%')
        win.show()
        for button in win.nav_buttons:
            button.click()
            self.assertTrue(win.lbl_battery.isVisible())
            self.assertIn('17%', win.lbl_battery.text())
        win.hide()

    def test_recuperacao_restaura_bateria_sem_apagar_outro_aviso(self):
        win = self.make_window()
        win.update_battery('Bateria: 17%')
        expected = win.lbl_battery.text()
        win.show_warning('overlay indisponível')
        win.clear_warning('overlay indisponível')
        self.assertEqual(win.lbl_battery.text(), expected)
        win.show_warning('overlay indisponível')
        win.show_warning('erro do microfone')
        win.clear_warning('overlay indisponível')
        self.assertIn('erro do microfone', win.lbl_battery.text())

    def test_efeito_le_valores_do_perfil_e_edicao_atual(self):
        win = self.make_window()
        win.lupa_slider.setValue(410)
        self.assertEqual(win.effects_canvas.settings['lupa_size'], 410)
        self.assertEqual(win.config.get_visual('lupa_size'),410)
        for mode, button in win.effect_buttons.items():
            button.click()
            self.assertEqual(win.effects_canvas.mode, mode)

    def test_formato_da_lupa_salvo_no_perfil(self):
        win = self.make_window()
        self.assertEqual(win.combo_lupa_shape.currentData(), 'circular')
        win.combo_lupa_shape.setCurrentIndex(win.combo_lupa_shape.findData('square'))
        self.assertEqual(win.config.get_visual('lupa_shape'), 'square')
        self.assertEqual(win.effects_canvas.settings['lupa_shape'], 'square')
        win.show()
        win.nav_buttons[1].click()
        win.effect_buttons['lupa'].click()
        self.assertTrue(win.combo_lupa_shape.isVisible())
        win.effect_buttons['laser'].click()
        self.assertFalse(win.combo_lupa_shape.isVisible())
        win.hide()
        win._load_profile_into_widgets()
        self.assertEqual(win.combo_lupa_shape.currentData(), 'square')

    def test_acoes_reais_de_modelos_e_destino(self):
        with mock.patch.object(gui.MainWindow,'add_model') as add, \
             mock.patch.object(gui.MainWindow,'delete_model') as remove, \
             mock.patch.object(gui.MainWindow,'pick_txt_dir') as folder:
            win = self.make_window()
            win.btn_add_model.click()
            win.btn_remove_model.click()
            win.btn_txt_dir.click()
            add.assert_called_once()
            remove.assert_called_once()
            folder.assert_called_once()

    def test_atualizacao_preserva_sinal_existente(self):
        win = self.make_window()
        callback = mock.Mock()
        win.manual_update_requested.connect(callback)
        win.btn_check_update.click()
        callback.assert_called_once()
        self.assertFalse(win.btn_uninstall.isEnabled())

    def test_rotulos_apos_carregar_perfil_com_sinais_bloqueados(self):
        win = self.make_window()
        expected = win.lupa_slider.value()
        self.assertIn(str(expected),win.effect_value_labels['lupa_size'][0].text())
        with mock.patch.object(gui.models,'find_model',return_value={'language':'en'}):
            win.refresh_model_language()
        self.assertIn('en',win.lbl_model_language.text())
