const { test, expect } = require("@playwright/test");
const { startSofaHarness } = require("./fixtures/sofa-source-harness.cjs");
const actual = require("./fixtures/sofa-synthetic/seven-daily.json");
const native = require("./fixtures/sofa-native-fixtures.cjs");
const fs = require("node:fs"), path = require("node:path");
const { execFileSync } = require("node:child_process");
// View-only arithmetic fixture from the actual pure model and its existing test
// input helpers. No invented score oracle, clinical admission, DB or provider.
const timedNative = JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON || "/home/xusheng/miniconda3/bin/python", ["-c", String.raw`
import json,sys,os
from pathlib import Path
def guard(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)) and Path(os.fsdecode(args[0])).name=='.env':raise AssertionError('no hospital dotenv')
 if event=='socket.connect':raise AssertionError('no hospital DB/network')
sys.addaudithook(guard)
from app.ai.sofa_config import runtime_descriptor,runtime_from_descriptor
from app.ai.sofa_contract import SofaSource,hash_content
from app.ai.sofa_model import compute_sofa
from tests.test_ai_sofa_model import with_vaso,vaso
source=SofaSource.model_validate(with_vaso([vaso('0.1')]))
analysis=compute_sofa(source,hash_content('Independent exact integer browser proof only'),runtime_from_descriptor(runtime_descriptor()))
assert not any(name in sys.modules for name in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'source':source.model_dump(),'analysis':analysis.model_dump()},ensure_ascii=False))
`], { cwd: path.resolve(__dirname, "../../fastapi_be"), encoding: "utf8", maxBuffer: 1048576 }));
let harness;
test.beforeAll(async () => { harness = await startSofaHarness(); });
test.afterAll(async () => { await harness?.close(); });
async function open(page) {
  await page.context().route("**/*", route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort("blockedbyclient"));
  await page.goto(harness.origin);
  await page.waitForFunction(() => !!window.__sofaProbe);
}

test("独立核对Super服务探针使用真实整数PK，原评估UUID与provider身份不混用", async ({ page }) => {
  await open(page);
  const writes = [];
  await page.route("**/api/ai/admin/providers/*/sofa-capabilities", async route => {
    writes.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, data: { synthetic_transport_only: true } }) });
  });
  const result = await page.evaluate(async () => {
    const api = window.__sofaProbe.api, results = [];
    for (const id of [1, 2147483647, 0, -1, true, "1", 2147483648, "11111111-1111-4111-8111-111111111111"]) {
      try { await api.checkSofaProvider(id, 7); results.push(true); } catch { results.push(false); }
    }
    return results;
  });
  expect(result).toEqual([true, true, false, false, false, false, false, false]);
  expect(writes).toEqual([1, 2147483647].map(id => ({ path: `/api/ai/admin/providers/${id}/sofa-capabilities`, body: { expected_revision: 7 } })));
});

test("独立闭集schema拒原型root、继承必填值、污染键与未知约束", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(source => {
    const validator = window.__sofaProbe.schema;
    const names = ["__proto__", "constructor", "prototype", "not_a_registered_model"];
    const unknown = names.map(name => [validator.sofaSchemaDefinition(name), validator.sofaSchemaMatches(name, { arbitrary: true })]);
    const root = structuredClone(source);
    const inherited = Object.create({ schema_version: root.schema_version });
    Object.assign(inherited, root); delete inherited.schema_version;
    const inheritedResult = validator.sofaSchemaMatches("SofaSource", inherited);
    const pollution = ["__proto__", "constructor", "prototype"].map(key => {
      const copy = structuredClone(source);
      Object.defineProperty(copy.population, key, { enumerable: true, value: { sofa_independent_polluted: true } });
      return validator.sofaSchemaMatches("SofaSource", copy);
    });
    const quantity = validator.sofaSchemaDefinition("SofaSource", "Quantity");
    quantity.multipleOf = 2;
    const unknownConstraint = validator.sofaSchemaMatches("SofaSource", source);
    delete quantity.multipleOf;
    return { unknown, inheritedResult, pollution, unknownConstraint, restored: validator.sofaSchemaMatches("SofaSource", source), polluted: Object.hasOwn(Object.prototype, "sofa_independent_polluted") };
  }, actual.specialist_source);
  expect(result).toEqual({ unknown: Array(4).fill([null, false]), inheritedResult: false, pollution: [false, false, false], unknownConstraint: false, restored: true, polluted: false });
});

test("独立原量schema保留超过32位的原Decimal字符串，拒numeric零、false、指数和超精度", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(() => {
    const match = window.__sofaProbe.schema.sofaSchemaMatches;
    return ["0", "0.00000000", "2147483648.00000000", "9999999999999999.99999999", null, 0, false, "1e3", "0.000000001", "10000000000000000"].map(value => {
      const quantity = { value, unit: "mm[Hg]", absent_reason: value === null ? "unknown" : null };
      return match("SofaSource", quantity, "Quantity");
    });
  });
  expect(result).toEqual([true, true, true, true, true, false, false, false, false, false]);
});

test("独立UTC微秒与Gregorian日历核验不经32位时间或本地时区", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(admissionId => {
    const request = window.__sofaProbe.api.sofaPeriodRequest, out = [];
    for (const [start, end, patient] of [
      ["2024-02-29T00:00:00.123456Z", "2024-03-01T00:00:00.123456Z", 2147483647],
      ["2000-02-29T00:00:00.000001Z", "2000-03-01T00:00:00.000001Z", 1],
      ["1000-01-01T00:00:00.000001Z", "1000-01-02T00:00:00.000001Z", 1],
      ["1900-02-29T00:00:00.000000Z", "1900-03-01T00:00:00.000000Z", 1],
      ["2026-02-30T00:00:00.000000Z", "2026-03-01T00:00:00.000000Z", 1],
      ["2024-02-29T00:00:00.123456Z", "2024-03-01T00:00:00.123455Z", 1],
      ["2024-02-29T24:00:00.000000Z", "2024-03-01T24:00:00.000000Z", 1],
      ["2024-02-29T00:00:00.000000Z", "2024-03-01T00:00:00.000000Z", 2147483648],
    ]) {
      try { const value = request(patient, admissionId, { period_start: start, period_end: end, as_of: end }); out.push(value.period_start === start && value.period_end === end); } catch { out.push(false); }
    }
    return out;
  }, actual.admission_id);
  expect(result).toEqual([true, true, true, false, false, false, false, false]);
});

test("独立完整七根原件在重算public SHA后仍不可修改零词形、NT、原bool、单位或stream证据", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(async original => {
    const api = window.__sofaProbe.api;
    const digest = async value => {
      const ordered = item => Array.isArray(item) ? item.map(ordered) : item && typeof item === "object" ? Object.fromEntries(Object.keys(item).sort().map(key => [key, ordered(item[key])])) : item;
      return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(ordered(value))))), byte => byte.toString(16).padStart(2, "0")).join("");
    };
    const changes = [
      source => { const zero = source.urine_intervals.find(row => row.volume_ml === "0"); if (!zero) throw new Error("actual zero fixture required"); zero.volume_ml = "0.00000000"; },
      source => { source.population.applicability_confirmed = !source.population.applicability_confirmed; },
      source => { const component = source.gcs_observations[0].components.verbal; component.score = component.score === 1 ? 2 : 1; component.absent_reason = null; },
      source => { source.vasoactive_groups[0].intervals[0].weight_applicability_confirmed = !source.vasoactive_groups[0].intervals[0].weight_applicability_confirmed; },
      source => { source.vasoactive_groups[0].intervals[0].stream_key = "0".repeat(64); },
      source => { source.lab_observations[0].quantity.original_unit_hash = "0".repeat(64); },
      source => { source.urine_intervals[0].patient_total = source.urine_intervals[0].patient_total === false ? true : false; },
    ];
    const valid = await api.verifySofaAssessment(original, original.patient_id, original.admission_id), accepted = [];
    for (const change of changes) {
      const row = structuredClone(original); change(row.specialist_source); row.projection_hash = await digest(row.specialist_source);
      accepted.push(await api.verifySofaAssessment(row, row.patient_id, row.admission_id));
    }
    return { valid, accepted };
  }, actual);
  expect(result).toEqual({ valid: true, accepted: Array(7).fill(false) });
});

test("独立实际源原始private全文与公开SHA均重算后仍拒伪造Doctor资格", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(async original => {
    const api = window.__sofaProbe.api;
    const digest = async value => {
      const order = item => Array.isArray(item) ? item.map(order) : item && typeof item === "object" ? Object.fromEntries(Object.keys(item).sort().map(key => [key, order(item[key])])) : item;
      return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(order(value))))), byte => byte.toString(16).padStart(2, "0")).join("");
    };
    const out = [];
    for (const mutation of [q => q.doctor_id = "1", q => q.clinical_review_signed = 1, q => q.role_at_creation = "nurse", q => q.care_authorization = "unknown"]) {
      const row = structuredClone(original); mutation(row.snapshot.author_qualification);
      row.content_hash = await digest(row.snapshot); row.source_id = `sofa_assessment:${row.assessment_id}:${row.content_hash.slice(0, 12)}`;
      row.specialist_source.content_hash = row.content_hash; row.specialist_source.source_id = row.source_id; row.projection_hash = await digest(row.specialist_source);
      out.push(await api.verifySofaAssessment(row, row.patient_id, row.admission_id));
    }
    return out;
  }, actual);
  expect(result).toEqual([false, false, false, false]);
});

test("独立真实七类private自由原文只转typed hash公开，不泄露流标识或临床备注", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(async row => {
    const privateStrings = new Set();
    const walk = value => { if (Array.isArray(value)) return value.forEach(walk); if (!value || typeof value !== "object") return; for (const [key, item] of Object.entries(value)) { if ((key.endsWith("note") || ["external_stream_id", "source_namespace", "barcode", "device_description"].includes(key)) && typeof item === "string" && item.length > 5) privateStrings.add(item); else walk(item); } };
    walk(row.snapshot);
    const source = JSON.stringify(row.specialist_source), leaked = [...privateStrings].filter(value => source.includes(value));
    return { checkedPrivateStrings: privateStrings.size, leaked, verified: await window.__sofaProbe.api.verifySofaAssessment(row, row.patient_id, row.admission_id) };
  }, actual);
  expect(result.checkedPrivateStrings).toBeGreaterThan(5);
  expect(result.leaked).toEqual([]);
  expect(result.verified).toBe(true);
});

test("独立真实native大于32位duration proof与零总分保持typed，不使用人工阈值oracle", async ({ page }) => {
  await open(page);
  const result = await page.evaluate(async values => {
    const api = window.__sofaProbe.api, out = {}, durations = [];
    for (const [name, item] of Object.entries(values)) {
      out[name] = await (item.source.schema_version === "sofa1_change_source_v1" ? api.verifySofaChangeAnalysis : api.verifySofaAnalysis)(item.source, item.analysis, item.scope?.projection_hash ?? null);
      const analyses = item.analysis.current_analysis ? [item.analysis.current_analysis] : [item.analysis];
      for (const analysis of analyses) for (const domain of analysis.domains) for (const candidate of domain.candidates) for (const proof of candidate.calculations) if (proof.kind === "continuous_tier") durations.push(proof.duration_microseconds);
    }
    return { out, durations, completeZero: values.complete_zero.analysis.complete_total_score, unknownSubtotal: values["daily-active"].analysis.known_subtotal };
  }, { ...native, actual_pure_duration: timedNative });
  expect(result.out).toEqual(Object.fromEntries([...Object.keys(native), "actual_pure_duration"].map(name => [name, true])));
  expect(result.durations.some(value => value > 2147483647)).toBe(true);
  expect(result.completeZero).toBe(0);
  expect(result.unknownSubtotal).toBeNull();
});

test("独立同患者跨住院observed原基线守自己的住院，拒改绑当前住院", async ({ page }) => {
  const file = path.join(__dirname, "fixtures/sofa-synthetic/change-cross-admission.json");
  expect(fs.existsSync(file), "actual memory-ORM cross-admission fixture must be committed").toBe(true);
  const row = JSON.parse(fs.readFileSync(file, "utf8"));
  expect(row.snapshot.baseline_assessment.admission_id).not.toBe(row.admission_id);
  await open(page);
  const result = await page.evaluate(async row => {
    const api = window.__sofaProbe.api, baseline = row.snapshot.baseline_assessment;
    const valid = await api.verifySofaChangeAssessment(row, row.patient_id, row.admission_id), own = await api.verifySofaAssessment(baseline, row.patient_id, baseline.admission_id), rebound = await api.verifySofaAssessment(baseline, row.patient_id, row.admission_id);
    const changed = structuredClone(row); changed.snapshot.baseline_assessment.admission_id = row.admission_id;
    return { valid, own, rebound, changed: await api.verifySofaChangeAssessment(changed, row.patient_id, row.admission_id) };
  }, row);
  expect(result).toEqual({ valid: true, own: true, rebound: false, changed: false });
});
