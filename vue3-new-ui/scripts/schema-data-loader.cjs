/* Build-time storage encoding only; no schema constraint or validator changes. */
const path = require('node:path');
const { MAX_SCHEMA_BYTES, decodeSchemaText } = require('../src/api/schemaDataCodec.cjs');

function encodeSchemaData(source) {
  const bytes = Buffer.isBuffer(source) ? source : Buffer.from(source, 'utf8');
  if (!bytes.length || bytes.length > MAX_SCHEMA_BYTES) throw new Error('Complete static schema exceeds the build data limit');
  const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  const parsed = JSON.parse(text);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const registry = value => object(value) && Object.keys(value).sort().join(',') === 'models,nodes' && object(value.models) && Array.isArray(value.nodes);
  const wrapped = object(parsed) && (
    Object.keys(parsed).sort().join(',') === 'policy,schemas' && object(parsed.policy) ||
    Object.keys(parsed).sort().join(',') === 'constants,schemas' && object(parsed.constants)
  ) && registry(parsed.schemas);
  if (!registry(parsed) && !wrapped) {
    throw new Error('Expected an actual complete generated schema registry');
  }
  const output = [], literals = [], positions = new Map();
  const keyAt = index => bytes.readUInt32LE(index);
  function record(index) {
    if (index + 4 > bytes.length) return;
    const key = keyAt(index), candidates = positions.get(key) || [];
    candidates.push(index);
    if (candidates.length > 16) candidates.shift();
    positions.set(key, candidates);
  }
  function flush() {
    if (!literals.length) return;
    output.push(literals.length - 1, ...literals);
    literals.length = 0;
  }
  for (let index = 0; index < bytes.length;) {
    let best = 0, selected = 0;
    const candidates = index + 4 <= bytes.length ? positions.get(keyAt(index)) || [] : [];
    for (let cursor = candidates.length - 1; cursor >= 0; cursor--) {
      const prior = candidates[cursor];
      if (index - prior > 65535) break;
      let length = 4;
      while (length < 131 && index + length < bytes.length && bytes[prior + length] === bytes[index + length]) length++;
      if (length > best) { best = length; selected = prior; }
      if (best === 131) break;
    }
    if (best >= 4) {
      flush();
      const distance = index - selected;
      output.push(128 + best - 4, distance & 255, distance >>> 8);
      for (let offset = 0; offset < best; offset++) record(index + offset);
      index += best;
    } else {
      literals.push(bytes[index]);
      record(index++);
      if (literals.length === 128) flush();
    }
  }
  flush();
  const encoded = Buffer.from(output).toString('base64');
  if (decodeSchemaText(encoded, bytes.length) !== text) throw new Error('Static schema UTF8 round trip changed the original bytes');
  return { encoded, byteLength: bytes.length };
}

function schemaDataLoader(source) {
  this.cacheable();
  const value = encodeSchemaData(source);
  const decoder = this.utils.contextify(this.context, path.resolve(__dirname, '../src/api/schemaDataCodec.cjs'));
  return `module.exports = require(${JSON.stringify(decoder)}).decodeSchemaData(${JSON.stringify(value.encoded)}, ${value.byteLength});`;
}
schemaDataLoader.raw = true;
schemaDataLoader.encodeSchemaData = encodeSchemaData;
module.exports = schemaDataLoader;
