const crypto=require('node:crypto'),zlib=require('node:zlib'),packed=require('./charge-assistant/actual.packed.json');
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
function load(kind='chat'){
 const item=packed.profiles[kind];if(!item)throw new Error('Unknown actual charge profile');
 const compressed=Buffer.from(item.gzip_base64,'base64');if(compressed.length!==item.gzip_bytes||hash(compressed)!==item.gzip_sha256)throw new Error('Compressed actual charge fixture differs');
 const raw=zlib.gunzipSync(compressed);if(raw.length!==item.bytes||hash(raw)!==item.sha256)throw new Error('Original actual charge export bytes differ');
 return JSON.parse(raw);
}
module.exports={load};
