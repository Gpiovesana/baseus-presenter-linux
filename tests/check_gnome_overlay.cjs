const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../extensions/baseus-presenter@baseus.local');

async function main() {
    const {parseState, Session} = await import('data:text/javascript,' +
        encodeURIComponent(fs.readFileSync(path.join(root, 'protocol.js'), 'utf8')));
    const state = {protocol: 1, active: false, mode: 'LASER', pen: false, pen_serial: 0,
        black: false, clear_serial: 0, subtitle: '', visual: {
            laser_size: 30, laser_color: '#FF0000', pincel_color: '#FF0000',
            lupa_size: 250, lupa_shape: 'circular', spotlight_size: 300,
            spotlight_opacity: 160}};
    const payload = () => JSON.stringify(state);
    assert.equal(parseState(payload()).visual.laser_size, 30);
    assert.equal([...parseState(JSON.stringify({...state, subtitle: '😀'.repeat(2048)})).subtitle].length, 2048);
    for (const bad of ['null', '{}', 'x'.repeat(16385),
        JSON.stringify({...state, pen: 'true'}),
        JSON.stringify({...state, visual: {...state.visual, laser_color: 'red; evil'}})])
        assert.throws(() => parseState(bad));
    const session = new Session();
    assert.equal(session.update(':1.20', payload(), 0), true);
    assert.equal(session.update(':1.20', payload(), 1000), false);
    assert.throws(() => session.update(':1.21', payload(), 2000), /owns/);
    assert.equal(session.release(':1.21'), false);
    assert.equal(session.expire(4999), false);
    assert.equal(session.expire(5000), true);
    assert.equal(session.state, null);
    assert.equal(session.update(':1.21', payload(), 5001), true);
    assert.throws(() => session.update(':1.21', '{}', 6000));
    assert.equal(session.deadline, 9001); // Invalid payload cannot extend lease.
    assert.equal(session.release(':1.21'), true);

    const attached = new Set();
    const monitors = [{x: 0, y: 552, width: 1600, height: 900},
        {x: 1600, y: 0, width: 1920, height: 1080}];
    let cursor = [700, 800];
    class Actor {
        constructor(props = {}) {
            Object.assign(this, props); this.children = []; this.visible = true;
            this.clutter_text = {set_line_wrap() {}, set_line_wrap_mode() {}, set_ellipsize() {}};
        }
        add_child(a) { this.children.push(a); a.parent = this; }
        get_size() {return [this.width ?? 0, this.height ?? 0];}
        set_child_above_sibling() {}
        set_position(x, y) { this.x = x; this.y = y; }
        set_size(w, h) { this.width = w; this.height = h; }
        set_style(s) { this.style = s; }
        set_text(s) { this.text = s; }
        show() { this.visible = true; }
        hide() { this.visible = false; }
        add_effect_with_name() {}
        connect() {}
        queue_repaint() { this.repaints = (this.repaints || 0) + 1; }
        destroy() {
            this.destroyed = true;
            if (this.parent)
                this.parent.children = this.parent.children.filter(a => a !== this);
        }
    }
    const context = {
        console, Cairo: {}, St: {Widget: Actor, DrawingArea: Actor, Label: Actor},
        Clutter: {Clone: Actor, ShaderType: {FRAGMENT_SHADER: 1},
            ShaderEffect: class {set_shader_source() {return true;} set_uniform_value() {}}},
        Pango: {WrapMode: {WORD_CHAR: 1}, EllipsizeMode: {END: 1}},
        Shell: {util_set_hidden_from_pick(actor, hidden) {actor.hiddenFromPick = hidden;}},
        Meta: {CursorTracker: {get_for_display: () => ({set_pointer_visible(v) {context.cursorVisible = v;}})}},
        global: {get_pointer: () => cursor, window_group: new Actor(), stage: new Actor(),
            backend: {get_cursor_tracker: () => ({set_pointer_visible(v) {context.cursorVisible = v;}})}},
        Main: {uiGroup: new Actor({width: 3520, height: 1452}), layoutManager: {monitors,
            addTopChrome(a, props) {
                assert.equal(a.reactive, false);
                assert.equal(props.affectsInputRegion, false);
                attached.add(a);
            },
            removeChrome(a) {assert(attached.delete(a));},
        }},
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(root, 'renderer.js'), 'utf8')
        .replace(/^import .*;\n/gm, '').replace('export class Renderer', 'this.Renderer = class'), context);
    const renderer = new context.Renderer();
    state.active = true;
    renderer.render(state);
    assert.equal(context.cursorVisible, false); // Cursor hidden when tool is active.
    assert.equal(renderer._tools.monitor, monitors[0]);
    assert.equal(renderer._tools.laser.visible, true);
    assert.equal(renderer._tools.lens, null); // Magnifier resources are lazy.
    state.mode = 'SPOTLIGHT';
    renderer.render(state);
    const hole = renderer._tools.hole;
    cursor = [710, 810]; renderer.render(state);
    assert.equal(renderer._tools.hole, hole); // Movement reuses cached cutout.
    assert.equal(hole.repaints, undefined);
    state.mode = 'LUPA'; renderer.render(state);
    assert.equal(renderer._tools.clone.source, context.Main.uiGroup);
    assert.equal(renderer._tools.lensRoot.parent, context.global.stage);
    assert.equal(renderer._tools.lensRoot.hiddenFromPick, true);
    assert(!context.Main.uiGroup.children.includes(renderer._tools.lensRoot));
    state.pen = true;
    renderer.render(state);
    cursor = [720, 820]; renderer.render(state);
    assert.equal(renderer._strokes.length, 1);
    const oldStroke = renderer._strokes[0];
    state.pen_serial++;
    renderer.render(state);
    assert.equal(renderer._strokes.length, 2); // New gesture even if pen=false was coalesced.
    cursor = [1800, 500]; renderer.render(state);
    assert.equal(renderer._strokes.length, 3); // Never join across monitors.
    assert.equal(renderer._tools.monitor, monitors[1]);
    state.pen = false; state.active = false;
    renderer.render(state);
    assert.equal(context.cursorVisible, true); // Cursor visible when tools are idle.
    assert.equal(renderer._tools.root.visible, false);
    assert.equal(renderer._tools.lensRoot.visible, false);
    assert.equal(oldStroke.actor.destroyed, undefined);
    state.clear_serial++; renderer.render(state);
    assert.equal(renderer._strokes.length, 0);
    assert.equal(oldStroke.actor.destroyed, true);
    state.black = true; renderer.render(state);
    assert.equal(context.cursorVisible, false); // Cursor hidden during black screen.
    assert.equal(renderer._tools.black.visible, true);
    state.active = true; state.mode = 'LUPA'; renderer.render(state);
    assert.equal(renderer._tools.lens.visible, false);
    renderer.reset(); renderer.reset();
    assert.equal(context.cursorVisible, true); // Cursor restored on reset.
    assert.equal(attached.size, 0);
    assert.equal(context.global.stage.children.length, 0);

    const timers = new Map();
    const watches = new Map();
    let id = 0;
    let now = 0;
    context.Extension = class {};
    context.Session = Session;
    context.GLib = {
        PRIORITY_DEFAULT: 0, SOURCE_REMOVE: false, SOURCE_CONTINUE: true,
        get_monotonic_time: () => now * 1000,
        timeout_add(priority, interval, callback) {timers.set(++id, callback); return id;},
        Source: {remove(key) {assert(timers.delete(key));}},
        Variant: class {constructor(type, values) {this.values = values;}},
    };
    context.Gio = {
        DBusExportedObject: {wrapJSObject: () => ({export() {}, unexport() {}})},
        DBus: {session: {}}, BusNameWatcherFlags: {NONE: 0},
        bus_watch_name_on_connection(conn, sender, flags, appeared, vanished) {
            watches.set(++id, vanished); return id;
        },
        bus_unwatch_name(key) {assert(watches.delete(key));},
    };
    context.Main.layoutManager.connect = () => 1;
    context.Main.layoutManager.disconnect = () => {};
    vm.runInContext(fs.readFileSync(path.join(root, 'extension.js'), 'utf8')
        .replace(/^import .*;\n/gm, '').replace('export default class', 'this.Server = class'), context);
    const server = new context.Server();
    server.enable();
    assert.equal(timers.size, 0); // Extension idle does not poll at 60Hz.
    const invocation = sender => ({
        get_sender: () => sender, return_value() {},
        return_dbus_error(name, message) {this.error = message;},
    });
    state.black = false; state.active = true; state.mode = 'LASER';
    server.UpdateAsync([payload()], invocation(':1.30'));
    assert.equal(timers.size, 1);
    assert.equal(watches.size, 1);
    const outsider = invocation(':1.31');
    server.UpdateAsync([payload()], outsider);
    assert.match(outsider.error, /owns/);
    server.ReleaseAsync([], outsider);
    assert.equal(server._session.owner, ':1.30');
    server.ReleaseAsync([], invocation(':1.30'));
    assert.equal(timers.size, 0); assert.equal(watches.size, 0);
    assert.equal(attached.size, 0);
    server.UpdateAsync([payload()], invocation(':1.30'));
    [...watches.values()][0](); // Client disconnected.
    assert.equal(server._session.state, null);
    assert.equal(timers.size, 0);
    server.UpdateAsync([payload()], invocation(':1.30'));
    now = 4000;
    const [timerId, callback] = [...timers][0];
    timers.delete(timerId);
    assert.equal(callback(), false); // Client hung, lease expired.
    assert.equal(server._session.state, null);
    assert.equal(attached.size, 0);
    server.disable(); server.disable();
    console.log('PASS: protocol/Unicode, async gesture boundary, effects, monitor switch, lease/disconnect/release, cleanup.');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
