from .i18n import tr
# ~/Documentos/Projetos/baseus-presenter-linux/app/hardware.py
import os
import re
import time
import select
from PyQt5.QtCore import QThread, pyqtSignal
from .logger import get_logger

log = get_logger(__name__)

try:
    import pyudev
except ImportError:
    pyudev = None
    log.warning("pyudev ausente. Hot-plug USB não funcionará em tempo real.")

try:
    from evdev import InputDevice, UInput, list_devices, ecodes as e
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    log.warning("Biblioteca evdev não instalada. Giroscópio desativado.")

class HardwareReader(QThread):
    pointer_active = pyqtSignal(bool)
    toggle_mode = pyqtSignal()
    battery_update = pyqtSignal(str)
    pen_active = pyqtSignal(bool)
    pen_clear = pyqtSignal()
    black_screen_toggle = pyqtSignal()
    record_toggled = pyqtSignal(bool)
    translate_toggled = pyqtSignal(bool)
    permission_error = pyqtSignal(str)

    def __init__(self, vendor_id="abc8", product_id="ca08", config=None):
        super().__init__()
        # IDs vêm do config quando disponível: uma revisão de hardware do
        # passador não deve exigir edição de código.
        if config is not None:
            hw = config.get("hardware", {}) or {}
            vendor_id = hw.get("vendor_id", vendor_id)
            product_id = hw.get("product_id", product_id)

        self.vendor_id_hex = vendor_id
        self.product_id_hex = product_id
        self.vendor_id_str = vendor_id.upper()
        self.running = True
        self._rescan_requested = False  # Flag para rescan seguro fora do select
        self.fds = {}
        self.kbd = None
        self.mouse_ev = None
        self.ui = None
        # #13: rastreia teclas/botões que JÁ foram encaminhados como
        # pressionados para o dispositivo virtual. Sem isso, o filtro do
        # pincel podia descartar o evento de SOLTURA de um botão que já
        # tinha sido encaminhado como pressionado, deixando-o preso para
        # sempre no dispositivo virtual.
        self._forwarded_pressed = set()

    def _release_evdev(self):
        """
        Libera UInput e os grabs de teclado/mouse.

        CRÍTICO: se o grab do teclado não for liberado, o teclado do usuário
        fica capturado por um processo zumbi — o pior modo de falha do projeto.
        Cada chamada é isolada para que a falha de uma não impeça as outras
        (ex.: hot-unplug torna ungrab() um OSError).
        """
        if not EVDEV_AVAILABLE:
            return

        # #13: solta no dispositivo virtual qualquer tecla/botão que ainda
        # esteja pressionado, ANTES de fechar o UInput. Fechar com uma tecla
        # presa deixaria o estado travado no consumidor (ex.: BTN_LEFT
        # eternamente pressionado do ponto de vista das aplicações).
        if self.ui and self._forwarded_pressed:
            for code in list(self._forwarded_pressed):
                try:
                    self.ui.write(e.EV_KEY, code, 0)
                except Exception as exc:
                    log.debug(f"Não foi possível soltar o código {code}: {exc}")
            try:
                self.ui.syn()
            except Exception:
                pass
        self._forwarded_pressed.clear()

        try:
            if self.ui: self.ui.close()
        except Exception as exc:
            log.warning(f"Erro ao fechar UInput (dispositivo pode ter sido desconectado): {exc}")
        finally:
            self.ui = None

        try:
            if self.kbd: self.kbd.ungrab()
        except Exception as exc:
            log.warning(f"Erro ao liberar kbd (dispositivo pode ter sido desconectado): {exc}")
        finally:
            try:
                if self.kbd: self.kbd.close()
            except Exception as exc:
                log.debug(f"Erro ao fechar kbd: {exc}")

        try:
            if self.mouse_ev: self.mouse_ev.ungrab()
        except Exception as exc:
            log.warning(f"Erro ao liberar mouse_ev (dispositivo pode ter sido desconectado): {exc}")
        finally:
            try:
                if self.mouse_ev: self.mouse_ev.close()
            except Exception as exc:
                log.debug(f"Erro ao fechar mouse_ev: {exc}")

    def _close_fds(self):
        for fd in list(self.fds.keys()):
            try: os.close(fd)
            except OSError: pass
        self.fds.clear()

    def run(self):
        try:
            self._run_loop()
        except Exception as exc:
            # Sem isto, qualquer exceção inesperada mataria a thread deixando
            # o teclado do usuário capturado.
            log.exception(f"HardwareReader encerrou por erro inesperado: {exc}")
        finally:
            self._close_fds()
            self._release_evdev()
            log.info("HardwareReader finalizado; dispositivos liberados.")

    def _scan_hidraw(self):
        """Descobre os nós hidraw do passador (botões e bateria)."""
        # `permission_denied` distingue "passador ausente" de "passador
        # presente mas sem regra udev" — a causa de suporte nº 1. Antes
        # o `except OSError: pass` engolia os dois e o usuário só via
        # "nada acontece".
        permission_denied = []
        # #23: antes usava range(20) fixo. Numa máquina com muitas
        # interfaces HID o passador pode receber hidraw20+ e nunca ser
        # encontrado. Agora enumeramos o que existe de verdade no sysfs.
        try:
            hidraw_nodes = sorted(os.listdir("/sys/class/hidraw"))
        except OSError as exc:
            log.warning(f"Não foi possível enumerar /sys/class/hidraw: {exc}")
            hidraw_nodes = []

        for nome in hidraw_nodes:
            path = f"/sys/class/hidraw/{nome}/device/uevent"
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        uevent = f.read()
                        # O kernel publica HID_ID como bus:vendor:product.
                        # Ler exclusivamente esse campo evita falso positivo
                        # em outros atributos do uevent que contenham os IDs.
                        hid_id = re.search(
                            r"(?mi)^HID_ID\s*=\s*([0-9a-f]+):([0-9a-f]+):([0-9a-f]+)\s*$",
                            uevent,
                        )
                        if hid_id and (
                            int(hid_id.group(2), 16) == int(self.vendor_id_hex, 16)
                            and int(hid_id.group(3), 16) == int(self.product_id_hex, 16)
                        ):
                            node = f"/dev/{nome}"
                            self.fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
                            log.info(f"Conexão Baseus estabelecida: {node}")
                except PermissionError:
                    permission_denied.append(f"/dev/{nome}")
                    log.debug(f"Permissão negada em /dev/{nome}")
                except OSError as exc:
                    log.debug(f"Ignorando {nome}: {exc}")

        if permission_denied and not self.fds:
            log.error(
                "Passador detectado, mas SEM PERMISSÃO de leitura em "
                f"{', '.join(permission_denied)}. Instale a regra udev "
                "(veja o README / install.sh) ou rode como root."
            )
            self.permission_error.emit(
                tr('⚠️ Sem permissão para ler o passador! Verifique as regras udev.')
            )

    def _scan_evdev(self):
        """Descobre e virtualiza as interfaces evdev (giroscópio/laser)."""
        if not EVDEV_AVAILABLE:
            return

        self._release_evdev()
        self.kbd = None
        self.mouse_ev = None

        grabbed = []  # #11: rastreia o que já foi capturado, p/ rollback
        try:
            v_id = int(self.vendor_id_hex, 16)
            p_id = int(self.product_id_hex, 16)
            for path in list_devices():
                dev = InputDevice(path)
                if dev.info.vendor != v_id or dev.info.product != p_id:
                    # InputDevice abre um FD no construtor; não deixe aberto
                    # um periférico que não pertence ao passador.
                    try: dev.close()
                    except Exception: pass
                    continue
                if 'Keyboard' in dev.name:
                    if self.kbd:
                        try: self.kbd.close()
                        except Exception: pass
                    self.kbd = dev
                elif 'Mouse' in dev.name:
                    if self.mouse_ev:
                        try: self.mouse_ev.close()
                        except Exception: pass
                    self.mouse_ev = dev
                else:
                    # Mesmo vendor/product, mas interface sem papel usado
                    # pelo virtualizador.
                    try: dev.close()
                    except Exception: pass

            if self.kbd and self.mouse_ev:
                # #11: se UInput.from_device() falhar (ex.: sem permissão em
                # /dev/uinput), os dois grab() já foram feitos. Antes o
                # código só logava o erro e seguia: os dispositivos FÍSICOS
                # ficavam capturados e, com self.ui vazio, nada era
                # reencaminhado — o passador parava de funcionar por
                # completo, sem o usuário poder nem usá-lo normalmente.
                try:
                    self.kbd.grab(); grabbed.append(self.kbd)
                    self.mouse_ev.grab(); grabbed.append(self.mouse_ev)
                    self.ui = UInput.from_device(self.kbd, self.mouse_ev, name='baseus-virtual')
                    log.info("Giroscópio virtualizado com sucesso!")
                except Exception:
                    # Desfaz TODAS as capturas antes de propagar.
                    for dev_grabbed in grabbed:
                        try: dev_grabbed.ungrab()
                        except Exception as exc_ungrab:
                            log.warning(f"Falha ao desfazer grab: {exc_ungrab}")
                        try: dev_grabbed.close()
                        except Exception as exc_close:
                            log.debug(f"Falha ao fechar dispositivo após rollback: {exc_close}")
                    self.ui = None
                    self.kbd = None
                    self.mouse_ev = None
                    raise
            elif self.kbd or self.mouse_ev:
                # #12: encontrar apenas UMA das duas interfaces deixava
                # self.kbd=None com self.mouse_ev válido. O loop então
                # acessava self.kbd.fd e estourava AttributeError. Sem as
                # duas não há virtualização possível, então descartamos.
                log.warning(
                    "Apenas uma interface evdev do passador foi encontrada "
                    f"(kbd={bool(self.kbd)}, mouse={bool(self.mouse_ev)}). "
                    "Giroscópio desativado até as duas aparecerem."
                )
                for dev in (self.kbd, self.mouse_ev):
                    try:
                        if dev: dev.close()
                    except Exception:
                        pass
                self.kbd = None
                self.mouse_ev = None
        except PermissionError as exc:
            log.error(
                f"Sem permissão para acessar os dispositivos evdev ({exc}). "
                "Verifique as regras udev e reconecte o passador."
            )
            self.permission_error.emit(
                tr('⚠️ Sem permissão no giroscópio! Verifique as regras udev.')
            )
        except Exception as exc:
            log.exception(f"Erro no giroscópio: {exc}")

    def _scan_devices(self):
        """
        (Re)descobre o passador: hidraw (botões/bateria) e evdev (giroscópio).

        Extraído de uma closure dentro de _run_loop para poder ser testado
        isoladamente, sem iniciar a thread nem precisar do hardware físico.
        """
        self._close_fds()
        self._scan_hidraw()
        self._scan_evdev()

    def _run_loop(self):
        log.info("Iniciando monitoramento USB (Hidraw + Evdev)...")

        if pyudev:
            context = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem='hidraw')
            monitor.start()
        else:
            monitor = None

        scan_devices = self._scan_devices  # alias local (usado no loop abaixo)

        # Roda a busca inicial
        scan_devices()

        last_click_time = 0; last_gyro_time = 0; press_time = 0
        is_drawing = False; is_pen_drawing = False; just_toggled = False; active_tool = None 
        DEBOUNCE = 0.5; last_rec_toggle = 0; last_translate_toggle = 0
        is_recording = False; is_translating = False

        while self.running:
            # #12: mapa fd -> dispositivo evdev. Antes o loop fazia
            # `self.kbd if fd == self.kbd.fd else self.mouse_ev`, que estoura
            # AttributeError quando self.kbd é None (só o mouse encontrado).
            evdev_por_fd = {}
            if self.kbd: evdev_por_fd[self.kbd.fd] = self.kbd
            if self.mouse_ev: evdev_por_fd[self.mouse_ev.fd] = self.mouse_ev

            watch_fds = list(self.fds.keys())
            if monitor: watch_fds.append(monitor.fileno())
            watch_fds.extend(evdev_por_fd.keys())

            if not watch_fds:
                time.sleep(1)
                if not monitor: scan_devices()
                continue

            try:
                r, w, x = select.select(watch_fds, [], [], 0.05)
            except (OSError, ValueError) as exc:
                # #22: um fd já inválido (dispositivo removido) faz o select
                # falhar com EBADF indefinidamente. Força um rescan em vez de
                # repetir o erro para sempre.
                log.warning(f"select() falhou ({exc}); reescaneando dispositivos.")
                scan_devices()
                continue

            for fd in r:
                
                # ---- SENSOR 1: EVDEV (O Movimento da Lupa/Laser) ----
                if EVDEV_AVAILABLE and fd in evdev_por_fd:
                    dev = evdev_por_fd[fd]
                    try:
                        for ev in dev.read():
                            if ev.type == e.EV_KEY:
                                if ev.code == e.KEY_B: continue
                                # #13 (revisado após teste manual): o filtro
                                # cobria só BTN_LEFT/KEY_ESC, mas o passador
                                # emite OUTRAS teclas via evdev durante o
                                # pincel (ex.: Ctrl+P, "E" — reproduzido
                                # manualmente: abria a paleta de comandos do
                                # VS Code e digitava "e" nos campos de
                                # texto). Qualquer tecla não filtrada nesse
                                # modo era encaminhada ao sistema como um
                                # atalho de teclado real. Agora TODA tecla é
                                # bloqueada durante o desenho — o pincel usa
                                # apenas o movimento (EV_REL), nunca teclado.
                                if is_pen_drawing:
                                    if ev.value == 0 and ev.code in self._forwarded_pressed:
                                        pass  # deixa a soltura passar (abaixo), nunca prende a tecla
                                    else:
                                        continue
                                # Rastreia o estado real do que encaminhamos.
                                if ev.value == 1:
                                    self._forwarded_pressed.add(ev.code)
                                elif ev.value == 0:
                                    self._forwarded_pressed.discard(ev.code)
                            if self.ui: 
                                self.ui.write_event(ev); self.ui.syn()
                    except OSError as exc:
                        # Dispositivo desconectado no meio da leitura.
                        log.debug(f"Leitura evdev falhou ({exc}); agendando rescan.")
                        self._rescan_requested = True
                    continue

                # ---- SENSOR 2: HOTPLUG (Colocar/Tirar do USB) ----
                if monitor and fd == monitor.fileno():
                    device = monitor.poll(0)
                    if device and device.action in ['add', 'remove']:
                        self._rescan_requested = True  # Agenda rescan seguro
                    continue

                # ---- SENSOR 3: HIDRAW (Os Botões Baseus) ----
                try:
                    data = os.read(fd, 64)
                except OSError as exc:
                    # #22: antes era `except OSError: continue`, e um fd de
                    # dispositivo removido continuava monitorado — o select
                    # o reportava como pronto a cada volta e a leitura
                    # falhava indefinidamente (busy loop), sem nunca
                    # redescobrir o dispositivo. Agora o fd morto é fechado
                    # e um rescan é agendado.
                    log.debug(f"Leitura de {self.fds.get(fd)} falhou ({exc}); removendo fd.")
                    try: os.close(fd)
                    except OSError: pass
                    self.fds.pop(fd, None)
                    self._rescan_requested = True
                    continue
                if not data: continue
                
                try:
                    if data[0] == 0x0A:
                        self.battery_update.emit(tr('🔋 Bateria: {0}%', data[3]))
                        comando = data[5]
                        
                        if comando in [0x71, 0x72, 0x73]:
                            active_tool = "LASER"; curr = time.time()
                            if curr - last_click_time < 0.4:
                                self.toggle_mode.emit(); self.pointer_active.emit(True)
                                last_click_time = 0; just_toggled = True; press_time = curr
                            else: 
                                last_click_time = curr; press_time = curr; just_toggled = False
                            last_gyro_time = time.time()
                            if not is_drawing: self.pointer_active.emit(True); is_drawing = True
                        
                        elif comando == 0x68:
                            active_tool = "PEN"; last_gyro_time = time.time()
                            if not is_pen_drawing: self.pen_active.emit(True); is_pen_drawing = True
                        elif comando == 0x67:
                            # O Verdadeiro Apagador (Clique Curto)
                            log.debug("Borracha acionada pelo passador!")
                            self.pen_clear.emit()
                            
                        elif comando in [0x69, 0x6a, 0x6c]:
                            # 0x69 = Soltou o botão do pincel (o fim do traço é gerido pelo giroscópio)
                            # 0x6a e 0x6c = Passar Slides (o Linux já entende isso nativamente)
                            # Não fazemos nada com eles aqui para evitar bugs visuais!
                            pass
                        elif comando == 0x6d: self.black_screen_toggle.emit()
                        
                        # A INVERSÃO DEFINITIVA CALCULADA!
                        elif comando in [0x75, 0x76, 0x77]: # MICROFONE FÍSICO
                            now = time.time()
                            if now - last_rec_toggle > DEBOUNCE:
                                is_recording = not is_recording; last_rec_toggle = now
                                self.record_toggled.emit(is_recording)
                                
                        elif comando in [0x7a, 0x7c, 0x7d]: # TRADUÇÃO FÍSICA
                            now = time.time()
                            if now - last_translate_toggle > DEBOUNCE:
                                is_translating = not is_translating; last_translate_toggle = now
                                self.translate_toggled.emit(is_translating)
                                
                    elif data[0] == 0x02:
                        if active_tool in ["LASER", "PEN"]: last_gyro_time = time.time()
                        if active_tool == "LASER" and not is_drawing and last_click_time > 0:
                            self.pointer_active.emit(True); is_drawing = True
                        elif active_tool == "PEN" and not is_pen_drawing:
                            self.pen_active.emit(True); is_pen_drawing = True
                except IndexError: pass

            if time.time() - last_gyro_time > 0.3:
                if is_drawing:
                    self.pointer_active.emit(False); is_drawing = False
                if is_pen_drawing:
                    self.pen_active.emit(False); is_pen_drawing = False
                active_tool = None

            # Rescan seguro APÓS o select (evita FD stale)
            if self._rescan_requested:
                self._rescan_requested = False
                time.sleep(0.5)
                scan_devices()

        # A limpeza agora vive no finally de run(), garantindo que rode
        # inclusive se este loop levantar uma exceção.

    def stop(self):
        self.running = False
        if not self.wait(3000):
            # Deixar a thread viva aqui significaria manter o grab do teclado.
            log.error("HardwareReader não encerrou em 3s; forçando terminate().")
            self.terminate()
            self.wait(1000)
            # terminate() aborta a thread sem rodar o finally de run(), então
            # a liberação é feita aqui, na thread que chamou stop().
            self._close_fds()
            self._release_evdev()
