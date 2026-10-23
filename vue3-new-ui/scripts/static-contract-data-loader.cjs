/* Exact checked-in public contracts only; no patient data, remote data or arbitrary JSON. */
const path = require('node:path');
const {encodeStaticJson, emitStaticJson} = require('./public-static-data.cjs');
const {MAX_SCHEMA_BYTES}=require('../src/api/schemaDataCodec.cjs');
const ROOT = path.resolve(__dirname, '..');
const PUBLIC_CONTRACTS = Object.freeze([
  "src/api/bedFixedPolicy.json",
  "src/api/iconGallery.json",
  "src/api/ai/researchVariableTaskFixed.json",
  "src/api/ai/researchVariableSourceColumns.json",
  "src/api/publicInterfaceTextPool.json",
  "src/api/ai/chargeReconciliationFixedPolicy.json",
  "src/api/ai/chargeReconciliationUiFixed.json",
  "src/api/ai/codingFixedPolicy.json",
  "src/api/ai/documentChangeFixed.json",
  "src/api/ai/rcaEvidenceFixed.json",
  "src/api/ai/documentExtractionFixed.json",
  "src/api/ai/drugLabelSourcePolicy.json",
  "src/api/ai/drugLabelTaskFixed.json",
  "src/api/ai/drugLabelTaskSchemaLinks.json",
  "src/api/ai/inventoryFixedPolicy.json",
  "src/api/ai/supplyFixedPolicy.json",
  "src/api/ai/surgeryFixedPolicy.json",
  "src/api/ai/surgeryScenarioFields.json"
]);
const MAX_FIXED_NODES = 100000, MAX_FIXED_DEPTH = 32;
function encodePublicFixedData(source) {
  const bytes = Buffer.isBuffer(source) ? source : Buffer.from(source, 'utf8');
  if (!bytes.length || bytes.length > MAX_SCHEMA_BYTES) throw new Error('Complete public fixed data exceeds the build data limit');
  const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes), parsed = JSON.parse(text);
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Expected complete public fixed object');
  const stack = [[parsed, 0]]; let nodes = 0;
  const validText = value => { for (const point of value) { const code = point.codePointAt(0); if (code >= 0xD800 && code <= 0xDFFF) throw new Error('Invalid public fixed Unicode'); } };
  while (stack.length) {
    const [value, depth] = stack.pop();
    if (++nodes > MAX_FIXED_NODES || depth > MAX_FIXED_DEPTH) throw new Error('Complete public fixed structure exceeds the build node/depth limit');
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('Invalid public fixed number');
    if (typeof value === 'string') validText(value);
    if (value !== null && typeof value === 'object') for (const key of Object.keys(value)) {
      validText(key); if (['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('Invalid public fixed object key');
      stack.push([value[key], depth + 1]);
    }
  }
  return encodeStaticJson(bytes);
}

function staticContractDataLoader(source) {
  const relative = path.relative(ROOT, this.resourcePath).replace(/\\/g, '/');
  if (!PUBLIC_CONTRACTS.includes(relative)) throw new Error('Static contract file is not allowlisted');
  this.cacheable();
  return emitStaticJson(this, encodePublicFixedData(source));
}
staticContractDataLoader.raw = true;
staticContractDataLoader.PUBLIC_CONTRACTS = PUBLIC_CONTRACTS;
staticContractDataLoader.encodePublicFixedData=encodePublicFixedData;
staticContractDataLoader.MAX_FIXED_NODES=MAX_FIXED_NODES;
staticContractDataLoader.MAX_FIXED_DEPTH=MAX_FIXED_DEPTH;
module.exports = staticContractDataLoader;
