"""Viewer contracts: real packaged asset, camera interaction and selection without a GPU."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from PyQt5.QtCore import QPoint, QPointF, Qt, QEvent
from PyQt5.QtGui import QQuaternion, QMouseEvent, QMatrix4x4, QVector3D
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
        front=QQuaternion(device.view.rotation)
        device.buttons['pen'].click()
        self.assertEqual(selected,['pen'])
        device.view._focus_animation.setCurrentTime(device.view._focus_animation.duration())
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

    def test_zoom_keeps_surface_point_under_mouse_after_rotation(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        view.resize(600,400);view.rotate(35,-20)
        point=QPointF(440,125)
        depth=.215
        # Construct a world point visible at this pixel, in front of the pivot.
        import math
        tangent=math.tan(math.radians(19))
        camera_point=QVector3D((2*point.x()/view.width()-1)*depth*tangent*1.5,
                              (1-2*point.y()/view.height())*depth*tangent,-depth)
        camera=QMatrix4x4();camera.translate(0,0,-view.distance);camera.rotate(view.rotation)
        model_point=camera.inverted()[0].map(camera_point)
        projection=QMatrix4x4();projection.perspective(38,1.5,.01,2)
        before=(projection*camera).map(model_point)
        view.zoom(2,point)
        after=(projection*view._camera_matrix()).map(model_point)
        self.assertAlmostEqual(before.x(),after.x(),places=5)
        self.assertAlmostEqual(before.y(),after.y(),places=5)
        self.assertLess(view.distance,.24)
        view.reset_view()
        self.assertEqual(view.camera_offset,QPointF())

    def test_zoom_at_limit_does_not_drift(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        point=QPointF(40,40)
        view.zoom(1000,point)
        offset=QPointF(view.camera_offset)
        view.zoom(10,point)
        self.assertEqual(view.camera_offset,offset)

    def test_wheel_uses_mouse_position_and_reverse_zoom_restores_camera(self):
        from PyQt5.QtGui import QWheelEvent
        view=ModelView();self.addCleanup(view.deleteLater)
        view.resize(500,350)
        point=QPointF(370,70)
        event=QWheelEvent(point,point,QPoint(),QPoint(0,120),
                          Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        view.wheelEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertNotEqual(view.camera_offset,QPointF())
        view.zoom(-1,point)
        self.assertAlmostEqual(view.distance,.24)
        self.assertAlmostEqual(view.camera_offset.x(),0,places=10)
        self.assertAlmostEqual(view.camera_offset.y(),0,places=10)

    def test_menu_selection_focuses_control_smoothly_without_accumulating_zoom(self):
        device=Device();self.addCleanup(device.deleteLater)
        device.selected.connect(device.select)
        selected=[];device.selected.connect(selected.append)
        view=device.view
        device.buttons['pen'].click()
        self.assertEqual(selected,['pen'])
        self.assertTrue(view._focus_animation.state())
        view._focus_animation.setCurrentTime(view._focus_animation.duration())
        center=view._control_center('pen')
        camera_center=view._camera_matrix().map(center)
        self.assertAlmostEqual(camera_center.x(),0,places=5)
        self.assertAlmostEqual(camera_center.y(),0,places=5)
        self.assertAlmostEqual(camera_center.z(),-.18,places=5)
        position=(view.distance,QPointF(view.camera_offset))
        device.buttons['pen'].click()
        view._focus_animation.setCurrentTime(view._focus_animation.duration())
        self.assertEqual((view.distance,view.camera_offset),position)
        self.assertEqual(view.active,'pen')

    def test_manual_zoom_interrupts_focus_and_reset_restores_view(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        view.focus_control('mic')
        view._focus_animation.setCurrentTime(80)
        view.zoom(1,QPointF(100,100))
        self.assertFalse(view._focus_animation.state())
        view.reset_view()
        self.assertEqual(view.camera_offset,QPointF())
        self.assertAlmostEqual(view.distance,.24)

    def test_arcball_drag_is_reversible_and_edges_allow_roll(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        view.resize(600,400)
        initial=QQuaternion(view.rotation)
        start,end=QPoint(500,190),QPoint(495,120)
        view._rotate_trackball(start,end)
        change=view.rotation*initial.conjugated()
        self.assertGreater(abs(change.z()),.01)
        self.assertAlmostEqual(view.rotation.length(),1,places=5)
        view._rotate_trackball(end,start)
        # Quaternions q and -q encode the same rotation.
        self.assertAlmostEqual(abs(QQuaternion.dotProduct(view.rotation,initial)),1,places=5)

    def test_every_menu_control_is_centred_and_visible_after_focus(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        for key in control_descriptions():
            with self.subTest(key=key):
                view.focus_control(key)
                view._focus_animation.setCurrentTime(view._focus_animation.duration())
                center=view._camera_matrix().map(view._control_center(key))
                self.assertAlmostEqual(center.x(),0,places=5)
                self.assertAlmostEqual(center.y(),0,places=5)
                self.assertAlmostEqual(center.z(),-.18,places=5)

    def test_drag_uses_trackball_instead_of_fixed_axis_rotation(self):
        view=ModelView();self.addCleanup(view.deleteLater)
        start,end=QPoint(150,150),QPoint(200,180)
        press=QMouseEvent(QEvent.MouseButtonPress,start,Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
        move=QMouseEvent(QEvent.MouseMove,end,Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
        view.mousePressEvent(press)
        with mock.patch.object(view,'_rotate_trackball') as rotate:
            view.mouseMoveEvent(move)
        rotate.assert_called_once_with(start,end)

    def test_microphone_translation_follow_physical_controls_not_swapped_asset_names(self):
        # These two mesh groups were named inversely in the bundled GLB.
        self.assertEqual(control_for_mesh('Lateral Microfone'),'translate')
        self.assertEqual(control_for_mesh('Microfone'),'mic')
        self.assertEqual(control_for_mesh('Lateral Tradução'),'mic')
        self.assertEqual(control_for_mesh('Tradução'),'translate')
        meshes=load_model(MODEL_PATH)
        def center(name):
            import struct
            mesh=next(m for m in meshes if m.name==name)
            vertices=list(struct.iter_unpack('<3f',mesh.positions))
            return mesh.transform.map(QVector3D(*[
                (min(v[i] for v in vertices)+max(v[i] for v in vertices))/2 for i in range(3)]))
        self.assertEqual(ModelView._control_center('mic'),center('Lateral Tradução'))
        self.assertEqual(ModelView._control_center('translate'),center('Lateral Microfone'))

    def test_body_symbols_are_in_the_correct_physical_order(self):
        meshes=load_model(MODEL_PATH)
        def symbol_z(name):
            mesh=next(m for m in meshes if m.name==name)
            points=[mesh.transform.map(QVector3D(*p)).z()
                    for p in struct.iter_unpack('<3f',mesh.positions)]
            return (min(points)+max(points))/2
        self.assertAlmostEqual(symbol_z('Microfone cápsula'),.014,places=6)
        self.assertAlmostEqual(symbol_z('Tradução círculo'),.005,places=6)
