"""Own an XFixes cursor-hide reference on a dedicated X11 connection."""
import ctypes as C

from .logger import get_logger

log = get_logger(__name__)


class X11Cursor:
    def __init__(self):
        self._display = None
        self._hidden = False
        try:
            self._x = C.CDLL('libX11.so.6')
            self._fixes = C.CDLL('libXfixes.so.3')
            self._bind(self._x.XOpenDisplay, [C.c_char_p], C.c_void_p)
            self._bind(self._x.XCloseDisplay, [C.c_void_p], C.c_int)
            self._bind(self._x.XScreenCount, [C.c_void_p], C.c_int)
            self._bind(self._x.XRootWindow, [C.c_void_p, C.c_int], C.c_ulong)
            self._bind(self._x.XFlush, [C.c_void_p], C.c_int)
            self._bind(self._fixes.XFixesQueryVersion,
                       [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)], C.c_int)
            for name in ('XFixesHideCursor', 'XFixesShowCursor'):
                self._bind(getattr(self._fixes, name),
                           [C.c_void_p, C.c_ulong], None)
            self._display = self._x.XOpenDisplay(None)
            if not self._display:
                raise RuntimeError('XOpenDisplay failed')
            major, minor = C.c_int(4), C.c_int(0)
            if (not self._fixes.XFixesQueryVersion(
                    self._display, C.byref(major), C.byref(minor)) or major.value < 4):
                raise RuntimeError('XFixes 4 or newer required')
            self._roots = [self._x.XRootWindow(self._display, i)
                           for i in range(self._x.XScreenCount(self._display))]
        except (OSError, AttributeError, RuntimeError) as error:
            self.close()
            log.warning('Ocultação nativa do cursor X11 indisponível: %s', error)

    @staticmethod
    def _bind(function, args, result):
        function.argtypes = args
        function.restype = result

    def set_hidden(self, hidden):
        hidden = bool(hidden)
        if not self._display or hidden == self._hidden:
            return
        operation = (self._fixes.XFixesHideCursor if hidden
                     else self._fixes.XFixesShowCursor)
        for root in self._roots:
            operation(self._display, root)
        self._x.XFlush(self._display)
        self._hidden = hidden

    def close(self):
        if self._display:
            self.set_hidden(False)
            # Disconnect also releases this client's server-side references.
            self._x.XCloseDisplay(self._display)
            self._display = None
