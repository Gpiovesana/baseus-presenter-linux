"""Native GPU integration check; run with QT_QPA_PLATFORM=xcb or wayland."""
import os,sys,struct
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
from test_gui_profiles import GuiTestCase
from app.gui_visuals import Device, control_descriptions
from PyQt5.QtWidgets import QLabel
from app.device_3d import load_model,MODEL_PATH
from PyQt5.QtGui import QMatrix4x4,QVector3D,QQuaternion
from PyQt5.QtCore import QPoint,Qt
from PyQt5.QtTest import QTest
case=GuiTestCase();case.setUpClass()
if case._app.platformName() not in ('xcb','wayland'):
    raise SystemExit('Run with QT_QPA_PLATFORM=xcb or QT_QPA_PLATFORM=wayland on a desktop session.')
case.setUp()
try:
    win=case.make_window();win.setWindowTitle('Baseus — teste de seleção 3D');win.show();QTest.qWait(900)
    device=win.findChild(Device);view=device.view;assert view.isValid() and not view.error
    names={'physical_laser':'Botão central','laser':'Botão mouse','next':'Botão avançar','back':'Botão Voltar','screen':'Botão Tela','pen':'Lateral Caneta','mic':'Lateral Tradução','translate':'Lateral Microfone','volume_up':'Lateral Volume mais','volume_down':'Lateral Volume menos','power':'Chave ON OFF'}
    def point_for(mesh):
        coords=list(struct.iter_unpack('<3f',mesh.positions))
        center=QVector3D(*[(min(v[i] for v in coords)+max(v[i] for v in coords))/2 for i in range(3)])
        proj=QMatrix4x4();proj.perspective(38,view.width()/view.height(),.01,2)
        camera=view._camera_matrix()
        ndc=(proj*camera*mesh.transform).map(center)
        return QPoint(round((ndc.x()+1)*view.width()/2),round((1-ndc.y())*view.height()/2))
    for key,name in names.items():
        view.orient_for_control(key);QTest.qWait(60)
        mesh=next(m for m in load_model(MODEL_PATH) if m.name==name)
        point=point_for(mesh);got=view.control_at(point)
        print('PICK',key,point.x(),point.y(),got,flush=True)
        assert got==key,(key,got)
        QTest.mouseClick(view,Qt.LeftButton,pos=point);QTest.qWait(60)
        assert view.active==key and device.buttons[key].isChecked(),key
        assert sum(b.isChecked() for b in device.buttons.values())==1
        assert control_descriptions()[key][0] in [label.text() for label in win.pages.widget(0).findChildren(QLabel)]
        assert not view.error
    # The opaque body must prevent a click on the hidden front mouse button.
    view.rotation=QQuaternion.fromEulerAngles(-90,0,0);view.update();QTest.qWait(60)
    mouse=next(m for m in load_model(MODEL_PATH) if m.name=='Botão mouse')
    assert view.control_at(point_for(mouse)) is None
    assert view.control_at(QPoint(1,1)) is None
    view.reset_view();device.selected.emit('laser');QTest.qWait(80)
    win.grab().save('/tmp/baseus-click-'+os.environ['QT_QPA_PLATFORM']+'.png')
    print('ALL_11_CLICK_OK',os.environ['QT_QPA_PLATFORM'],flush=True)
    win.close();case.doCleanups();case._app.processEvents()
finally:case.doCleanups()
