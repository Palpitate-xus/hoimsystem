// One whole real Main/JWT lifecycle case. No state/flags/hashes are fabricated.
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const sha=v=>crypto.createHash('sha256').update(v).digest('hex');
function loadResearchVariableSource(){
 const p=JSON.parse(fs.readFileSync(path.join(__dirname,'research-variable-source/actual-lifecycle.packed.json'),'utf8')),raw=zlib.gunzipSync(Buffer.from(p.gzip_base64,'base64'));
 if(p.schema_version!=='research_variable_actual_source_http_gzip_v1'||raw.length!==p.original_bytes||sha(raw)!==p.original_sha256)throw Error('Actual Source lifecycle fixture differs');
 const source=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));if(source.records.length!==73||Object.keys(source.stage_index).length!==73)throw Error('Unexpected Source lifecycle count');
 for(const row of source.records){const bytes=Buffer.from(row.body,'utf8');if(bytes.length!==row.body_bytes||sha(bytes)!==row.body_sha256||JSON.stringify(JSON.parse(row.body))!==JSON.stringify(row.json))throw Error('Original actual response bytes differ');}
 const record=stage=>{const i=source.stage_index[stage],row=source.records[i];if(!Number.isInteger(i)||row?.stage!==stage)throw Error('Unknown actual stage '+stage);return row;};
 const data=stage=>{const row=record(stage),v=JSON.parse(row.body);return Object.hasOwn(v,'data')?v.data:v;};
 const pair=stage=>stage.startsWith('batch.')?{source:data(stage+'.source'),snapshot:data(stage+'.snapshot')}:{definition:data(stage+'.definition'),scope:data(stage+'.scope')};
 return{source,record,data,pair,packed:p};
}
async function installResearchVariableSourceResponses(page,{choose}={}){
 const actual=loadResearchVariableSource(),state={actual,seen:[],unknown:[],errors:[],release:null};page.on('pageerror',e=>state.errors.push(e.message));
 await page.route('**/api/**',async route=>{const q=route.request(),url=new URL(q.url()),request={method:q.method(),path:url.pathname,query:Object.fromEntries(url.searchParams),body:q.postData()?q.postDataJSON():null,headers:q.headers()};state.seen.push(request);const selected=choose?.(request,state),row=typeof selected==='string'?actual.record(selected):selected;
  if(!row){state.unknown.push(request);return route.fulfill({status:599,json:{detail:'No matching same-case Source response selected'}});}
  if(row.method!==request.method||new URL(row.path,'http://actual.invalid').pathname!==request.path)throw Error('Selected actual response belongs to another endpoint');
  return route.fulfill({status:row.status,body:row.body,headers:row.response_headers});
 });return state;
}
module.exports={loadResearchVariableSource,installResearchVariableSourceResponses};
