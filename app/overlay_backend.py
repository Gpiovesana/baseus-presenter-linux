"""Select by desktop session, independently of the GUI's Qt platform plugin."""
import os


def create_overlay(config, on_error=None, on_recovered=None):
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        from .gnome_extension import prepare_wayland_extension
        warning = prepare_wayland_extension()
        from .overlay_wayland import WaylandOverlay
        return WaylandOverlay(config, on_error=on_error, on_recovered=on_recovered,
                              preparation_warning=warning)
    from .overlay import PointerWindow
    return PointerWindow(config)
