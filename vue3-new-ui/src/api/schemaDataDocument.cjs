/* Read inert generated validation contracts, never clinical data or executable code. */
const {MAX_SCHEMA_BYTES, decodeSchemaData, decodeStaticCodeBytes} = require('./schemaDataCodec.cjs');
const {schemaDataHash} = require('./schemaDataHash.cjs');
let entries;
const checked = new Map();

function readSchemaDocumentData(sha256, byteLength, packedBytes) {
  if (typeof sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(sha256) || !Number.isSafeInteger(byteLength) || byteLength < 1 || byteLength > MAX_SCHEMA_BYTES || !Number.isSafeInteger(packedBytes) || packedBytes < 1 || packedBytes > MAX_SCHEMA_BYTES * 2) throw new Error('Invalid generated static schema binding');
  if (!entries) {
    const nodes = document.querySelectorAll('script#hoim-schema-data[type="application/json"]');
    if (nodes.length !== 1 || document.querySelectorAll('#hoim-schema-data').length !== 1) throw new Error('Missing or ambiguous complete static schema data');
    const text = nodes[0].textContent;
    if (typeof text !== 'string' || !text.length || text.length > 8388608 || /[^\x20-\x7e]/.test(text)) throw new Error('Invalid complete static schema registry bytes');
    const value = JSON.parse(text);
    if (!value || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'entries,schema_version' || value.schema_version !== 'hoim_static_schema_document_v1' || !value.entries || Array.isArray(value.entries) || typeof value.entries !== 'object' || Object.keys(value.entries).length > 256 || Object.keys(value.entries).some(key => !/^[a-f0-9]{64}$/.test(key))) throw new Error('Invalid closed generated static schema registry');
    entries = value.entries;
  }
  const key = JSON.stringify([sha256, byteLength, packedBytes]);
  if (checked.has(key)) return checked.get(key);
  const value = entries[sha256];
  if (!value || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'byteLength,encoded,packedBytes' || value.byteLength !== byteLength || value.packedBytes !== packedBytes || typeof value.encoded !== 'string') throw new Error('Incomplete generated static schema record');
  const binary = decodeStaticCodeBytes(value.encoded, packedBytes);
  if (binary.length !== packedBytes) throw new Error('Invalid original static schema code bytes');
  const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
  if (schemaDataHash(bytes) !== sha256) throw new Error('Generated static schema SHA differs');
  const result = decodeSchemaData(value.encoded, byteLength);
  checked.set(key, result);
  return result;
}
module.exports = {readSchemaDocumentData};
