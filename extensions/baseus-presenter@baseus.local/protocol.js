// Pure validation and session ownership; also exercised outside the Shell.
export function parseState(payload) {
    if (typeof payload !== 'string' || payload.length > 16384)
        throw new Error('Payload too large or invalid');
    const value = JSON.parse(payload);
    if (!value || value.protocol !== 1 || !['LASER', 'LUPA', 'SPOTLIGHT'].includes(value.mode))
        throw new Error('Unsupported protocol or mode');
    for (const key of ['active', 'pen', 'black']) {
        if (typeof value[key] !== 'boolean')
            throw new Error(`Invalid ${key}`);
    }
    if (!Number.isSafeInteger(value.clear_serial) || value.clear_serial < 0 ||
        !Number.isSafeInteger(value.pen_serial) || value.pen_serial < 0 ||
        typeof value.subtitle !== 'string' || [...value.subtitle].length > 2048)
        throw new Error('Invalid clear serial or subtitle');
    const input = value.visual;
    if (!input || typeof input !== 'object')
        throw new Error('Missing visual configuration');
    const visual = {};
    for (const [key, min, max] of [
        ['laser_size', 10, 100], ['lupa_size', 100, 500],
        ['spotlight_size', 100, 800], ['spotlight_opacity', 0, 255],
    ]) {
        if (!Number.isFinite(input[key]))
            throw new Error(`Invalid ${key}`);
        visual[key] = Math.min(max, Math.max(min, input[key]));
    }
    for (const key of ['laser_color', 'pincel_color']) {
        if (typeof input[key] !== 'string' || !/^#[0-9a-f]{6}$/i.test(input[key]))
            throw new Error(`Invalid ${key}`);
        visual[key] = input[key];
    }
    if (!['circular', 'square'].includes(input.lupa_shape))
        throw new Error('Invalid magnifier shape');
    visual.lupa_shape = input.lupa_shape;
    return {protocol: 1, active: value.active, mode: value.mode, pen: value.pen,
        black: value.black, clear_serial: value.clear_serial, pen_serial: value.pen_serial,
        subtitle: value.subtitle, visual};
}

export class Session {
    constructor() {
        this.owner = null;
        this.deadline = 0;
        this.state = null;
    }

    update(sender, payload, now) {
        const state = parseState(payload);
        if (this.owner && this.owner !== sender && now < this.deadline)
            throw new Error('Another client owns the overlay');
        const changedOwner = this.owner !== sender || now >= this.deadline;
        this.owner = sender;
        this.deadline = now + 4000;
        this.state = state;
        return changedOwner;
    }

    release(sender) {
        if (sender !== this.owner)
            return false;
        this.owner = null;
        this.state = null;
        this.deadline = 0;
        return true;
    }

    expire(now) {
        return this.owner !== null && now >= this.deadline && this.release(this.owner);
    }
}
