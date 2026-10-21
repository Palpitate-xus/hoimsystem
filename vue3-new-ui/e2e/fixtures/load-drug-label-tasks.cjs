const zlib=require('node:zlib'),crypto=require('node:crypto'),assert=require('node:assert/strict'),packed=require('./drug-label-tasks/actual.packed.json');
function load(kind='chat'){assert(['chat','responses'].includes(kind));const value=packed[kind],raw=zlib.gunzipSync(Buffer.from(value.gzip_base64,'base64'));assert.equal(raw.length,value.raw_bytes);assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),value.raw_sha256);return JSON.parse(raw);}
module.exports={load};
