// Regression: the Submit button is one element shared by every exam in a page session.
// After a successful submit it used to stay disabled ("Submitting…"), so every later exam in the
// same session could not be submitted: the click did nothing and sent no request.
//
// Runs the real app/static/app.js against a minimal stubbed page:  node --test tests/frontend
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
// APP_JS lets a reviewer point the test at another copy (e.g. the pre-fix file) to see it fail.
const source = readFileSync(process.env.APP_JS || path.join(here, '../../app/static/app.js'), 'utf8');
process.on('unhandledRejection', () => {});

function makeElement(id) {
  const store = {
    id, dataset: {}, style: {}, children: [], textContent: '', innerHTML: '', hidden: false, disabled: false, value: '',
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    querySelectorAll: () => [], querySelector: () => makeElement('q'), closest: () => null,
    addEventListener() {}, removeEventListener() {}, focus() {}, setAttribute() {}, removeAttribute() {},
    appendChild() {}, append() {}, remove() {}, insertAdjacentHTML() {}, scrollIntoView() {},
  };
  return new Proxy(store, { get: (t, p) => (p in t ? t[p] : (typeof p === 'symbol' ? undefined : () => undefined)), set: (t, p, v) => { t[p] = v; return true; } });
}

function boot(routes) {
  const elements = new Map();
  const calls = [];
  const element = id => { if (!elements.has(id)) elements.set(id, makeElement(id)); return elements.get(id); };
  const storage = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }; };
  const document = { getElementById: element, querySelector: () => makeElement('q'), querySelectorAll: () => [], addEventListener() {}, body: makeElement('body'), documentElement: makeElement('html'), createElement: () => makeElement('c'), hidden: false };
  const window = { addEventListener() {}, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }), location: { hash: '', href: 'http://t/', origin: 'http://t', pathname: '/' }, history: { replaceState() {}, pushState() {} }, open() {} };
  const fetch = async (url, options = {}) => {
    const method = options.method || 'GET';
    calls.push(`${method} ${url}`);
    const handler = routes(method, String(url).replace(/^\/api/, ''));
    const status = handler?.status ?? 200;
    return { ok: status < 400, status, json: async () => handler?.body ?? {} };
  };
  const context = vm.createContext({
    document, window, location: window.location, history: window.history, fetch, console, localStorage: storage(), sessionStorage: storage(), navigator: { onLine: true, userAgent: 'node' },
    crypto: { randomUUID: () => `uuid-${Math.random().toString(16).slice(2)}` },
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {}, requestAnimationFrame: () => 0,
    URL, URLSearchParams, FormData: class {}, Intl, Date, Math, JSON, Map, Set, Promise, Object, Array, Number, String, Error, Symbol,
    IntersectionObserver: class { observe() {} disconnect() {} }, ResizeObserver: class { observe() {} disconnect() {} },
    Notification: undefined, performance: { now: () => 0 }, confirm: () => true,
  });
  window.document = document; context.window = window; context.self = window;
  vm.runInContext(source, context, { filename: 'app.js' });
  return { context, calls, element };
}

const exam = id => ({
  attempt_id: 100 + id, title: `Exam ${id}`, release_label: 'x', deadline_at: new Date(Date.now() + 3_600_000).toISOString(),
  questions: [{ id: 1, position: 1, stem: 'q', type: 'multiple_choice', options: ['a', 'b'], saved_answer: null }],
  accommodation_applied: false, time_multiplier: 1, restored_response_count: 0,
});

test('Submit works for a second exam in the same page session', async () => {
  const routes = (method, url) => {
    let m;
    if ((m = url.match(/^\/exams\/(\d+)\/start$/))) return { body: exam(Number(m[1])) };
    if (/\/responses$/.test(url)) return { body: { saved: true, duplicate: false } };
    if (/\/submit$/.test(url)) return { body: { id: 1, status: 'remediation_open', score: 1, max_score: 1 } };
    if (/\/review$/.test(url)) return { body: { challengeable_items: [], remediation_cases: [] } };
    if (/\/answers$/.test(url)) return { body: { items: [] } };
    return { body: {} };
  };
  const { context, calls, element } = boot(routes);
  const run = code => vm.runInContext(code, context);
  run("state.user = { id: 7 }; state.token = 't'; state.authConfig = { provider: 'local' };");

  for (const examId of [1, 2]) {
    await run(`startExam(${examId})`);
    assert.equal(run('state.attempt'), 100 + examId, `exam ${examId} started`);
    run("state.answers[1] = 0; state.sequences[1] = 0;");
    const before = calls.filter(c => /\/submit$/.test(c)).length;
    await run('submitExam()');
    const submits = calls.filter(c => /\/submit$/.test(c)).length - before;
    assert.equal(submits, 1, `exam ${examId}: clicking Submit sent exactly one submit request`);
    assert.equal(element('submit-exam').disabled, false, `exam ${examId}: Submit button is usable again`);
  }
});
