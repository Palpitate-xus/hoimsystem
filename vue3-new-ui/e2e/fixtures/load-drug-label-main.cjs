const zlib=require('node:zlib'),crypto=require('node:crypto'),assert=require('node:assert/strict'),packed=require('./drug-label-main/actual.packed.json');
const hash=v=>crypto.createHash('sha256').update(v).digest('hex');
function load(kind='chat'){
 assert(['chat','responses'].includes(kind));const entry=packed[kind],compressed=Buffer.from(entry.gzip_base64,'base64');assert.equal(hash(compressed),entry.gzip_sha256);const raw=zlib.gunzipSync(compressed);assert.equal(raw.length,entry.raw_bytes);assert.equal(hash(raw),entry.raw_sha256);const packet=JSON.parse(raw);
 for(const[name,wire]of Object.entries(packet.raw_http_responses)){const body=Buffer.from(wire.body_utf8,'utf8');assert.equal(body.length,wire.body_bytes);assert.equal(hash(body),wire.body_sha256);assert.equal(wire.status_code,200);assert.deepEqual(JSON.parse(body),packet[name]);}
 return packet;
}
module.exports={load};
