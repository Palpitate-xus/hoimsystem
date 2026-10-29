const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function streamHarness(fetch) {
  const events = [], requests = [], timers = new Map();
  const source = fs.readFileSync(path.join(__dirname, '../src/utils/clinicalEvents.js'), 'utf8').replace(/^import[^\n]+\n/gm, '').replace('export const clinicalEventStream', 'const clinicalEventStream');
  const context = vm.createContext({ module: { exports: {} }, baseURL: '/api', tokenName: 'accesstoken', AbortController, TextDecoder, console, ElNotification() {}, eventBus: { emit: (name, payload) => events.push({ name, payload }) }, fetch: (...args) => { requests.push(args); return fetch(...args); }, setTimeout: (fn, delay) => { const id = timers.size + 1; timers.set(id, { fn, delay }); return id; }, clearTimeout: id => timers.delete(id) });
  new vm.Script(source + '\nmodule.exports = clinicalEventStream;').runInContext(context);
  return { stream: context.module.exports, events, requests, timers };
}
for (const status of [401, 403]) {
  test(`actual stream stops on ${status}, notifies the snapshot refresh once and schedules no reconnect`, async () => {
    const h = streamHarness(async () => ({ status }));
    h.stream.start('synthetic-current-token'); await tick();
    assert.equal(h.requests.length, 1); assert.equal(h.stream.token, ''); assert.equal(h.timers.size, 0);
    assert.equal(h.requests[0][1].signal.aborted, true);
    assert.deepEqual(JSON.parse(JSON.stringify(h.events)), [{ name: 'access-denied', payload: { token: 'synthetic-current-token', status, source: 'clinical-event-stream' } }]);
    await tick(); assert.equal(h.requests.length, 1);
  });
}
test('a late forbidden response from a replaced token cannot stop or notify the new stream', async () => {
  const old = deferred(), current = deferred(); let count = 0;
  const h = streamHarness(() => ++count === 1 ? old.promise : current.promise);
  h.stream.start('old-token'); h.stream.start('new-token');
  old.resolve({ status: 403 }); await tick();
  assert.equal(h.stream.token, 'new-token'); assert.deepEqual(h.events, []);
  assert.equal(h.requests[1][1].signal.aborted, false);
  current.resolve({ status: 403 }); await tick();
  assert.equal(h.events.length, 1); assert.equal(h.events[0].payload.token, 'new-token'); assert.equal(h.timers.size, 0);
});
test('manual stop suppresses a delayed access-denied notification', async () => {
  const pending = deferred(), h = streamHarness(() => pending.promise);
  h.stream.start('old-token'); h.stream.stop(); pending.resolve({ status: 403 }); await tick();
  assert.deepEqual(h.events, []); assert.equal(h.timers.size, 0);
});
test('transient transport failure retains the existing bounded reconnect delay', async () => {
  const h = streamHarness(async () => ({ status: 503, ok: false })); h.stream.start('current-token'); await tick();
  assert.equal(h.events.length, 0); assert.equal(h.timers.size, 1); const { delay } = [...h.timers.values()][0]; assert.ok(delay >= 1000 && delay < 1500); h.stream.stop(); assert.equal(h.timers.size, 0);
});
