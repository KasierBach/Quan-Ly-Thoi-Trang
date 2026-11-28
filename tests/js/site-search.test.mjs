import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const script = readFileSync(new URL('../../app/static/js/site.js', import.meta.url), 'utf8');

function element() {
    const listeners = new Map();
    const attributes = new Map();
    const classes = new Set();
    const children = [];
    return {
        style: {}, children, attributes, classes,
        classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) },
        addEventListener: (type, listener) => listeners.set(type, listener),
        fire: (type, event) => listeners.get(type)(event),
        setAttribute: (name, value) => attributes.set(name, value),
        append: (...nodes) => children.push(...nodes),
        replaceChildren: () => children.splice(0),
    };
}

function searchFixture() {
    const input = element();
    const results = element();
    const elements = {
        'base-data': { textContent: JSON.stringify({ isLoggedIn: true, searchUrl: '/api/search_autocomplete' }) },
        searchInput: input, searchAutocomplete: results, darkIcon: element(), lightIcon: element(),
    };
    const document = Object.assign(element(), {
        documentElement: { dataset: {} },
        getElementById: (id) => elements[id] || null,
        querySelector: () => null,
        createElement: element,
    });
    const timers = new Map();
    const requests = [];
    runInNewContext(script, {
        document, AbortController, URL, URLSearchParams,
        location: { origin: 'https://store.example.test' },
        setTimeout(callback, delay) { timers.set(delay, callback); return delay; },
        clearTimeout: (id) => timers.delete(id),
        fetch: (_, { signal }) => new Promise((resolve) => requests.push({ signal, resolve })),
    });
    return {
        results, requests,
        type: (value) => { input.value = value; input.fire('input'); },
        escape() {
            let prevented = false;
            input.fire('keydown', { key: 'Escape', preventDefault: () => { prevented = true; } });
            return prevented;
        },
        clickOutside: () => document.fire('click', { target: { closest: () => null } }),
        runDebounce() {
            const callback = timers.get(250);
            timers.delete(250);
            return callback?.();
        },
        expanded: () => input.attributes.get('aria-expanded'),
    };
}

function reply(request, ok = true) {
    request.resolve({ ok, json: async () => ({ success: ok, products: [{ id: 7, name: 'Áo', price: '200000' }] }) });
}

test('Escape cancels debounce and an outside click discards a pending response', async () => {
    const search = searchFixture();
    search.type('áo');
    assert.equal(search.escape(), true);
    assert.equal(search.runDebounce(), undefined);
    assert.equal(search.requests.length, 0);

    search.type('áo');
    const response = search.runDebounce();
    search.clickOutside();
    assert.equal(search.requests[0].signal.aborted, true);
    reply(search.requests[0]); // The response may already be queued when abort runs.
    await response;
    assert.equal(search.expanded(), 'false');
    assert.equal(search.results.children.length, 0);
});

test('a new term removes old links immediately, including if the new request fails', async () => {
    const search = searchFixture();
    search.type('áo');
    const successful = search.runDebounce();
    reply(search.requests[0]);
    await successful;
    assert.equal(search.expanded(), 'true');
    assert.equal(search.results.children[0].href, '/product/7');

    search.type('quần');
    assert.equal(search.expanded(), 'false');
    assert.equal(search.results.children.length, 0);
    const failed = search.runDebounce();
    reply(search.requests[1], false);
    await failed;
    assert.equal(search.expanded(), 'false');
    assert.equal(search.results.children.length, 0);
});
