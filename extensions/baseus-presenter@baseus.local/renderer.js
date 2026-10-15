import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Pango from 'gi://Pango';
import Shell from 'gi://Shell';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const PASSIVE = {reactive: false, can_focus: false, track_hover: false};
const MAX_STROKES = 500;
const MAX_POINTS = 2000;
const MAX_STROKE_PIXELS = 8_000_000;

function color(cr, hex) {
    const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
    cr.setSourceRGB(...rgb);
}

export class Renderer {
    constructor() {
        this._actors = new Set();
        this._stageActors = new Set();
        this._strokes = [];
        this._tools = null;
        this._current = null;
        this._clearSerial = null;
        this._penSerial = null;
        this._cursorTracker = global.backend?.get_cursor_tracker?.() ??
            (Meta?.CursorTracker?.get_for_display ? Meta.CursorTracker.get_for_display(global.display) : null);
        this._cursorHidden = false;
    }

    _add(actor) {
        this._actors.add(actor);
        Main.layoutManager.addTopChrome(actor, {
            affectsInputRegion: false, trackFullscreen: false,
        });
        return actor;
    }

    _drop(actor) {
        this._actors.delete(actor);
        try {
            if (!this._stageActors.delete(actor))
                Main.layoutManager.removeChrome(actor);
        } finally {
            actor.destroy();
        }
    }

    _setCursorHidden(hidden) {
        if (this._cursorHidden === hidden)
            return;
        this._cursorHidden = hidden;
        try {
            this._cursorTracker?.set_pointer_visible(!hidden);
        } catch (error) {
            console.error(`[BASEUS] set_pointer_visible: ${error}`);
        }
    }

    reset() {
        this._setCursorHidden(false);
        for (const actor of [...this._actors]) {
            try {
                this._drop(actor);
            } catch (error) {
                console.error(`[BASEUS] actor cleanup: ${error}`);
            }
        }
        this._strokes = [];
        this._current = null;
        this._tools = null;
        this._clearSerial = null;
        this._penSerial = null;
    }

    _clearPen() {
        for (const stroke of this._strokes)
            this._drop(stroke.actor);
        this._strokes = [];
        this._current = null;
    }

    _makeTools(monitor, visual) {
        if (this._tools) {
            if (this._tools.lensRoot)
                this._drop(this._tools.lensRoot);
            this._drop(this._tools.root);
        }
        const root = this._add(new St.Widget({...PASSIVE,
            x: monitor.x, y: monitor.y, width: monitor.width, height: monitor.height,
            clip_to_allocation: true}));
        const laser = new St.Widget({...PASSIVE});
        root.add_child(laser);
        const shade = new St.Widget({...PASSIVE, width: monitor.width,
            height: monitor.height, clip_to_allocation: true});
        root.add_child(shade);
        const panels = Array.from({length: 4}, () => {
            const panel = new St.Widget({...PASSIVE});
            shade.add_child(panel);
            return panel;
        });
        // Cache just the circular cutout; moving it never repaints a full monitor.
        const hole = new St.DrawingArea({...PASSIVE,
            width: visual.spotlight_size, height: visual.spotlight_size});
        hole.connect('repaint', area => {
            const cr = area.get_context();
            try {
                const [w, h] = area.get_surface_size();
                cr.setSourceRGBA(0, 0, 0, visual.spotlight_opacity / 255);
                cr.paint();
                cr.setOperator(Cairo.Operator.CLEAR);
                cr.arc(w / 2, h / 2, w / 2, 0, Math.PI * 2);
                cr.fill();
            } finally {
                cr.$dispose();
            }
        });
        shade.add_child(hole);
        const subtitle = new St.Label({...PASSIVE,
            style: 'font-size: 24px; font-weight: bold; color: white; background-color: rgba(0,0,0,0.8); padding: 12px; border-radius: 10px;'});
        subtitle.clutter_text.set_line_wrap(true);
        subtitle.clutter_text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR);
        subtitle.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
        subtitle.set_size(Math.round(monitor.width * 0.8), 110);
        subtitle.set_position(Math.round(monitor.width * 0.1), monitor.height - 150);
        root.add_child(subtitle);
        const black = new St.Widget({...PASSIVE, width: monitor.width,
            height: monitor.height, style: 'background-color: black;'});
        root.add_child(black);
        const dim = `background-color: rgba(0,0,0,${visual.spotlight_opacity / 255});`;
        panels.forEach(panel => panel.set_style(dim));
        laser.set_size(visual.laser_size, visual.laser_size);
        laser.set_style(`background-color: ${visual.laser_color}; border-radius: ${visual.laser_size / 2}px;`);
        this._tools = {root, laser, shade, panels, hole, lensRoot: null, lens: null, clone: null, lensBorder: null,
            subtitle, black, monitor, key: JSON.stringify(visual)};
    }

    _makeLens(monitor, visual) {
        // Match GNOME's magnifier: sized uiGroup source, lens outside that subtree.
        // MetaWindowGroup reports natural size 0; Clone allocation would divide by 0.
        const lensRoot = new St.Widget({...PASSIVE,
            x: monitor.x, y: monitor.y, width: monitor.width, height: monitor.height,
            clip_to_allocation: true});
        this._actors.add(lensRoot);
        this._stageActors.add(lensRoot);
        global.stage.add_child(lensRoot);
        Shell.util_set_hidden_from_pick(lensRoot, true);
        console.log(`[BASEUS] magnifier source=uiGroup size=${Main.uiGroup.get_size().join('x')}`);
        const lens = new St.Widget({...PASSIVE, width: visual.lupa_size,
            height: visual.lupa_size, clip_to_allocation: true,
            style: 'background-color: black;'});
        lensRoot.add_child(lens);
        const clone = new Clutter.Clone({source: Main.uiGroup,
            reactive: false, clip_to_allocation: true, scale_x: 2, scale_y: 2});
        lens.add_child(clone);
        if (visual.lupa_shape === 'circular') {
            const mask = new Clutter.ShaderEffect({
                shader_type: Clutter.ShaderType.FRAGMENT_SHADER});
            const accepted = mask.set_shader_source(`
                uniform sampler2D tex;
                void main() {
                    vec2 uv = cogl_tex_coord_in[0].st;
                    vec4 pixel = texture2D(tex, uv) * cogl_color_in;
                    float inside = 1.0 - smoothstep(0.49, 0.5, length(uv - vec2(0.5)));
                    cogl_color_out = pixel * inside;
                }`);
            if (!accepted)
                throw new Error('Magnifier mask shader rejected');
            mask.set_uniform_value('tex', 0);
            lens.add_effect_with_name('baseus-circle', mask);
        }
        const lensBorder = new St.Widget({...PASSIVE,
            width: visual.lupa_size, height: visual.lupa_size,
            style: `border: 3px solid white; border-radius: ${visual.lupa_shape === 'circular' ? visual.lupa_size / 2 : 0}px;`});
        lensRoot.add_child(lensBorder);
        return {lensRoot, lens, clone, lensBorder};
    }

    _positionShade(x, y, monitor, visual) {
        const {panels, hole} = this._tools;
        const r = visual.spotlight_size / 2;
        const left = Math.max(0, x - r);
        const right = Math.min(monitor.width, x + r);
        const top = Math.max(0, y - r);
        const bottom = Math.min(monitor.height, y + r);
        const rects = [[0, 0, monitor.width, top],
            [0, bottom, monitor.width, monitor.height - bottom],
            [0, top, left, bottom - top],
            [right, top, monitor.width - right, bottom - top]];
        panels.forEach((panel, i) => {
            panel.set_position(rects[i][0], rects[i][1]);
            panel.set_size(rects[i][2], rects[i][3]);
        });
        hole.set_position(x - r, y - r);
    }

    _pen(x, y, monitor, hex) {
        let stroke = this._current;
        if (!stroke || stroke.monitor !== monitor || stroke.points.length >= MAX_POINTS) {
            const actor = this._add(new St.DrawingArea({...PASSIVE}));
            stroke = {actor, monitor, points: [], hex, pixels: 0};
            this._strokes.push(stroke);
            this._current = stroke;
            actor.connect('repaint', area => {
                const cr = area.get_context();
                try {
                    color(cr, stroke.hex);
                    cr.setLineWidth(5);
                    cr.setLineCap(Cairo.LineCap.ROUND);
                    cr.setLineJoin(Cairo.LineJoin.ROUND);
                    const first = stroke.points[0];
                    if (first) {
                        cr.moveTo(first[0] - stroke.left, first[1] - stroke.top);
                        for (const point of stroke.points)
                            cr.lineTo(point[0] - stroke.left, point[1] - stroke.top);
                        cr.stroke();
                    }
                } finally {
                    cr.$dispose();
                }
            });
        }
        const last = stroke.points[stroke.points.length - 1];
        if (last && last[0] === x && last[1] === y)
            return;
        stroke.points.push([x, y]);
        const xs = stroke.points.map(p => p[0]);
        const ys = stroke.points.map(p => p[1]);
        stroke.left = Math.max(monitor.x, Math.min(...xs) - 4);
        stroke.top = Math.max(monitor.y, Math.min(...ys) - 4);
        const width = Math.min(monitor.x + monitor.width, Math.max(...xs) + 4) - stroke.left;
        const height = Math.min(monitor.y + monitor.height, Math.max(...ys) + 4) - stroke.top;
        if (width * height > MAX_STROKE_PIXELS) {
            stroke.points.pop();
            this._current = null;
            this._pen(x, y, monitor, hex);
            return;
        }
        stroke.actor.set_position(stroke.left, stroke.top);
        stroke.actor.set_size(width, height);
        stroke.pixels = width * height;
        stroke.actor.queue_repaint();
        let pixels = this._strokes.reduce((sum, s) => sum + s.pixels, 0);
        while (this._strokes.length > MAX_STROKES ||
            (pixels > MAX_STROKE_PIXELS && this._strokes.length > 1)) {
            const removed = this._strokes.shift();
            pixels -= removed.pixels;
            this._drop(removed.actor);
        }
    }

    render(state) {
        // A release/press pair may be coalesced by the async transport.
        if (state.pen_serial !== this._penSerial) {
            this._current = null;
            this._penSerial = state.pen_serial;
        }
        if (state.clear_serial !== this._clearSerial) {
            this._clearPen();
            this._clearSerial = state.clear_serial;
        }
        const [gx, gy] = global.get_pointer();
        const monitor = Main.layoutManager.monitors.find(m =>
            gx >= m.x && gx < m.x + m.width && gy >= m.y && gy < m.y + m.height);
        if (!monitor) {
            this._tools?.root.hide();
            this._tools?.lensRoot?.hide();
            this._current = null;
            this._setCursorHidden(false);
            return;
        }
        if (!state.pen || state.black)
            this._current = null;
        const v = state.visual;
        if (state.pen && !state.black)
            this._pen(gx, gy, monitor, v.pincel_color);
        for (const stroke of this._strokes) {
            stroke.actor.visible = !state.black;
            if (stroke.hex !== v.pincel_color) {
                stroke.hex = v.pincel_color;
                stroke.actor.queue_repaint();
            }
        }
        const shouldHideCursor = Boolean(state.black || state.active || state.pen);
        this._setCursorHidden(shouldHideCursor);
        if (!(state.active || state.black || state.subtitle)) {
            this._tools?.root.hide();
            this._tools?.lensRoot?.hide();
            return;
        }
        if (!this._tools || this._tools.monitor !== monitor || this._tools.key !== JSON.stringify(v))
            this._makeTools(monitor, v);
        const t = this._tools;
        t.root.show();
        const active = state.active && !state.black;
        const x = gx - monitor.x;
        const y = gy - monitor.y;
        t.black.visible = state.black;
        t.laser.visible = active && state.mode === 'LASER';
        t.shade.visible = active && state.mode === 'SPOTLIGHT';
        if (active && state.mode === 'LUPA' && !t.lens) {
            Object.assign(t, this._makeLens(monitor, v));
        }
        if (t.lens)
            t.lensRoot.visible = t.lens.visible = t.lensBorder.visible = active && state.mode === 'LUPA';
        t.subtitle.visible = Boolean(state.subtitle) && !state.black;
        if (t.subtitle.text !== state.subtitle)
            t.subtitle.set_text(state.subtitle);
        t.laser.set_position(x - v.laser_size / 2, y - v.laser_size / 2);
        if (t.shade.visible)
            this._positionShade(x, y, monitor, v);
        if (t.lens?.visible) {
            t.lens.set_position(x - v.lupa_size / 2, y - v.lupa_size / 2);
            t.lensBorder.set_position(x - v.lupa_size / 2, y - v.lupa_size / 2);
            t.clone.set_position(v.lupa_size / 2 - gx * 2, v.lupa_size / 2 - gy * 2);
        }
    }
}
