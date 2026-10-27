// Actual isolated workers and production readers; original SQL strings are retained.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
function loadUnknownUsage(domain) {
  if (!['document-extraction', 'document-change', 'drug-label', 'satisfaction'].includes(domain)) throw new Error('Unknown captured native domain');
  return ['chat', 'responses'].map(kind => {
    const stem = path.join(__dirname, 'native-unknown-usage', domain + '-' + kind);
    const bytes = fs.readFileSync(stem + '.json');
    const provenance = JSON.parse(fs.readFileSync(stem + '.provenance.json', 'utf8'));
    if (provenance.domain !== domain || provenance.kind !== kind || crypto.createHash('sha256').update(bytes).digest('hex') !== provenance.fixture_sha256) throw new Error('Actual native unknown-usage capture changed');
    return JSON.parse(bytes);
  });
}
module.exports = { loadUnknownUsage };
