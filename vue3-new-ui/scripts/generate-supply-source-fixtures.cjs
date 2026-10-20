const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
for(const[input,file]of[['/tmp/hoim-supply-source-signer-ui-actual-fixtures.json','actual.json'],['/tmp/hoim-supply-source-panel-governance-final-ui-actual-fixtures.json','panel.json']]){
const raw=fs.readFileSync(input),actual=JSON.parse(raw),{packets,...retained}=actual;
assert.ok(Array.isArray(packets)&&packets.length>20);
const value={...retained,browser_provenance:{source_path:input,source_sha256:crypto.createHash('sha256').update(raw).digest('hex'),source_bytes:raw.length,scope:'Actual synthetic memory ORM/JWT/isolated ASGI response DTOs. Browser routes intercept these exact responses; browser tests are isolated mocks, not real HTTP backend tests.',omitted_keys:['packets']}};
assert.deepEqual(JSON.parse(JSON.stringify(value, (key,v)=>key==='browser_provenance'?undefined:v)),retained);
const target=path.resolve(__dirname,'../e2e/fixtures/supply-sources',file),text=JSON.stringify(value)+'\n';
if(process.argv.includes('--check'))assert.equal(fs.readFileSync(target,'utf8'),text);else{fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,text);}
process.stdout.write(`Verified unchanged ${Object.keys(retained).length} actual response groups: ${Buffer.byteLength(text)} bytes\n`);
}
