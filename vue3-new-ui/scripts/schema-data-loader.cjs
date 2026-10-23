/* Complete generated schema registries retain their original closed build contract. */
const {encodeStaticJson, emitStaticJson} = require('./public-static-data.cjs');
const path=require('node:path');
const publicFixed=require('./static-contract-data-loader.cjs');
const PUBLIC_FIXED_PATHS=Object.freeze(publicFixed.PUBLIC_CONTRACTS.map(name=>path.resolve(__dirname,'..',name)));
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
  const options=this.getOptions?.()||{};
  if(Object.keys(options).some(key=>!['kind','documentData'].includes(key))||options.kind!==undefined&&options.kind!=='public_fixed'||options.documentData!==undefined&&typeof options.documentData!=='boolean')throw new Error('Unknown complete public build data mode');
  if(options.kind==='public_fixed'&&!PUBLIC_FIXED_PATHS.includes(this.resourcePath))throw new Error('Public fixed build data path is not allowlisted');
  return emitStaticJson(this,options.kind==='public_fixed'?publicFixed.encodePublicFixedData(source):encodeSchemaData(source));
}
schemaDataLoader.raw = true;
schemaDataLoader.encodeSchemaData = encodeSchemaData;
schemaDataLoader.PUBLIC_FIXED_PATHS=PUBLIC_FIXED_PATHS;
schemaDataLoader.encodePublicFixedData=publicFixed.encodePublicFixedData;
schemaDataLoader.MAX_FIXED_NODES=publicFixed.MAX_FIXED_NODES;
schemaDataLoader.MAX_FIXED_DEPTH=publicFixed.MAX_FIXED_DEPTH;
module.exports = schemaDataLoader;
