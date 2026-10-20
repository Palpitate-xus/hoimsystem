const test = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { parse: parseJavaScript } = require("@babel/parser");
const { parse: parseSfc } = require("@vue/compiler-sfc");
const Vue = require("vue");

// These are state/contract regressions, not browser or HTTP tests. They execute
// the actual SFC script with real Vue reactivity and deferred synthetic API
// replies. Only imports, setup macros and lifecycle registration are injected;
// product conditionals, handlers, watchers and scope predicates remain intact.
const root = join(__dirname, "..");
const read = path => readFileSync(join(root, path), "utf8");
function injectable(source, exports = []) {
  const ast = parseJavaScript(source, { sourceType: "module" });
  const removals = ast.program.body.flatMap(node => node.type === "ImportDeclaration" ? [[node.start, node.end]] : node.type === "ExportNamedDeclaration" ? [[node.start, node.declaration.start]] : []);
  for (const [start, end] of removals.sort((left, right) => right[0] - left[0])) source = source.slice(0, start) + source.slice(end);
  return source + `\nreturn { ${exports.join(", ")} };`;
}
function evaluate(source, dependencies, exports) {
  return new Function(...Object.keys(dependencies), injectable(source, exports))(...Object.values(dependencies));
}
const noTransport = () => { throw new Error("This Node regression must not make HTTP requests"); };
const labApi = evaluate(read("src/api/inpatientLaboratory.js"), { request: noTransport }, ["labSourceMatches"]);
const windowApi = evaluate(read("src/api/inpatientObservations.js"), { request: noTransport, labSourceMatches: labApi.labSourceMatches }, ["observationWindowMatches"]);
const parsed = parseSfc(read("src/components/AIObservationWindowInput/index.vue"));
assert.deepEqual(parsed.errors, []);
assert.ok(parsed.descriptor.scriptSetup);
const script = parsed.descriptor.scriptSetup.content;
const admission = "d1000000-0000-4000-8000-000000000001";
const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const clone = value => structuredClone(value);

function windowResponse(id = firstId, schema = "inpatient_window_v2") {
  const contentHash = (id === firstId ? "a" : "b").repeat(64);
  const sourceId = `observation_window:${id}:${contentHash.slice(0, 12)}`;
  const frozen = {
    schema_version: schema, window_id: id, patient_id: 1, admission_id: admission,
    start_at: "2026-10-20T00:00:00.123456Z", end_at: "2026-10-20T01:00:00.123456Z", as_of: "2026-10-20T02:00:00.123456Z",
    source_id: sourceId, content_hash: contentHash, points: [], urine_intervals: [],
  };
  if (schema === "inpatient_window_v2") {
    const source = {
      lab_source_id: "33333333-3333-4333-8333-333333333333", patient_id: 1, admission_id: admission,
      observation_id: "synthetic-original-observation", mapping_id: "44444444-4444-4444-8444-444444444444", schema_version: "inpatient_lab_source_v1",
      raw_original_hash: "c".repeat(64), mapping_content_hash: "d".repeat(64),
      collected_at_utc: frozen.start_at, registered_at: frozen.as_of, available_at: frozen.as_of,
      window_projection: "risk_lab_projection_v1",
    };
    source.snapshot = {
      ...source,
      original: {
        observation: { observation_id: source.observation_id, lab_result_id: "synthetic-report", value_num: "0", value_text: null, unit: "umol/L" },
        report: { lab_result_id: "synthetic-report", lab_order_id: "synthetic-order" },
        order: { lab_order_id: "synthetic-order", patient_id: 1 },
      },
      mapping: { mapping_id: source.mapping_id },
    };
    frozen.lab_observations = [source];
  }
  return { ...frozen, snapshot: frozen, status: "active", revision: 1, freshness: { state: "current" } };
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
async function flush() {
  await Vue.nextTick();
  await new Promise(resolve => setImmediate(resolve));
  await Vue.nextTick();
}
function harness(t, initialWindowId = firstId) {
  const props = Vue.reactive({ patientId: 1, admissionId: admission, initialWindowId, disabled: false });
  const store = Vue.reactive({ getters: { "user/permissions": ["doctor"] }, state: { user: { accessToken: "synthetic-node-session" } } });
  const calls = { lists: [], details: [] }, events = [], hooks = { activate: [], deactivate: [], unmount: [] };
  const dependencies = {
    ...Vue, defineProps: () => props, defineEmits: () => (...event) => events.push(event), useStore: () => store,
    onActivated: callback => hooks.activate.push(callback), onDeactivated: callback => hooks.deactivate.push(callback), onBeforeUnmount: callback => hooks.unmount.push(callback),
    getObservationWindows: params => { const pending = deferred(); calls.lists.push({ params: clone(params), ...pending }); return pending.promise; },
    getObservationWindow: (id, params) => { const pending = deferred(); calls.details.push({ id, params: clone(params), ...pending }); return pending.promise; },
    observationWindowMatches: windowApi.observationWindowMatches,
  };
  const scope = Vue.effectScope();
  const state = scope.run(() => evaluate(script, dependencies, ["reload", "sourceChanged", "windowCreated", "selectedId", "current", "loading", "checking", "options", "error", "sourceNotice"]));
  t.after(() => { hooks.unmount.forEach(callback => callback()); scope.stop(); });
  return {
    props, store, state, calls, events, hooks,
    async directory(index, items = [windowResponse()]) { assert.ok(calls.lists[index], "Expected the actual directory request"); calls.lists[index].resolve({ data: clone(items) }); await flush(); },
    async detail(index, response = windowResponse()) { assert.ok(calls.details[index], "Expected the actual detail request"); calls.details[index].resolve({ data: clone(response) }); await flush(); },
  };
}
const readiness = h => h.events.filter(event => event[0] === "availability").map(event => event[1]);
function assertCleared(h) {
  assert.equal(h.state.selectedId.value, "");
  assert.equal(h.state.current.value, null);
  assert.equal(readiness(h).at(-1), false);
}

test("a source change invalidates a held directory before it can restore an initial window", async t => {
  const h = harness(t);
  assert.equal(h.calls.lists.length, 1);
  h.state.sourceChanged();
  await h.directory(0);
  assertCleared(h);
  assert.equal(h.state.loading.value, false);
  assert.deepEqual(h.state.options.value, []);
  assert.equal(h.calls.details.length, 0);
  assert.ok(h.state.sourceNotice.value.includes("重新建立"));
});

test("creating a new window does not automatically reselect the old initial deep link", async t => {
  const h = harness(t);
  await h.directory(0); await h.detail(0);
  assert.equal(h.state.current.value.window_id, firstId);
  h.state.windowCreated();
  await h.directory(1, [windowResponse(), windowResponse(secondId)]);
  assertCleared(h);
  assert.equal(h.calls.details.length, 1);
  h.state.selectedId.value = secondId;
  await flush(); await h.detail(1, windowResponse(secondId));
  assert.equal(h.state.current.value.window_id, secondId);
});

for (const version of ["inpatient_window_v1", "inpatient_window_v2"]) {
  test(`${version} deep link is checked once; a manual refresh requires a fresh explicit selection`, async t => {
    const h = harness(t);
    const response = windowResponse(firstId, version);
    await h.directory(0, [response]);
    assert.deepEqual(h.calls.details[0].params, { patient_id: 1, admission_id: admission });
    await h.detail(0, response);
    assert.equal(readiness(h).at(-1), true);
    const reload = h.state.reload();
    await h.directory(1, [response]); await reload;
    assertCleared(h);
    assert.equal(h.calls.details.length, 1);
    h.state.selectedId.value = firstId;
    await flush(); await h.detail(1, response);
    assert.equal(readiness(h).at(-1), true);
  });
}

for (const mutation of ["session", "role"]) {
  test(`${mutation} changes drop the held directory and never auto-restore its initial selection`, async t => {
    const h = harness(t);
    if (mutation === "session") h.store.state.user.accessToken = "synthetic-next-session";
    else h.store.getters["user/permissions"] = ["nurse"];
    await flush();
    assert.equal(h.calls.lists.length, 2);
    await h.directory(0); await h.directory(1);
    assertCleared(h);
    assert.equal(h.calls.details.length, 0);
  });
}

test("reactivating a component does not restore an initial window discarded on deactivation", async t => {
  const h = harness(t);
  await h.directory(0); await h.detail(0);
  h.hooks.deactivate.forEach(callback => callback());
  await flush(); assertCleared(h);
  h.hooks.activate.forEach(callback => callback());
  await h.directory(1);
  assertCleared(h);
  assert.equal(h.calls.details.length, 1);
});

test("an explicitly changed initial source identity permits one new deep-link check", async t => {
  const h = harness(t);
  await h.directory(0); await h.detail(0);
  h.props.initialWindowId = secondId;
  await flush(); await h.directory(1, [windowResponse(), windowResponse(secondId)]); await h.detail(1, windowResponse(secondId));
  assert.equal(h.state.current.value.window_id, secondId);
  assert.equal(readiness(h).at(-1), true);
});

const brokenMembers = [
  ["null body", item => { item.snapshot = null; }],
  ["missing body", item => { delete item.snapshot; }],
  ["array body", item => { item.snapshot = []; }],
  ["missing projection", item => { delete item.window_projection; }],
  ["unsupported projection", item => { item.window_projection = "unreviewed"; }],
  ["wrong nested parent patient", item => { item.snapshot.original.order.patient_id = 2; }],
  ["broken original report chain", item => { item.snapshot.original.observation.lab_result_id = "other-report"; }],
];
for (const [name, damage] of brokenMembers) {
  test(`a v2 member with ${name} never marks the actual selector ready`, async t => {
    const h = harness(t);
    const response = windowResponse(); damage(response.snapshot.lab_observations[0]);
    await h.directory(0, [response]); await h.detail(0, response);
    assert.equal(h.state.current.value, null);
    assert.equal(readiness(h).includes(true), false);
    assert.ok(h.state.error.value);
    assert.equal(h.events.some(event => event[0] === "selection" && event[1] !== null), false);
  });
}

test("metadata-only source directories remain readable while full v2 windows reject missing bodies", () => {
  const source = { patient_id: 1, admission_id: admission, snapshot: null };
  assert.equal(labApi.labSourceMatches(source, 1, admission), true);
  const response = windowResponse(); response.snapshot.lab_observations = [source];
  assert.equal(windowApi.observationWindowMatches(response, 1, admission), false);
});
