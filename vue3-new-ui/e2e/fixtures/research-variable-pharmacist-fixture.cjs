const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
function loadPharmacistLifecycle(){
const packed=require('./research-variable-pharmacist-main.packed.json'),raw=zlib.gunzipSync(Buffer.from(packed.gzip_base64,'base64'),{maxOutputLength:8388608});
if(packed.schema_version!=='research_variable_pharmacist_main_gzip_v1'||raw.length!==packed.original_bytes||crypto.createHash('sha256').update(raw).digest('hex')!==packed.original_sha256)throw Error('Actual pharmacist lifecycle bytes differ');
const fixture=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw)),byStage=Object.fromEntries(fixture.records.map(row=>[row.stage,row])),data=stage=>JSON.parse(byStage[stage].body).data,scope=data('scope.context'),id=scope.scope_id,request=byStage['dictionary.created'].request_json;
for(const row of fixture.records)if(Buffer.byteLength(row.body)!==row.body_bytes||crypto.createHash('sha256').update(row.body).digest('hex')!==row.body_sha256)throw Error('Actual response bytes differ');
for(const[name,sha]of Object.entries(fixture.backend_bindings))if(crypto.createHash('sha256').update(fs.readFileSync(path.resolve(__dirname,'../../..',name))).digest('hex')!==sha)throw Error('Current pharmacist backend binding differs: '+name);
return{fixture,byStage,data,scope,id,request};
}
module.exports={loadPharmacistLifecycle};
