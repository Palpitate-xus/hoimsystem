/* Lossless build storage for allowlisted public static JSON; never runtime input. */
const path = require('node:path');
const crypto = require('node:crypto');
const { MAX_SCHEMA_BYTES, decodeSchemaText } = require('../src/api/schemaDataCodec.cjs');

function encodeStaticJson(source) {
  const bytes = Buffer.isBuffer(source) ? source : Buffer.from(source, 'utf8');
  if (!bytes.length || bytes.length > MAX_SCHEMA_BYTES) throw new Error('Complete static schema exceeds the build data limit');
  const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  JSON.parse(text);
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

function emitStaticJson(context, value) {
  if (context.getOptions?.().documentData === true) {
    const packed = Buffer.from(value.encoded, 'base64');
    const sha256 = crypto.createHash('sha256').update(packed).digest('hex');
    const filename = `static/schema-data/${sha256}.schema.json`;
    context.emitFile(filename, JSON.stringify({schema_version:'hoim_static_schema_record_v1',encoded:value.encoded,byteLength:value.byteLength,packedBytes:packed.length,sha256}));
    const reader = context.utils.contextify(context.context, path.resolve(__dirname, '../src/api/schemaDataDocument.cjs'));
    return `module.exports = require(${JSON.stringify(reader)}).readSchemaDocumentData(${JSON.stringify(sha256)}, ${value.byteLength}, ${packed.length});`;
  }
  const decoder = context.utils.contextify(context.context, path.resolve(__dirname, '../src/api/schemaDataCodec.cjs'));
  return `module.exports = require(${JSON.stringify(decoder)}).decodeSchemaData(${JSON.stringify(value.encoded)}, ${value.byteLength});`;
}

module.exports = {encodeStaticJson, emitStaticJson};
