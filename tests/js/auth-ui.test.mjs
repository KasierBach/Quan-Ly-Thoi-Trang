import test from 'node:test';
import assert from 'node:assert/strict';

import { initAsideSlideshow, initConfirmMatch, initEyeToggles, initPasswordPattern, initSubmitFeedback } from '../../app/static/js/auth/auth_ui.js';

class FakeElement {
    constructor(tag, attributes = {}) {
        this.tagName = tag.toUpperCase();
        this.attributes = new Map(Object.entries(attributes));
        this.classes = new Set();
        this.dataset = {};
        this.style = {};
        this.value = '';
        this.type = '';
        this.disabled = false;
        this.textContent = '';
        this.focusCalls = 0;
        this.parentElement = null;
        this.children = [];
        this.listeners = new Map();
        this.customMessage = '';
        const self = this;
        this.classList = {
            add: (...names) => names.forEach((name) => self.classes.add(name)),
            remove: (...names) => names.forEach((name) => self.classes.delete(name)),
            contains: (name) => self.classes.has(name),
            toggle: (name, force) => {
                const enable = force === undefined ? !self.classes.has(name) : Boolean(force);
                if (enable) self.classes.add(name); else self.classes.delete(name);
                return enable;
            },
        };
    }

    getAttribute(name) { return this.attributes.get(name) ?? null; }

    setAttribute(name, value) { this.attributes.set(name, String(value)); }

    removeAttribute(name) { this.attributes.delete(name); }

    focus() { this.focusCalls += 1; }

    setCustomValidity(message) {
        this.customMessage = message;
        this.validity = { customError: Boolean(message) };
    }

    *descendants() {
        for (const child of this.children) {
            yield child;
            yield* child.descendants();
        }
    }

    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }

    querySelectorAll(selector) {
        return [...this.descendants()].filter((el) => matchesSelector(el, selector));
    }

    closest(selector) {
        let node = this.parentElement;
        while (node) {
            if (matchesSelector(node, selector)) return node;
            node = node.parentElement;
        }
        return null;
    }

    addEventListener(type, listener) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(listener);
    }

    dispatch(type) {
        const event = {
            defaultPrevented: false,
            preventDefault() { this.defaultPrevented = true; },
        };
        for (const listener of [...(this.listeners.get(type) ?? [])]) listener(event);
        return event;
    }
}

function matchesSelector(el, selector) {
    const attrMatch = selector.match(/\[([^\]=]+)(?:="([^"]*)")?\]/);
    const rest = selector.replace(/\[[^\]]*\]/g, '');
    if (rest) {
        if (rest.startsWith('#')) {
            if (el.attributes.get('id') !== rest.slice(1)) return false;
        } else if (rest.startsWith('.')) {
            if (!el.classes.has(rest.slice(1))) return false;
        } else if (el.tagName !== rest.toUpperCase()) {
            return false;
        }
    }
    if (attrMatch) {
        const [, attr, expected] = attrMatch;
        const value = el.attributes.get(attr) ?? (attr === 'type' ? el.type.toLowerCase() : undefined);
        if (expected === undefined ? value === undefined : value !== expected) return false;
    }
    return true;
}

function buildEyeFixture() {
    const shell = new FakeElement('div', { id: 'auth-shell', class: 'auth-shell' });
    const input = new FakeElement('input', { id: 'password', name: 'password' });
    input.type = 'password';
    const eyeIcon = new FakeElement('i', { 'data-eye-icon': '' });
    eyeIcon.classes.add('fas', 'fa-eye');
    const eyeButton = new FakeElement('button', {
        type: 'button', 'data-eye': '', 'aria-pressed': 'false', 'aria-label': 'Hiện mật khẩu',
    });
    eyeButton.children.push(eyeIcon);
    eyeIcon.parentElement = eyeButton;
    const group = new FakeElement('div', { class: 'input-group' });
    group.children.push(input, eyeButton);
    input.parentElement = group;
    eyeButton.parentElement = group;
    shell.children.push(group);
    return { shell, input, eyeButton, eyeIcon };
}

test('eye toggle flips visibility, icon, aria state and back', () => {
    const { shell, input, eyeButton, eyeIcon } = buildEyeFixture();

    initEyeToggles(shell);
    eyeButton.dispatch('click');
    assert.equal(input.type, 'text');
    assert.equal(eyeButton.getAttribute('aria-pressed'), 'true');
    assert.equal(eyeButton.getAttribute('aria-label'), 'Ẩn mật khẩu');
    assert.ok(eyeIcon.classes.has('fa-eye-slash') && !eyeIcon.classes.has('fa-eye'));

    eyeButton.dispatch('click');
    assert.equal(input.type, 'password');
    assert.equal(eyeButton.getAttribute('aria-pressed'), 'false');
    assert.equal(eyeButton.getAttribute('aria-label'), 'Hiện mật khẩu');
    assert.ok(eyeIcon.classes.has('fa-eye') && !eyeIcon.classes.has('fa-eye-slash'));
});

function buildMatchFixture() {
    const shell = new FakeElement('div');
    const password = new FakeElement('input', { id: 'password', name: 'password' });
    const confirm = new FakeElement('input', { id: 'confirm_password', name: 'confirm_password' });
    const hint = new FakeElement('div', { 'data-confirm-hint': '' });
    shell.children.push(password, confirm, hint);
    initConfirmMatch(shell);
    return { password, confirm, hint };
}

test('confirm mismatch sets customError and error hint until it matches', () => {
    const { password, confirm, hint } = buildMatchFixture();

    confirm.value = 'TestPass123';
    confirm.dispatch('input');
    assert.equal(hint.dataset.state, 'err');
    assert.equal(hint.textContent, 'Mật khẩu xác nhận chưa khớp.');
    assert.equal(confirm.customMessage, 'Mật khẩu không khớp');
    assert.equal(confirm.validity.customError, true);

    confirm.value = 'TestPass999';
    confirm.dispatch('input');
    assert.equal(hint.dataset.state, 'err');

    password.value = 'TestPass999';
    password.dispatch('input');
    assert.equal(hint.dataset.state, 'ok');
    assert.equal(hint.textContent, 'Mật khẩu khớp.');
    assert.equal(confirm.customMessage, '');
    assert.equal(confirm.validity.customError, false);
    assert.ok(confirm.classes.has('is-ok'));
});

test('empty confirmation clears hint and custom error', () => {
    const { confirm, hint } = buildMatchFixture();

    confirm.value = 'Temp123';
    confirm.dispatch('input');
    confirm.value = '';
    confirm.dispatch('input');
    assert.equal(hint.dataset.state, '');
    assert.equal(hint.textContent, '');
    assert.equal(confirm.validity.customError, false);
});

function buildSubmitFixture() {
    const shell = new FakeElement('div');
    const icon = new FakeElement('i', { 'data-btn-icon': 'fa-sign-in-alt' });
    icon.classes.add('fas', 'fa-sign-in-alt');
    const button = new FakeElement('button', { type: 'submit' });
    button.children.push(icon);
    icon.parentElement = button;
    const form = new FakeElement('form', { 'data-auth-loading': '' });
    form.children.push(button);
    shell.children.push(form);
    return { shell, form, button, icon };
}

test('submit feedback disables the button, swaps the icon, and restores on pageshow', () => {
    const { shell, form, button, icon } = buildSubmitFixture();

    const events = new Map();
    const fakeWindow = { addEventListener: (type, listener) => events.set(type, listener) };
    initSubmitFeedback(shell, fakeWindow);

    form.dispatch('submit');
    assert.equal(button.disabled, true);
    assert.ok(icon.classes.has('fa-spinner') && icon.classes.has('fa-spin-pulse'));
    assert.ok(!icon.classes.has('fa-sign-in-alt'));

    events.get('pageshow')({});
    assert.equal(button.disabled, false);
    assert.ok(icon.classes.has('fa-sign-in-alt'));
    assert.ok(!icon.classes.has('fa-spinner') && !icon.classes.has('fa-spin-pulse'));
});

test('submit feedback ignores repeated submits while disabled', () => {
    const { shell, form, button, icon } = buildSubmitFixture();

    initSubmitFeedback(shell, { addEventListener: () => {} });
    form.dispatch('submit');
    form.dispatch('submit');
    assert.equal(button.disabled, true);
    assert.equal(icon.classes.size, 3); // fas + fa-spinner + fa-spin-pulse, original removed once
});

test('weak reset password leaves submit enabled so a corrected password can be sent', () => {
    const shell = new FakeElement('div');
    const icon = new FakeElement('i', { 'data-btn-icon': 'fa-key' });
    icon.classList.add('fas', 'fa-key');
    const button = new FakeElement('button', { type: 'submit' });
    button.children.push(icon);
    const password = new FakeElement('input', {
        id: 'password', name: 'password', 'data-new-password': '',
    });
    password.type = 'password';
    const hint = new FakeElement('div', { 'data-pattern-hint': '' });
    const form = new FakeElement('form', { 'data-auth-loading': '' });
    form.children.push(password, hint, button);
    password.parentElement = form;
    hint.parentElement = form;
    button.parentElement = form;
    shell.children.push(form);

    initPasswordPattern(shell);
    initSubmitFeedback(shell, { addEventListener: () => {} });

    password.value = 'weak';
    password.dispatch('input');
    assert.equal(hint.dataset.state, 'err');
    assert.equal(hint.textContent, 'Mật khẩu chưa đạt yêu cầu.');

    password.value = 'StrongPass1';
    password.dispatch('input');
    assert.equal(hint.dataset.state, 'ok');
    assert.equal(hint.textContent, 'Mật khẩu đạt yêu cầu.');

    // Weak value again, then a submit attempt is prevented and refocused.
    password.value = 'weakpass';
    password.dispatch('input');
    assert.equal(form.dispatch('submit').defaultPrevented, true);
    assert.equal(hint.dataset.state, 'err');
    assert.equal(password.focusCalls, 1);
    assert.equal(password.getAttribute('aria-invalid'), 'true');
    assert.equal(button.disabled, false);
    assert.ok(icon.classes.has('fa-key') && !icon.classes.has('fa-spinner'));

    password.value = 'Aa٠' + '👗'.repeat(126);
    password.dispatch('input');
    assert.equal(form.dispatch('submit').defaultPrevented, true);

    password.value = 'Aa٠' + '👗'.repeat(125);
    password.dispatch('input');
    assert.equal(password.getAttribute('aria-invalid'), null);
    assert.equal(form.dispatch('submit').defaultPrevented, false);
    assert.equal(button.disabled, true);
    assert.ok(icon.classes.has('fa-spinner'));
});

function slideshowFixture(matches = true) {
    const slides = Array.from({ length: 4 }, () => new FakeElement('span', { 'data-aside-slide': '' }));
    slides[0].classList.add('is-active');
    slides.slice(1).forEach((slide, index) => { slide.dataset.asideSrc = `/static/photo-${index + 2}.jpg`; });
    const loads = [];
    let interval;
    const media = { matches };
    const scheduler = {
        matchMedia: (query) => {
            assert.equal(query, '(min-width: 768px) and (prefers-reduced-motion: no-preference)');
            return media;
        },
        setInterval: (fn) => { interval = fn; return 7; },
        Image: class {
            async decode() { loads.push(this.src); }
        },
    };
    const scope = { querySelectorAll: () => slides, hidden: false };
    const handle = initAsideSlideshow(scope, scheduler);
    return { slides, handle, loads, media, scope, tick: () => interval() };
}

test('none of the other brand photos loads until its turn', async () => {
    const { slides, handle, loads, tick } = slideshowFixture();
    assert.equal(handle, 7);
    assert.ok(slides[0].classes.has('is-active'));
    assert.deepEqual(loads, []);

    await tick();
    assert.ok(!slides[0].classes.has('is-active') && slides[1].classes.has('is-active'));
    assert.deepEqual(loads, ['/static/photo-2.jpg']);

    await tick();
    await tick();
    assert.ok(slides[3].classes.has('is-active'));
    assert.equal(loads.length, 3);
    await tick();
    await tick();
    assert.ok(slides[1].classes.has('is-active'));
    assert.equal(loads.length, 3, 'rotate through the previously decoded background');
});

test('brand rotation skips mobile, reduced motion, and hidden pages', async () => {
    const staticView = slideshowFixture(false);
    assert.equal(staticView.handle, null);
    assert.ok(staticView.slides[0].classes.has('is-active'));
    assert.deepEqual(staticView.loads, []);

    const desktop = slideshowFixture();
    desktop.scope.hidden = true;
    await desktop.tick();
    desktop.scope.hidden = false;
    desktop.media.matches = false;
    await desktop.tick();
    assert.deepEqual(desktop.loads, []);
    assert.ok(desktop.slides[0].classes.has('is-active'));
});
