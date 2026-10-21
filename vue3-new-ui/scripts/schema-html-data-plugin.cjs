/* Public generated contracts are inert HTML data, included in total asset budgets. */
const crypto = require('node:crypto');
const HtmlRspackPlugin = require('html-rspack-plugin');
const {decodeSchemaText, MAX_SCHEMA_BYTES} = require('../src/api/schemaDataCodec.cjs');
const snapshots = new WeakMap();

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
      entries[sha] = {encoded: value.encoded, byteLength: value.byteLength, packedBytes: value.packedBytes};
    }
    snapshots.set(compilation, entries);
    for (const asset of assets) compilation.deleteAsset(asset.name);
  }
  const data = JSON.stringify({schema_version: 'hoim_static_schema_document_v1', entries});
  if (data.length > 8388608 || /[^\x20-\x7e]/.test(data) || data.includes('<') || html.includes('id="hoim-schema-data"') || html.includes('id=hoim-schema-data') || !html.includes('</head>')) throw new Error('Invalid static schema HTML data envelope');
  return html.replace('</head>', `<script id="hoim-schema-data" type="application/json">${data}</script></head>`);
}

class SchemaHtmlDataPlugin {
  apply(compiler) {
    compiler.hooks.compilation.tap('HoimStaticSchemaData', compilation => {
      HtmlRspackPlugin.getCompilationHooks(compilation).beforeEmit.tap('HoimStaticSchemaData', data => ({...data, html: embedSchemaData(compilation, data.html)}));
    });
  }
}
module.exports = {SchemaHtmlDataPlugin, embedSchemaData};
