const zlib=require('node:zlib'),crypto=require('node:crypto'),packed=require('./infection-cluster/actual.packed.json');
function load(name){if(!Object.hasOwn(packed,name))throw new Error('Unknown actual packet');const item=packed[name],raw=zlib.gunzipSync(Buffer.from(item.gzip_base64,'base64'));if(raw.length!==item.bytes||crypto.createHash('sha256').update(raw).digest('hex')!==item.sha256)throw new Error('Actual packet original bytes changed');return JSON.parse(raw.toString('utf8'));}
module.exports={load,manifest:packed};
