const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),zlib=require('node:zlib');
const hash=v=>crypto.createHash('sha256').update(v).digest('hex'),cache=new Map();
function actual(version='second'){
 if(!['first','second'].includes(version))throw new Error('Explicit actual export version required');
 if(!cache.has(version)){
  const packed=JSON.parse(fs.readFileSync(path.join(__dirname,'deidentification','shared-'+version+'.packed.json'),'utf8')),raw=zlib.gunzipSync(Buffer.from(packed.gzip_base64,'base64'));
  if(raw.length!==packed.original_bytes||hash(raw)!==packed.original_sha256)throw new Error('Actual shared export bytes differ');
  const value=JSON.parse(raw.toString('utf8'));
  for(const packet of Object.values(value.cases)){
   for(const response of packet.additional_actual_http)if(hash(response.raw_utf8)!==response.raw_sha256)throw new Error('Actual HTTP response bytes differ');
   for(const [part,text]of Object.entries(packet.success.parts_original_utf8))if(hash(text)!==packet.success.metadata.part_hashes[part]||JSON.stringify(JSON.parse(text))!==JSON.stringify(packet.success.parts[part]))throw new Error('Actual independent part differs');
  }
  cache.set(version,value);
 }
 return structuredClone(cache.get(version));
}
module.exports={actual};
