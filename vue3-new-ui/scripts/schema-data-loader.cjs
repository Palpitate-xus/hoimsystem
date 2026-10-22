/* Complete generated schema registries retain their original closed build contract. */
const {encodeStaticJson, emitStaticJson} = require('./public-static-data.cjs');
const {decodeSchemaText} = require('../src/api/schemaDataCodec.cjs');

function encodeSchemaData(source) {
  const value = encodeStaticJson(source);
  const text = decodeSchemaText(value.encoded, value.byteLength);
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
  return value;
}
function schemaDataLoader(source) {
  this.cacheable();
  return emitStaticJson(this, encodeSchemaData(source));
}
schemaDataLoader.raw = true;
schemaDataLoader.encodeSchemaData = encodeSchemaData;
module.exports = schemaDataLoader;
