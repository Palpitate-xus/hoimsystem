const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function load(name){
 const packed=JSON.parse(fs.readFileSync(path.join(__dirname,'operations-support',name+'.packed.json'),'utf8'));
 if(packed.schema_version!=='operations_actual_http_fixture_gzip_v1')throw new Error('Unknown fixture envelope');
 const raw=zlib.gunzipSync(Buffer.from(packed.gzip_base64,'base64'));if(raw.length!==packed.original_bytes||sha(raw)!==packed.original_sha256)throw new Error('Actual original packet bytes changed');
 const parsed=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw)),rows=Array.isArray(parsed)?parsed:parsed?.schema_version==='operations_actual_same_case_ui_packets_v2'?parsed.packets:null;
 if(!Array.isArray(rows)||rows.some(r=>typeof r.body!=='string'||!Number.isInteger(r.status)))throw new Error('Actual HTTP packet malformed');
 const data=r=>{const value=JSON.parse(r.body);return value&&typeof value==='object'&&Object.hasOwn(value,'data')?value.data:value;};
 return{header:Array.isArray(parsed)?null:parsed,rows,data,first:(method,suffix)=>{const row=rows.find(x=>x.method===method&&x.path.endsWith(suffix));if(!row)throw new Error('Missing actual HTTP response '+method+suffix);return row;},original:packed};
}
module.exports={loadOperationsPackets:load};
