"""Private-bus fixture: no GNOME, windows, hardware or session settings."""
import json
import sys
from gi.repository import Gio, GLib

connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus', 'RequestName',
                     GLib.Variant('(su)', ('org.baseus.OverlayTest', 0)), None,
                     Gio.DBusCallFlags.NONE, 1000, None)
xml = '''<node><interface name="org.gnome.Shell.Extensions.BaseusPresenter1">
<method name="Update"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
<method name="Release"/></interface></node>'''


def method(conn, sender, path, interface, name, parameters, invocation):
    with open(sys.argv[1], 'a', encoding='utf-8') as log:
        event = {'method': name}
        if name == 'Update':
            event['state'] = json.loads(parameters.unpack()[0])
        log.write(json.dumps(event) + '\n')
    invocation.return_value(GLib.Variant('(b)', (True,)) if name == 'Update' else None)


connection.register_object('/org/gnome/Shell/Extensions/BaseusPresenter',
    Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], method, None, None)
print('READY', flush=True)
GLib.MainLoop().run()
