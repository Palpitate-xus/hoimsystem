/* Public generated contracts are inert HTML data, included in total asset budgets. */
const crypto = require('node:crypto');
const HtmlRspackPlugin = require('html-rspack-plugin');
const {decodeSchemaText, decodeStaticCodeBytes, MAX_SCHEMA_BYTES} = require('../src/api/schemaDataCodec.cjs');
const snapshots = new WeakMap();

function encodeHtmlCodeBytes(bytes) {
  if (!(bytes instanceof Uint8Array) || !bytes.length || bytes.length > MAX_SCHEMA_BYTES * 2) throw new Error('Invalid complete public static code bytes');
  const alphabet = '!#$%()*+,-./0123456789:;=?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_abcdefghijklmnopqrstuvwxyz{|';
  const padding = (4 - bytes.length % 4) % 4;
  let encoded = '~1' + padding;
  for (let offset = 0; offset < bytes.length; offset += 4) {
    let word = 0;
    for (let i = 0; i < 4; i++) word = word * 256 + (bytes[offset + i] || 0);
    let group = '';
    for (let i = 0; i < 5; i++) {group = alphabet[word % 85] + group; word = Math.floor(word / 85);}
    encoded += group;
  }
  return encoded;
}

function embedSchemaData(compilation, html) {
  let entries = snapshots.get(compilation);
  if (!entries) {
    entries = {};
    const assets = compilation.getAssets().filter(asset => /^static\/schema-data\/[a-f0-9]{64}\.schema\.json$/.test(asset.name)).sort((a,b) => a.name.localeCompare(b.name));
    if (!assets.length || assets.length > 256) throw new Error('Missing bounded generated static schema records');
    for (const asset of assets) {
      const value = JSON.parse(asset.source.source().toString());
      if (!value || Object.keys(value).sort().join(',') !== 'byteLength,encoded,packedBytes,schema_version,sha256' || value.schema_version !== 'hoim_static_schema_record_v1' || !Number.isSafeInteger(value.byteLength) || value.byteLength < 1 || value.byteLength > MAX_SCHEMA_BYTES || !Number.isSafeInteger(value.packedBytes) || value.packedBytes < 1 || value.packedBytes > MAX_SCHEMA_BYTES * 2 || typeof value.encoded !== 'string') throw new Error('Invalid whole static schema build record');
      const packed = Buffer.from(value.encoded, 'base64');
      const sha = crypto.createHash('sha256').update(packed).digest('hex');
      if (value.encoded !== packed.toString('base64') || packed.length !== value.packedBytes || sha !== value.sha256 || asset.name !== `static/schema-data/${sha}.schema.json`) throw new Error('Static schema asset SHA or length differs');
      JSON.parse(decodeSchemaText(value.encoded, value.byteLength));
      const dense = encodeHtmlCodeBytes(packed);
      const encoded = dense.length < value.encoded.length ? dense : value.encoded;
      if (!Buffer.from(decodeStaticCodeBytes(encoded, packed.length), 'binary').equals(packed)) throw new Error('Static HTML code transport changed original bytes');
      entries[sha] = {encoded, byteLength: value.byteLength, packedBytes: value.packedBytes};
    }
    snapshots.set(compilation, entries);
    for (const asset of assets) compilation.deleteAsset(asset.name);
  }
  const data = JSON.stringify({schema_version: 'hoim_static_schema_document_v1', entries});
  if (data.length > 8388608 || /[^\x20-\x7e]/.test(data) || data.includes('<') || html.includes('id="hoim-schema-data"') || html.includes('id=hoim-schema-data') || !html.includes('</head>')) throw new Error('Invalid static schema HTML data envelope');
  return html.replace('</head>', () => `<script id="hoim-schema-data" type="application/json">${data}</script></head>`);
}

class SchemaHtmlDataPlugin {
  apply(compiler) {
    compiler.hooks.compilation.tap('HoimStaticSchemaData', compilation => {
      HtmlRspackPlugin.getCompilationHooks(compilation).beforeEmit.tap('HoimStaticSchemaData', data => ({...data, html: embedSchemaData(compilation, data.html)}));
    });
  }
}
module.exports = {SchemaHtmlDataPlugin, embedSchemaData, encodeHtmlCodeBytes};
