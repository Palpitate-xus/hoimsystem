const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const [source,...flags]=process.argv.slice(2);
if(!source||flags.some(v=>v!=='--check'))throw new Error('Provide the actual JWT metadata receipt JSON and optional --check');
const raw=fs.readFileSync(source),value=JSON.parse(raw);
if(value.code!==200||value.data?.capabilities?.schema_version!=='14'||value.data.capabilities.feature_key!=='inventory_optimization'||value.data.compatible!==false)throw new Error('Expected an actual model-mismatch metadata check receipt');
const target=path.resolve(__dirname,'../e2e/fixtures/inventory-provider/actual.json');
const fixture={scope:'Actual synthetic JWT administrator metadata route and native ASGI capabilities; browser tests mock these bytes. No runtime inference or operational validation.',source_artifact:{name:path.basename(source),sha256:crypto.createHash('sha256').update(raw).digest('hex')},data:value.data};
const text=JSON.stringify(fixture)+'\n';
if(flags.includes('--check')){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Actual metadata fixture differs');}else{fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,text);}
process.stdout.write(`${flags.includes('--check')?'Verified':'Extracted'} actual inventory metadata fixture (${Buffer.byteLength(text)} bytes); browser API remains isolated.\n`);
