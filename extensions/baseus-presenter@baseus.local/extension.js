import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Session} from './protocol.js';
import {Renderer} from './renderer.js';

const XML = `<node><interface name="org.gnome.Shell.Extensions.BaseusPresenter1">
<method name="Update"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
<method name="Release"/>
</interface></node>`;

export default class BaseusPresenter extends Extension {
    enable() {
        this._timer = 0;
        this._monitorSignal = 0;
        this._watch = 0;
        this._session = new Session();
        try {
            this._renderer = new Renderer();
            this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
            this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/BaseusPresenter');
            this._monitorSignal = Main.layoutManager.connect('monitors-changed', () => {
                this._renderer.reset();
            });
            console.log('[BASEUS] overlay service ready (protocol 1)');
        } catch (error) {
            this.disable();
            throw error;
        }
    }

    _startTimer() {
        if (this._timer)
            return;
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 16, () => {
            try {
                if (this._session.expire(GLib.get_monotonic_time() / 1000)) {
                    this._timer = 0;
                    this._reset();
                    return GLib.SOURCE_REMOVE;
                }
                this._renderer.render(this._session.state);
                return GLib.SOURCE_CONTINUE;
            } catch (error) {
                console.error(`[BASEUS] render stopped: ${error.stack ?? error}`);
                this._timer = 0;
                this._session.release(this._session.owner);
                this._reset();
                return GLib.SOURCE_REMOVE;
            }
        });
    }

    UpdateAsync([payload], invocation) {
        try {
            const sender = invocation.get_sender();
            const changedOwner = this._session.update(sender, payload,
                GLib.get_monotonic_time() / 1000);
            if (changedOwner) {
                this._reset();
                this._watch = Gio.bus_watch_name_on_connection(Gio.DBus.session, sender,
                    Gio.BusNameWatcherFlags.NONE, null, () => {
                        if (this._session?.release(sender))
                            this._reset();
                    });
            }
            // Apply releases immediately, not just on the next display tick.
            this._renderer.render(this._session.state);
            this._startTimer();
            invocation.return_value(new GLib.Variant('(b)', [true]));
        } catch (error) {
            if (this._session.release(invocation.get_sender()))
                this._reset();
            invocation.return_dbus_error('org.gnome.Shell.Extensions.BaseusPresenter.Error',
                String(error.message));
        }
    }

    ReleaseAsync(params, invocation) {
        if (this._session.release(invocation.get_sender()))
            this._reset();
        invocation.return_value(null);
    }

    _reset() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = 0;
        }
        if (this._watch) {
            Gio.bus_unwatch_name(this._watch);
            this._watch = 0;
        }
        this._renderer?.reset();
    }

    disable() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = 0;
        }
        if (this._monitorSignal) {
            Main.layoutManager.disconnect(this._monitorSignal);
            this._monitorSignal = 0;
        }
        this._reset();
        this._dbus?.unexport();
        this._dbus = null;
        this._renderer = null;
        this._session = null;
    }
}
