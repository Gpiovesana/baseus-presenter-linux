// Execute the production renderer without a running GNOME Shell. The tracker
// uses real GObject signals, including synchronous/reentrant visibility changes.
const {GLib, GObject} = imports.gi;
const ByteArray = imports.byteArray;
function assert(condition, message) {
    if (!condition)
        throw new Error(message);
}
function load(relative) {
    const [, bytes] = GLib.file_get_contents(`${ARGV[0]}/${relative}`);
    return ByteArray.toString(bytes).replace(/^import .*;\n/gm, '');
}
// In Mutter 46, showing the pointer owns one unfocus inhibition; hiding it
// releases that reference. An overlay must retain its own while hidden.
const seat = {
    count: 1,
    inhibit_unfocus() { this.count++; },
    uninhibit_unfocus() {
        assert(this.count > 0, 'unbalanced unfocus release');
        this.count--;
    },
};
const Clutter = {get_default_backend: () => ({get_default_seat: () => seat})};
const Tracker = GObject.registerClass({
    Signals: {'visibility-changed': {}},
}, class Tracker extends GObject.Object {
    _init() {
        super._init();
        this.visible = true;
        this.writes = 0;
    }
    get_pointer_visible() { return this.visible; }
    set_pointer_visible(visible) {
        this.writes++;
        assert(this.writes < 100, 'visibility callback recursed indefinitely');
        if (this.visible === visible)
            return;
        this.visible = visible;
        if (visible)
            seat.inhibit_unfocus();
        else
            seat.uninhibit_unfocus();
        this.emit('visibility-changed');
    }
});
let compositionHolds = 0;
const Meta = {
    disable_unredirect_for_display() { compositionHolds++; },
    enable_unredirect_for_display() {
        assert(compositionHolds > 0, 'unbalanced composition release');
        compositionHolds--;
    },
};
const tracker = new Tracker();
const global = {backend: {get_cursor_tracker: () => tracker},
    get_pointer: () => [10, 10]};
const monitor = {x: 0, y: 0, width: 100, height: 100};
const Main = {layoutManager: {monitors: [monitor]}};
const Extension = class {};
const Renderer = eval(load('extensions/baseus-presenter@baseus.local/renderer.js')
    .replace('export class Renderer', 'class Renderer') + '\nRenderer;');
const BaseusPresenter = eval(load('extensions/baseus-presenter@baseus.local/extension.js')
    .replace('export default class BaseusPresenter', 'class BaseusPresenter') + '\nBaseusPresenter;');

const renderer = new Renderer();
renderer._setCursorHidden(true);
assert(!tracker.visible, 'initial hide failed');
assert(seat.count === 1, 'hiding cursor allowed pointer focus to be unset');
tracker.set_pointer_visible(true); // Mutter may show it again after pointer input.
assert(!tracker.visible, 'native cursor reappeared while effect was active');
const writes = tracker.writes;
renderer._setCursorHidden(true);
assert(tracker.writes === writes, 'repeated hide must be idempotent');
assert(seat.count === 1, 'repeated hide leaked unfocus inhibition');
renderer._setCursorHidden(false);
assert(tracker.visible, 'effect deactivation did not restore cursor');
assert(seat.count === 1, 'effect deactivation leaked unfocus inhibition');
const restoredWrites = tracker.writes;
tracker.emit('visibility-changed');
assert(tracker.writes === restoredWrites, 'visibility handler leaked after release');

for (let cycle = 0; cycle < 3; cycle++) {
    renderer._setCursorHidden(true);
    renderer.reset();
    renderer.reset();
    assert(tracker.visible, 'reset did not restore cursor');
    assert(seat.count === 1, 'reset leaked unfocus inhibition');
    const afterReset = tracker.writes;
    tracker.emit('visibility-changed');
    assert(tracker.writes === afterReset, 'reset leaked a visibility handler');
}

// Exercise real render decisions with inert tool actors (no compositor needed).
const actor = () => ({hide() {}, show() {}, set_position() {}});
const visual = {laser_size: 10, lupa_size: 20};
const state = {active: false, black: false, pen: false, subtitle: '',
    pen_serial: 0, clear_serial: 0, visual};
for (const effect of ['LASER', 'LUPA', 'SPOTLIGHT', 'BLACK']) {
    renderer._tools = {root: actor(), lensRoot: actor(), lens: actor(),
        lensBorder: actor(), clone: actor(), laser: actor(), shade: actor(),
        subtitle: {...actor(), text: ''}, black: actor(), monitor,
        key: JSON.stringify(visual)};
    renderer._positionShade = () => {};
    renderer.render({...state, mode: effect, active: effect !== 'BLACK',
        black: effect === 'BLACK'});
    assert(!tracker.visible, `${effect} did not hide cursor`);
    assert(compositionHolds === 1, `${effect} did not require composition`);
    assert(seat.count === 1, `${effect} lost pointer focus protection`);
    tracker.set_pointer_visible(true);
    assert(!tracker.visible, `${effect} allowed cursor to reappear`);
    renderer.render(state);
    assert(tracker.visible, `${effect} deactivation did not restore cursor`);
    assert(compositionHolds === 0, `${effect} leaked composition inhibition`);
    assert(seat.count === 1, `${effect} leaked unfocus inhibition`);
}
renderer.render({...state, active: true, mode: 'LASER'});
renderer.render({...state, active: true, mode: 'SPOTLIGHT'});
assert(compositionHolds === 1, 'effect switch leaked composition hold');
renderer._strokes = [{actor: {visible: true}, hex: undefined}];
renderer.render(state);
assert(compositionHolds === 1, 'retained pen drawing lost composition');
renderer._strokes = [];
renderer.render(state);
assert(compositionHolds === 0, 'cleared drawing retained composition');
renderer._setCursorHidden(true);
Main.layoutManager.monitors = [];
renderer.render(state);
assert(tracker.visible, 'missing monitor did not restore cursor');
assert(compositionHolds === 0, 'missing monitor leaked composition');
assert(seat.count === 1, 'missing monitor leaked unfocus inhibition');

renderer._setCursorHidden(true);
const extension = new BaseusPresenter();
extension._renderer = renderer;
renderer._setCompositionRequired(true);
extension.disable();
extension.disable();
assert(tracker.visible, 'extension disable did not restore cursor');
assert(compositionHolds === 0, 'disable leaked composition');
assert(seat.count === 1, 'extension disable leaked unfocus inhibition');
const afterDisable = tracker.writes;
tracker.emit('visibility-changed');
assert(tracker.writes === afterDisable, 'extension disable leaked a visibility handler');

// Exercise the actual extension release and lease-expiry paths with active tools.
Main.layoutManager.monitors = [monitor];
const lifecycle = new BaseusPresenter();
lifecycle._renderer = new Renderer();
lifecycle._session = {owner: ':test', release: () => true, expire: () => true};
lifecycle._renderer._setCursorHidden(true);
lifecycle._renderer._setCompositionRequired(true);
lifecycle.ReleaseAsync([], {get_sender: () => ':test', return_value() {}});
assert(tracker.visible && compositionHolds === 0, 'Release did not restore cursor/compositor');
lifecycle._renderer._setCursorHidden(true);
lifecycle._renderer._setCompositionRequired(true);
lifecycle._startTimer();
const loop = new GLib.MainLoop(null, false);
GLib.timeout_add(GLib.PRIORITY_DEFAULT, 60, () => {
    loop.quit();
    return GLib.SOURCE_REMOVE;
});
loop.run();
assert(tracker.visible && compositionHolds === 0, 'lease expiry did not restore cursor/compositor');
assert(lifecycle._timer === 0, 'lease expiry left render timer running');
lifecycle.disable();
print('PASS: cursor visibility, effect transitions, reset, missing monitor, disable');
