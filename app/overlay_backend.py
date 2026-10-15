"""Select by desktop session, independently of the GUI's Qt platform plugin."""
import os


def create_overlay(config, on_error=None, on_recovered=None):
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        from .overlay_wayland import WaylandOverlay
        return WaylandOverlay(config, on_error=on_error, on_recovered=on_recovered)
    from .overlay import PointerWindow
    return PointerWindow(config)
