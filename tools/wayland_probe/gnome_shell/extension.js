import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Disposable capability probe, not a production overlay backend.
export default class BaseusOverlayProbe extends Extension {
    enable() {
        this._actors = [];
        this._tickId = 0;
        this._timeoutId = 0;
        let ticks = 0;
        const focusAtStart = global.display.focus_window;
        try {
            this._timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
                this._timeoutId = 0;
                this._cleanup();
                console.log('[BASEUS-PROBE] finished; actors removed');
                return GLib.SOURCE_REMOVE;
            });
            for (const monitor of Main.layoutManager.monitors) {
                const border = new St.Widget({
                    reactive: false, can_focus: false, track_hover: false,
                    x: monitor.x, y: monitor.y,
                    width: monitor.width, height: monitor.height,
                    style: 'border: 5px solid #00ff66;',
                });
                this._add(border);
                console.log(`[BASEUS-PROBE] monitor ${monitor.index}: ${monitor.x},${monitor.y} ${monitor.width}x${monitor.height}`);
            }
            const dot = new St.Widget({
                reactive: false, can_focus: false, track_hover: false,
                width: 20, height: 20,
                style: 'background-color: #ff00cc; border-radius: 10px;',
            });
            this._add(dot);
            const children = Main.uiGroup.get_children();
            console.log(`[BASEUS-PROBE] stacking windows=${children.indexOf(global.window_group)} topWindows=${children.indexOf(global.top_window_group)} probe=${this._actors.map(a => children.indexOf(a)).join(',')}`);
            const sample = () => {
                const [x, y] = global.get_pointer();
                dot.set_position(x - 10, y - 10);
                if (ticks++ % 20 === 0) {
                    const focus = global.display.focus_window;
                    console.log(`[BASEUS-PROBE] pointer=${x},${y} focus=${focus?.get_wm_class() ?? 'none'} unchanged=${focus === focusAtStart}`);
                }
            };
            sample();
            this._tickId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
                try {
                    sample();
                    return GLib.SOURCE_CONTINUE;
                } catch (error) {
                    this._tickId = 0;
                    this._cleanup();
                    console.error(`[BASEUS-PROBE] stopped: ${error}`);
                    return GLib.SOURCE_REMOVE;
                }
            });
        } catch (error) {
            this._cleanup();
            throw error;
        }
    }

    _add(actor) {
        this._actors.push(actor);
        Main.layoutManager.addTopChrome(actor, {
            affectsInputRegion: false, trackFullscreen: false,
        });
    }

    _cleanup() {
        for (const key of ['_tickId', '_timeoutId']) {
            if (this[key]) {
                GLib.Source.remove(this[key]);
                this[key] = 0;
            }
        }
        for (const actor of this._actors ?? []) {
            try {
                Main.layoutManager.removeChrome(actor);
            } catch (error) {
                console.error(`[BASEUS-PROBE] removeChrome: ${error}`);
            }
            actor.destroy();
        }
        this._actors = [];
    }

    disable() {
        this._cleanup();
    }
}
