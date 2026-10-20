"""Native Qt/OpenGL viewer for the bundled Blender model; no network or Blender runtime."""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import struct

from PyQt5.QtCore import Qt, QTimer, QPointF, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import (QMatrix4x4, QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLShader,
                         QOpenGLShaderProgram, QOpenGLVersionProfile, QQuaternion,
                         QSurfaceFormat, QVector3D)
from PyQt5.QtWidgets import QApplication, QOpenGLWidget
from .i18n import tr
from .logger import get_logger

MODEL_PATH=Path(__file__).parent/'resources/baseus-presenter.glb'
log=get_logger('device_3d')


@dataclass(frozen=True)
class Mesh:
    name: str
    positions: bytes
    normals: bytes
    indices: bytes
    index_type: int
    count: int
    color: tuple
    transform: QMatrix4x4


@lru_cache(maxsize=1)
def load_model(path):
    """Read the embedded, uncompressed glTF triangles shipped by this project."""
    data=Path(path).read_bytes()
    try:
        if len(data)<20 or struct.unpack_from('<4sII',data)!=(b'glTF',2,len(data)):
            raise ValueError('Invalid GLB header')
        chunks={};offset=12
        while offset<len(data):
            size,kind=struct.unpack_from('<II',data,offset);offset+=8
            if offset+size>len(data):raise ValueError('Truncated GLB chunk')
            chunks[kind]=data[offset:offset+size];offset+=size
        doc=json.loads(chunks[0x4E4F534A]);binary=chunks[0x004E4942]
        if len(doc['buffers'])!=1 or 'uri' in doc['buffers'][0]:
            raise ValueError('Only the embedded model buffer is supported')

        def accessor(index,vector):
            spec=doc['accessors'][index];view=doc['bufferViews'][spec['bufferView']]
            sizes={5121:1,5123:2,5125:4,5126:4}
            component=spec['componentType'];width=sizes[component]*(3 if vector else 1)
            if (spec['type']!=('VEC3' if vector else 'SCALAR') or
                    (vector and component!=5126) or (not vector and component==5126) or
                    'sparse' in spec or view['buffer']!=0):
                raise ValueError('Unsupported model accessor')
            start=view.get('byteOffset',0)+spec.get('byteOffset',0)
            stride=view.get('byteStride',width);count=spec['count']
            end=start+(count-1)*stride+width
            if count<=0 or stride<width or start<0 or end>len(binary) or end>view.get('byteOffset',0)+view['byteLength']:
                raise ValueError('Invalid model buffer bounds')
            raw=(binary[start:end] if stride==width else
                 b''.join(binary[start+i*stride:start+i*stride+width] for i in range(count)))
            return raw,component,count

        result=[]
        def visit(index,parent,ancestors):
            if index in ancestors:raise ValueError('Cyclic model nodes')
            node=doc['nodes'][index];local=QMatrix4x4()
            if 'matrix' in node:
                values=node['matrix']
                local=QMatrix4x4(*[values[c*4+r] for r in range(4) for c in range(4)])
            else:
                local.translate(*node.get('translation',(0,0,0)))
                x,y,z,w=node.get('rotation',(0,0,0,1));local.rotate(QQuaternion(w,x,y,z))
                local.scale(*node.get('scale',(1,1,1)))
            transform=parent*local
            if 'mesh' in node:
                for primitive in doc['meshes'][node['mesh']]['primitives']:
                    if primitive.get('mode',4)!=4:raise ValueError('Only triangles are supported')
                    positions,_,vertices=accessor(primitive['attributes']['POSITION'],True)
                    normals,_,normal_count=accessor(primitive['attributes']['NORMAL'],True)
                    indices,index_type,count=accessor(primitive['indices'],False)
                    code={5121:'B',5123:'H',5125:'I'}[index_type]
                    if vertices!=normal_count or count%3 or max(v[0] for v in struct.iter_unpack('<'+code,indices))>=vertices:
                        raise ValueError('Invalid model triangle indices')
                    color=doc['materials'][primitive['material']]['pbrMetallicRoughness'].get('baseColorFactor',[1,1,1,1])
                    result.append(Mesh(node.get('name',''),positions,normals,indices,index_type,count,tuple(color[:3]),transform))
            for child in node.get('children',[]):visit(child,transform,ancestors|{index})
        for index in doc['scenes'][doc.get('scene',0)]['nodes']:visit(index,QMatrix4x4(),set())
        if not result:raise ValueError('Empty model')
        return tuple(result)
    except (KeyError,IndexError,TypeError,struct.error,OverflowError) as exc:
        raise ValueError('Invalid bundled 3D model') from exc


CONTROL_PREFIXES=(
    ('Botão mouse','laser'),('Rebaixo mouse','laser'),('Mouse ','laser'),
    ('Botão central','physical_laser'),('Aro botão laranja','physical_laser'),
    ('Símbolo laranja','physical_laser'),('Centro símbolo','physical_laser'),('Saída laser','physical_laser'),
    ('Botão avançar','next'),('Rebaixo avançar','next'),('Seta para','next'),
    ('Botão Voltar','back'),('Ícone voltar','back'),('Botão Tela','screen'),('Ícone tela','screen'),
    ('Lateral Caneta','pen'),('Pincel lateral','pen'),
    # Button mesh names are inverted; glyph positions in the GLB are corrected.
    ('Lateral Microfone','translate'),('Microfone','mic'),
    ('Lateral Tradução','mic'),('Tradução','translate'),
    ('Lateral Volume mais','volume_up'),('Volume mais','volume_up'),
    ('Lateral Volume menos','volume_down'),('Volume menos','volume_down'),
    ('Chave ON OFF','power'),('Trilho ON OFF','power'),('Indicador laranja ON OFF','power'),('Alimentação ','power'),
)
PICK_KEYS=tuple(dict.fromkeys(key for _,key in CONTROL_PREFIXES))
FOCUS_MESHES={
    'laser':'Botão mouse','physical_laser':'Botão central',
    'next':'Botão avançar','back':'Botão Voltar','screen':'Botão Tela',
    'pen':'Lateral Caneta','mic':'Lateral Tradução','translate':'Lateral Microfone',
    'volume_up':'Lateral Volume mais','volume_down':'Lateral Volume menos',
    'power':'Chave ON OFF',
}


def control_for_mesh(name):
    return next((key for prefix,key in CONTROL_PREFIXES if name.startswith(prefix)),None)


VERTEX_SHADER='''
attribute vec3 position;
attribute vec3 normal;
uniform mat4 mvp;
uniform mat3 normalMatrix;
varying vec3 surfaceNormal;
void main() {
    gl_Position = mvp * vec4(position, 1.0);
    surfaceNormal = normalize(normalMatrix * normal);
}
'''
FRAGMENT_SHADER='''
uniform vec3 baseColor;
uniform float highlight;
uniform float picking;
uniform vec3 pickColor;
varying vec3 surfaceNormal;
void main() {
    if (picking > 0.5) { gl_FragColor = vec4(pickColor,1.0); return; }
    vec3 n = normalize(surfaceNormal);
    float light = 0.38 + 0.62 * max(dot(n, normalize(vec3(-0.4,0.7,1.0))), 0.0);
    float shine = pow(max(dot(n, normalize(vec3(0.3,0.7,1.0))), 0.0), 45.0);
    vec3 color = baseColor * light + vec3(0.08 * shine);
    color = mix(color, vec3(0.16,0.42,0.75), highlight * 0.6);
    gl_FragColor = vec4(pow(max(color,vec3(0.0)),vec3(1.0/2.2)),1.0);
}
'''


class ModelView(QOpenGLWidget):
    unavailable=pyqtSignal()
    control_clicked=pyqtSignal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        fmt=QSurfaceFormat();fmt.setVersion(2,1);fmt.setDepthBufferSize(24);fmt.setSamples(4)
        self.setFormat(fmt)
        self.setMinimumSize(300,280);self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(tr('Modelo 3D do passador'))
        self.active='laser';self.buffers=[];self.program=None;self.functions=None
        self.error=False;self._position=None;self._press_position=None;self._dragged=False;self._checked=False
        self._focus_start=None
        self._focus_animation=QVariantAnimation(self)
        self._focus_animation.setDuration(280)
        self._focus_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._focus_animation.setStartValue(0.0)
        self._focus_animation.setEndValue(1.0)
        self._focus_animation.valueChanged.connect(self._animate_focus)
        self.reset_view()

    def reset_view(self):
        self._focus_animation.stop()
        self.rotation=QQuaternion.fromEulerAngles(72,-18,-12)
        self.distance=.24;self.camera_offset=QPointF();self.update()

    @staticmethod
    def _control_rotation(key):
        angles=((78,-70,-10) if key in ('pen','mic','translate','volume_up','volume_down') else
                (78,70,10) if key=='power' else (72,-18,-12))
        return QQuaternion.fromEulerAngles(*angles)

    def orient_for_control(self,key):
        self._focus_animation.stop()
        self.rotation=self._control_rotation(key);self.update()

    @staticmethod
    @lru_cache(maxsize=11)
    def _control_center(key):
        mesh=next(m for m in load_model(MODEL_PATH) if m.name==FOCUS_MESHES[key])
        vertices=list(struct.iter_unpack('<3f',mesh.positions))
        center=QVector3D(*[(min(v[i] for v in vertices)+max(v[i] for v in vertices))/2
                          for i in range(3)])
        return mesh.transform.map(center)

    def focus_control(self,key):
        if self.error:return
        self._focus_animation.stop()
        target_rotation=self._control_rotation(key)
        center=target_rotation.rotatedVector(self._control_center(key))
        self._focus_start=(QQuaternion(self.rotation),self.distance,QPointF(self.camera_offset))
        self._focus_target=(target_rotation,max(.11,min(.65,.18+center.z())),
                            QPointF(-center.x(),-center.y()))
        self._focus_animation.start()

    def _animate_focus(self,progress):
        if self._focus_start is None:return
        rotation,distance,offset=self._focus_start
        target_rotation,target_distance,target_offset=self._focus_target
        self.rotation=QQuaternion.slerp(rotation,target_rotation,progress)
        self.distance=distance+(target_distance-distance)*progress
        self.camera_offset=offset+(target_offset-offset)*progress
        self.update()

    def _trackball_point(self,point):
        radius=max(1,min(self.width(),self.height())/2)
        x=(point.x()-self.width()/2)/radius
        y=(self.height()/2-point.y())/radius
        squared=x*x+y*y
        # Sphere in the centre, smooth hyperbolic continuation outside it.
        z=math.sqrt(1-squared) if squared<=.5 else .5/math.sqrt(squared)
        return QVector3D(x,y,z).normalized()

    def _rotate_trackball(self,start,end):
        self._focus_animation.stop()
        turn=QQuaternion.rotationTo(self._trackball_point(start),self._trackball_point(end))
        self.rotation=(turn*self.rotation).normalized();self.update()

    def rotate(self,dx,dy):
        self._focus_animation.stop()
        yaw=QQuaternion.fromAxisAndAngle(0,1,0,dx*.6)
        pitch=QQuaternion.fromAxisAndAngle(1,0,0,dy*.6)
        self.rotation=(yaw*pitch*self.rotation).normalized();self.update()

    def _camera_matrix(self):
        view=QMatrix4x4()
        view.translate(self.camera_offset.x(),self.camera_offset.y(),-self.distance)
        view.rotate(self.rotation)
        return view

    def zoom(self,steps,point=None):
        self._focus_animation.stop()
        distance=max(.11,min(.65,self.distance*math.exp(max(-10,min(10,-steps*.12)))))
        delta=distance-self.distance
        if not delta:return
        if point is not None:
            point=QPointF(point)
            # Move the camera along the ray through the mouse. Every point
            # on that ray stays at the same pixel, at any model depth.
            tangent=math.tan(math.radians(19))
            x=(2*point.x()/max(1,self.width())-1)*tangent*self.width()/max(1,self.height())
            y=(1-2*point.y()/max(1,self.height()))*tangent
            self.camera_offset+=QPointF(x*delta,y*delta)
        self.distance=distance
        self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._focus_animation.stop()
            self._position=event.pos();self._press_position=event.pos();self._dragged=False
            self.setFocus();self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self,event):
        if self._position is not None and event.buttons()&Qt.LeftButton:
            if not self._dragged:
                if (event.pos()-self._press_position).manhattanLength()<QApplication.startDragDistance():return
                self._dragged=True
            self._rotate_trackball(self._position,event.pos())
            self._position=event.pos()

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:self.reset_view()

    def mouseReleaseEvent(self,event):
        clicked=(event.button()==Qt.LeftButton and self._press_position is not None and
                 not self._dragged and (event.pos()-self._press_position).manhattanLength()<QApplication.startDragDistance())
        self._position=None;self._press_position=None;self.setCursor(Qt.OpenHandCursor)
        if clicked:
            key=self.control_at(event.pos())
            if key is not None:self.control_clicked.emit(key)

    def control_at(self,point):
        if self.error or not self.isValid() or not self.rect().contains(point):return None
        self.makeCurrent()
        frame=None
        try:
            scale=self.devicePixelRatioF()
            format=QOpenGLFramebufferObjectFormat();format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            frame=QOpenGLFramebufferObject(round(self.width()*scale),round(self.height()*scale),format)
            if not frame.isValid() or not frame.bind():raise RuntimeError('Cannot create picking framebuffer')
            # Draw all geometry with depth testing: the body must hide buttons on the far side.
            self.functions.glDisable(0x0BD0)  # Dithering would change the exact control IDs.
            self._paint_model(picking=True)
            color=frame.toImage().pixelColor(int(point.x()*scale),int(point.y()*scale))
            index=color.red()-1
            return PICK_KEYS[index] if 0<=index<len(PICK_KEYS) else None
        except RuntimeError as exc:
            self._fail(str(exc));return None
        finally:
            if frame is not None:frame.release()
            self.functions.glEnable(0x0BD0)
            self.doneCurrent();self.update()

    def wheelEvent(self,event):
        self.zoom(event.angleDelta().y()/120,event.posF());event.accept()

    def keyPressEvent(self,event):
        key=event.key()
        if key in (Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down):
            self.rotate({Qt.Key_Left:-15,Qt.Key_Right:15}.get(key,0),{Qt.Key_Up:-15,Qt.Key_Down:15}.get(key,0))
        elif key in (Qt.Key_Plus,Qt.Key_Equal,Qt.Key_Minus):self.zoom(-1 if key==Qt.Key_Minus else 1)
        elif key==Qt.Key_Home:self.reset_view()
        else:super().keyPressEvent(event)

    def showEvent(self,event):
        super().showEvent(event);self.setCursor(Qt.OpenHandCursor)
        if not self._checked:
            self._checked=True;QTimer.singleShot(150,self._check_context)

    def _check_context(self):
        if not self.isValid():self._fail('OpenGL context unavailable')

    def _fail(self,message):
        if not self.error:
            self.error=True;log.warning('3D viewer: %s',message);self.unavailable.emit()

    def initializeGL(self):
        try:
            profile=QOpenGLVersionProfile();profile.setVersion(2,1)
            self.functions=self.context().versionFunctions(profile)
            if self.functions is None:raise RuntimeError('OpenGL 2.1 unavailable')
            self.functions.initializeOpenGLFunctions()
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.program=QOpenGLShaderProgram(self)
            if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex,VERTEX_SHADER):raise RuntimeError(self.program.log())
            if not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment,FRAGMENT_SHADER):raise RuntimeError(self.program.log())
            if not self.program.link():raise RuntimeError(self.program.log())
            for mesh in load_model(MODEL_PATH):
                buffers=[]
                for kind,data in ((QOpenGLBuffer.VertexBuffer,mesh.positions),(QOpenGLBuffer.VertexBuffer,mesh.normals),(QOpenGLBuffer.IndexBuffer,mesh.indices)):
                    buffer=QOpenGLBuffer(kind)
                    if not buffer.create():raise RuntimeError('Cannot create model buffer')
                    buffers.append(buffer);buffer.bind();buffer.allocate(data,len(data));buffer.release()
                self.buffers.append((mesh,buffers))
        except (OSError,ValueError,RuntimeError,ImportError) as exc:self._fail(str(exc))

    def paintGL(self):
        try:self._paint_model()
        except RuntimeError as exc:self._fail(str(exc))

    def _paint_model(self,picking=False):
        if self.error or not self.program:return
        f=self.functions
        scale=self.devicePixelRatioF()
        f.glViewport(0,0,round(self.width()*scale),round(self.height()*scale))
        f.glClearColor(0,0,0,1) if picking else f.glClearColor(.055,.065,.085,1)
        f.glClear(0x4000|0x0100);f.glEnable(0x0B71)
        projection=QMatrix4x4();projection.perspective(38,self.width()/max(1,self.height()),.01,2)
        view=self._camera_matrix()
        self.program.bind();self.program.setUniformValue('picking',float(picking))
        for mesh,buffers in self.buffers:
            key=control_for_mesh(mesh.name)
            index=PICK_KEYS.index(key)+1 if key is not None else 0
            self.program.setUniformValue('pickColor',QVector3D(index/255,0,0))
            model=view*mesh.transform
            self.program.setUniformValue('mvp',projection*model)
            self.program.setUniformValue('normalMatrix',model.normalMatrix())
            self.program.setUniformValue('baseColor',QVector3D(*mesh.color))
            self.program.setUniformValue('highlight',float(control_for_mesh(mesh.name)==self.active))
            for name,buffer in zip(('position','normal'),buffers[:2]):
                buffer.bind();self.program.enableAttributeArray(name)
                self.program.setAttributeBuffer(name,0x1406,0,3)
            buffers[2].bind();f.glDrawElements(4,mesh.count,mesh.index_type,None)
            buffers[2].release()
        self.program.disableAttributeArray('position');self.program.disableAttributeArray('normal')
        self.program.release()

    def cleanup(self):
        self.makeCurrent()
        for _,buffers in self.buffers:
            for buffer in buffers:buffer.destroy()
        self.buffers=[]
        if self.program:self.program.removeAllShaders();self.program=None
        self.doneCurrent()
