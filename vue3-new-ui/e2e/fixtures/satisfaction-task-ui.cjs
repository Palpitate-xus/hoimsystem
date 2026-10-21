const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const manifest=require('./satisfaction-tasks/manifest.json'),compressed=fs.readFileSync(path.join(__dirname,'satisfaction-tasks/actual-main.json.gz'));
if(crypto.createHash('sha256').update(compressed).digest('hex')!==manifest.gzip_sha256)throw new Error('Actual Main wire fixture gzip changed');
const raw=zlib.gunzipSync(compressed);
if(raw.length!==manifest.raw_bytes||crypto.createHash('sha256').update(raw).digest('hex')!==manifest.upstream_sha256)throw new Error('Actual Main wire fixture changed');
const packet=JSON.parse(raw),copy=v=>structuredClone(v),unwrap=r=>copy(r.json);
for(const response of packet.responses)if(crypto.createHash('sha256').update(response.raw_response_utf8).digest('hex')!==response.raw_response_sha256||JSON.stringify(JSON.parse(response.raw_response_utf8))!==JSON.stringify(response.json))throw new Error('An actual raw HTTP response lost its parsed or byte identity');
function profile(kind='chat'){
 const rows=packet.responses.filter(r=>r.test.endsWith(`[${kind}]`));
 if(!rows.length)throw new Error('Actual test profile missing');
 const source=rows.find(r=>r.method==='GET'&&r.path.includes('/satisfaction-sources/cases/'));
 const preview=rows.find(r=>r.path.endsWith('/operational-context'));
 const queued=rows.find(r=>r.method==='POST'&&r.path.endsWith('/ai/runs'));
 const id=queued.json.data.run_id,full=rows.find(r=>r.method==='GET'&&r.path.endsWith('/ai/runs/'+id)),trace=rows.find(r=>r.path.endsWith('/ai/admin/runs/'+id)),history=rows.find(r=>r.path.includes('/api/ai/runs?'));
 const adminHistory=rows.find(r=>r.path.includes('/api/ai/admin/runs?')),features=rows.find(r=>r.path.endsWith('/api/ai/features'));
 const options=rows.find(r=>r.path.endsWith('/satisfaction-sources/options')),doctors=rows.find(r=>r.path.includes('/satisfaction-sources/doctors?')),directory=rows.find(r=>r.path.includes('/satisfaction-sources/cases?')),query=new URL(directory.path).searchParams;
 const scope={scope_kind:query.get('scope_kind'),doctor_ids:query.getAll('doctor_ids').map(Number),date_from:query.get('date_from'),date_to:query.get('date_to')};
 return{source:unwrap(source),preview:unwrap(preview),queued:unwrap(queued),full:unwrap(full),trace:unwrap(trace),history:unwrap(history),adminHistory:unwrap(adminHistory),features:unwrap(features),options:unwrap(options),doctors:unwrap(doctors),directory:unwrap(directory),scope,input:copy(trace.json.data.frozen_request.payload.input),feature:copy(features.json.data.find(v=>v.key==='feedback_analysis'))};
}
async function setupSatisfactionTask(page,harness,{kind='chat',initial=true,component=false}={}){
 const value=profile(kind),calls=[],errors=[],replace=new Map(),denied=new Map(),gates=new Map();page.on('pageerror',error=>errors.push(String(error)));
 const hold=key=>{let release;const gate={started:false,promise:new Promise(resolve=>release=resolve),release:()=>release()};gates.set(key,gate);return gate;};
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),key=req.method()+' '+url.pathname;let body=null;if(req.postData())try{body=JSON.parse(req.postData());}catch{body=req.postData();}calls.push({key,body,query:Object.fromEntries(url.searchParams)});const gate=gates.get(key);if(gate){gate.started=true;await gate.promise;gates.delete(key);}if(denied.has(key)){await route.fulfill({status:denied.get(key),json:{detail:'合成当前权限已变化'}});return;}
 let response=replace.get(key);if(response===undefined){if(key==='GET /api/ai/satisfaction-sources/cases/'+value.input.satisfaction_case_id)response=value.source;else if(key==='GET /api/ai/satisfaction-sources/options')response=value.options;else if(key==='GET /api/ai/satisfaction-sources/doctors')response=value.doctors;else if(key==='GET /api/ai/satisfaction-sources/cases')response=value.directory;else if(key==='POST /api/ai/operational-context')response=value.preview;else if(key==='POST /api/ai/runs')response=value.queued;else if(key==='GET /api/ai/runs/'+value.full.data.run_id)response=value.full;else if(key==='GET /api/ai/runs')response=value.history;else if(key==='POST /api/ai/runs/'+value.full.data.run_id+'/feedback'||key==='POST /api/ai/runs/'+value.full.data.run_id+'/cancel')response={code:200,msg:'success'};}
 if(response===undefined){errors.push('Unknown API '+key);await route.fulfill({status:599,json:{detail:'No fabricated API fallback'}});return;}
 await route.fulfill({status:200,json:response});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__satisfactionTaskProbe);
 await page.evaluate(({value,initial,component})=>{const p=window.__satisfactionTaskProbe;p.store.commit('user/permissions',['admin']);if(component){p.scope.initialInput=initial?value.input:{};p.scope.feature=value.feature;}},{value,initial,component});
 return{value,calls,errors,replace,denied,hold,unhandled:harness.unhandled};
}
module.exports={profile,setupSatisfactionTask};
