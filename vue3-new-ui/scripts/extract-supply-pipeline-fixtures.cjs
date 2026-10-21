// Lossless storage factoring of actual synthetic SQLite/JWT/native-ASGI packets.
// This script does not create a run, change a result, or claim browser HTTP.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const input=process.argv.find(v=>v.startsWith('--pipeline='))?.slice('--pipeline='.length);
if(!input)throw new Error('Pass --pipeline=/tmp/hoim-supply-actual-complete-pipeline-second-packets.json');
const bytes=fs.readFileSync(input),sha=v=>crypto.createHash('sha256').update(v).digest('hex'),canonical=v=>v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?'['+v.map(canonical).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}',expected='6021567c5c66880c512aafc39613544e06cc70a77a57da10feeed65adbb3186e';
if(sha(bytes)!==expected)throw new Error('Original actual development packet artifact SHA differs');
const original=JSON.parse(bytes),common={source:original.horizons['14'].detail.data.supply_findings.supply_source,series:original.horizons['14'].detail.data.supply_findings.supply_series,results:Object.fromEntries(['7','14'].map(h=>[h,original.horizons[h].detail.data.result]))},commonText={source:canonical(common.source),series:canonical(common.series)},digests={},packets={};
function pack(v,h,key=''){
 if(key==='supply_source'||key==='supply_series'){const name=key==='supply_source'?'source':'series';if(canonical(v)!==commonText[name])throw new Error('Source/series differs: '+h+':'+key);return{$fixture_ref:name};}
 if(key==='result'&&canonical(v)===canonical(common.results[h]))return{$fixture_ref:'result:'+h};
 if(Array.isArray(v))return v.map(x=>pack(x,h));
 if(v!==null&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,pack(x,h,k)]));
 return v;
}
function unpack(v){if(v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===1&&Object.hasOwn(v,'$fixture_ref')){const ref=v.$fixture_ref;return ref.startsWith('result:')?common.results[ref.slice(7)]:common[ref];}if(Array.isArray(v))return v.map(unpack);if(v!==null&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,unpack(x)]));return v;}
for(const h of ['7','14']){packets[h]={};digests[h]={};for(const name of ['preview','queued','running','detail','audit']){const value=original.horizons[h][name],packed=pack(value,h),text=canonical(value);if(canonical(unpack(packed))!==text)throw new Error('Lossless reconstruction differs '+h+':'+name);packets[h][name]=packed;digests[h][name]={canonical_bytes:Buffer.byteLength(text),canonical_sha256:sha(text)};}}
const output=canonical({scope:'Losslessly factored actual synthetic SQLite/JWT/native-ASGI development packets; browser tests mock API, not native HTTP',source_artifact:{name:path.basename(input),bytes:bytes.length,sha256:expected},common,packets,digests})+'\n',file=path.resolve(__dirname,'../e2e/fixtures/supply-native/pipeline-development.json');
if(process.argv.includes('--check')){if(fs.readFileSync(file,'utf8')!==output)throw new Error('Pipeline fixture differs from actual source artifact');}else fs.writeFileSync(file,output);
process.stdout.write('Ten exact full DTO reconstructions verified; factored fixture '+Buffer.byteLength(output)+' bytes; original '+bytes.length+' bytes\n');

const unknown=process.argv.find(v=>v.startsWith('--unknown='))?.slice('--unknown='.length);if(unknown){const value=fs.readFileSync(unknown),expected='a8a3942aa0f4c1f85277f1388b22af778bae0c7eb146befb45c527ffe19694fb';if(sha(value)!==expected)throw new Error('Actual unknown pipeline SHA differs');const file=path.resolve(__dirname,'../e2e/fixtures/supply-native/pipeline-unknown.json');if(process.argv.includes('--check')){if(!fs.readFileSync(file).equals(value))throw new Error('Actual unknown pipeline differs');}else fs.writeFileSync(file,value);process.stdout.write('Exact actual unknown worker packet '+value.length+' bytes '+expected+'\n');}

const states=process.argv.find(v=>v.startsWith('--states='))?.slice('--states='.length);if(states){const value=fs.readFileSync(states),expected='c8410761890c3ed5e229b18a9e359a13c282cdf373162621e466a8fc87b658bd';if(sha(value)!==expected)throw new Error('Actual five states SHA differs');const file=path.resolve(__dirname,'../e2e/fixtures/supply-native/pipeline-statuses.json');if(process.argv.includes('--check')){if(!fs.readFileSync(file).equals(value))throw new Error('Actual five states differs');}else fs.writeFileSync(file,value);process.stdout.write('Exact actual five states '+value.length+' bytes '+expected+'\n');}
