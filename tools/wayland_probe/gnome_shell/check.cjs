const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/extension.js`, 'utf8')
    .replace(/^import .*;\n/gm, '')
    .replace('export default class', 'this.Probe = class');

function setup(failAt = 0) {
    const timers = new Map();
    const actors = [];
    const attached = [];
    let sequence = 0;
    let added = 0;
    const focus = {get_wm_class: () => 'okular'};
    const schedule = (priority, delay, callback) => {
        timers.set(++sequence, {delay, callback});
        return sequence;
    };
    const context = {
        console: {log() {}, error() {}}, Extension: class {},
        GLib: {
            PRIORITY_DEFAULT: 0, SOURCE_REMOVE: false, SOURCE_CONTINUE: true,
            timeout_add: schedule, timeout_add_seconds: schedule,
            Source: {remove: id => assert(timers.delete(id))},
        },
        St: {Widget: class {
            constructor(props) { Object.assign(this, props); actors.push(this); }
            set_position(x, y) { this.position = [x, y]; }
            destroy() { this.destroyed = true; }
        }},
        global: {display: {focus_window: focus}, get_pointer: () => [700, 800]},
        Main: {
            uiGroup: {get_children: () => attached},
            layoutManager: {
                monitors: [{index: 0, x: 0, y: 552, width: 1600, height: 900},
                    {index: 1, x: 1600, y: 0, width: 1920, height: 1080}],
                addTopChrome(actor, params) {
                    if (++added === failAt) throw new Error('simulated registration failure');
                    assert.equal(params.affectsInputRegion, false);
                    assert.equal(params.trackFullscreen, false);
                    assert.equal(actor.reactive, false);
                    attached.push(actor);
                },
                removeChrome(actor) {
                    const index = attached.indexOf(actor);
                    if (index >= 0) attached.splice(index, 1);
                },
            },
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    return {probe: new context.Probe(), actors, timers, attached};
}

for (const mode of ['disable', 'timeout', 'startup-failure']) {
    const state = setup(mode === 'startup-failure' ? 2 : 0);
    if (mode === 'startup-failure') {
        assert.throws(() => state.probe.enable(), /simulated/);
    } else {
        state.probe.enable();
        assert.equal(state.actors.length, 3);
        assert.equal(state.timers.size, 2);
        if (mode === 'timeout') {
            const [id, timer] = [...state.timers].find(([, t]) => t.delay === 30);
            state.timers.delete(id);
            assert.equal(timer.callback(), false);
        } else {
            state.probe.disable();
        }
    }
    state.probe.disable(); // Cleanup must also be safe after timeout or partial startup.
    assert.equal(state.timers.size, 0);
    assert.equal(state.attached.length, 0);
    assert(state.actors.every(actor => actor.destroyed));
}
console.log('PASS: disable, timeout, partial startup failure; cleanup is idempotent.');
