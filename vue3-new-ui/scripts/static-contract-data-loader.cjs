/* Exact checked-in public contracts only; no patient data, remote data or arbitrary JSON. */
const path = require('node:path');
const {encodeStaticJson, emitStaticJson} = require('./public-static-data.cjs');
const ROOT = path.resolve(__dirname, '..');
const PUBLIC_CONTRACTS = Object.freeze([
  "src/api/bedFixedPolicy.json",
  "src/api/iconGallery.json",
  "src/api/publicInterfaceTextPool.json",
  "src/api/ai/chargeReconciliationFixedPolicy.json",
  "src/api/ai/chargeReconciliationUiFixed.json",
  "src/api/ai/codingFixedPolicy.json",
  "src/api/ai/documentChangeFixed.json",
  "src/api/ai/documentExtractionFixed.json",
  "src/api/ai/drugLabelSourcePolicy.json",
  "src/api/ai/drugLabelTaskFixed.json",
  "src/api/ai/drugLabelTaskSchemaLinks.json",
  "src/api/ai/inventoryFixedPolicy.json",
  "src/api/ai/supplyFixedPolicy.json",
  "src/api/ai/surgeryFixedPolicy.json",
  "src/api/ai/surgeryScenarioFields.json"
]);
function staticContractDataLoader(source) {
  const relative = path.relative(ROOT, this.resourcePath).replace(/\\/g, '/');
  if (!PUBLIC_CONTRACTS.includes(relative)) throw new Error('Static contract file is not allowlisted');
  this.cacheable();
  return emitStaticJson(this, encodeStaticJson(source));
}
staticContractDataLoader.raw = true;
staticContractDataLoader.PUBLIC_CONTRACTS = PUBLIC_CONTRACTS;
module.exports = staticContractDataLoader;
