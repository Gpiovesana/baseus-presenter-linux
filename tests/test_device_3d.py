"""Viewer contracts: real packaged asset, camera interaction and selection without a GPU."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from PyQt5.QtCore import QPoint, Qt, QEvent
from PyQt5.QtGui import QQuaternion, QMouseEvent
from PyQt5.QtWidgets import QApplication
from app.device_3d import MODEL_PATH, load_model, ModelView, control_for_mesh
from app.gui_visuals import Device, control_descriptions


class TestDevice3D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_packaged_model_contains_controls_and_real_scale(self):
        meshes=load_model(MODEL_PATH)
        names={mesh.name for mesh in meshes}
        self.assertTrue({'Botão Voltar','Botão Tela','Lateral Caneta','Fundo sulco comum'} <= names)
        self.assertTrue(all(len(mesh.positions)==len(mesh.normals) for mesh in meshes))
        # glTF is in metres; the root must preserve the presenter's 135 mm length.
        self.assertTrue(any(abs(mesh.transform.column(0).length()-.001)<1e-7 for mesh in meshes))

    def test_corrupt_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.glb';p.write_bytes(b'broken')
            with self.assertRaises(ValueError): load_model(p)

    def test_rotation_is_free_zoom_bounded_and_reset_reproducible(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        initial=QQuaternion(view.rotation)
        view.rotate(140,95)
        self.assertNotEqual(view.rotation,initial)
        self.assertAlmostEqual(view.rotation.length(),1,places=5)
        view.zoom(1000);self.assertGreater(view.distance,0)
        view.zoom(-1000);self.assertLessEqual(view.distance,.65)
        view.reset_view();self.assertEqual(view.rotation,initial)
        self.assertAlmostEqual(view.distance,.24)

    def test_selection_preserves_existing_signals_and_highlights_model(self):
        device=Device();self.addCleanup(device.deleteLater)
        selected=[];device.selected.connect(selected.append)
        device.buttons['pen'].click()
        self.assertEqual(selected,['pen'])
        front=QQuaternion(device.view.rotation)
        device.select('pen')
        self.assertNotEqual(device.view.rotation,front)
        self.assertEqual(device.view.active,'pen')
        self.assertEqual(sum(b.isChecked() for b in device.buttons.values()),1)
        self.assertEqual(device.view.focusPolicy(),Qt.StrongFocus)

    def test_renderer_failure_keeps_explanations_available(self):
        device=Device();self.addCleanup(device.deleteLater)
        device.view._fail('test unavailable')
        self.assertIs(device.stack.currentWidget(),device.fallback)
        self.assertFalse(device.reset_button.isEnabled())
        selected=[];device.selected.connect(selected.append)
        device.buttons['mic'].click();self.assertEqual(selected,['mic'])

    def test_physical_and_mouse_buttons_are_not_confused(self):
        self.assertEqual(control_for_mesh('Botão central'),'physical_laser')
        self.assertEqual(control_for_mesh('Botão mouse'),'laser')
        self.assertEqual(control_for_mesh('Mouse contorno'),'laser')
        self.assertIn('Mouse',control_descriptions()['laser'][0])
        self.assertIn('físico',control_descriptions()['physical_laser'][0])

    def test_all_eleven_buttons_have_a_menu_entry(self):
        expected={'laser','physical_laser','next','back','screen','pen','mic','translate','volume_up','volume_down','power'}
        self.assertEqual(set(control_descriptions()),expected)
        meshes=load_model(MODEL_PATH)
        mapped={control_for_mesh(mesh.name) for mesh in meshes}
        self.assertTrue(expected<=mapped)

    def test_model_click_selects_menu_but_drag_does_not(self):
        device=Device();self.addCleanup(device.deleteLater)
        device.selected.connect(device.select)
        selected=[];device.selected.connect(selected.append)
        view=device.view
        def event(kind,point,button,buttons):
            return QMouseEvent(kind,point,button,buttons,Qt.NoModifier)
        with mock.patch.object(view,'control_at',return_value='physical_laser') as pick:
            view.mousePressEvent(event(QEvent.MouseButtonPress,QPoint(50,50),Qt.LeftButton,Qt.LeftButton))
            view.mouseReleaseEvent(event(QEvent.MouseButtonRelease,QPoint(50,50),Qt.LeftButton,Qt.NoButton))
            self.assertEqual(selected,['physical_laser'])
            self.assertTrue(device.buttons['physical_laser'].isChecked())
            self.assertEqual(view.active,'physical_laser')
            pick.reset_mock()
            view.mousePressEvent(event(QEvent.MouseButtonPress,QPoint(50,50),Qt.LeftButton,Qt.LeftButton))
            view.mouseMoveEvent(event(QEvent.MouseMove,QPoint(100,100),Qt.NoButton,Qt.LeftButton))
            view.mouseReleaseEvent(event(QEvent.MouseButtonRelease,QPoint(100,100),Qt.LeftButton,Qt.NoButton))
            pick.assert_not_called();self.assertEqual(selected,['physical_laser'])
