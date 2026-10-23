const {isDeepStrictEqual}=require('node:util');
const {expect}=require('@playwright/test'),{load}=require('./load-rca-evidence.cjs');
async function openRcaTask(page,harness,{kind='chat',state='succeeded',role='super_admin',scope={},hold=null,status=null,mutate=null,fallback=null,waitForView=true,shared=false,packetName=null}={}){
 let activeState=state;const failures=new Map();const packet=load(packetName||(shared?'shared-':'tasks-')+kind),reads=[],writes=[],feature=packet.features.data.find(v=>v.key==='incident_rca'),defaultInput=packet.states.succeeded.detail.data.rca_evidence_findings.input;
 await page.addInitScript(({scope,role})=>{window.__rcaEvidenceScope=scope;window.__rcaEvidenceRole=role;},{scope:{feature,initialInput:defaultInput,...scope},role});
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),path=u.pathname;let name=null,value=null;
  if(req.method()==='POST'){
   const body=req.postDataJSON();writes.push({path,body});
   if(path==='/api/ai/runs'){name='create';value=packet.states.queued.ack;}
   if(path==='/api/ai/rca-evidence/context'){name='preview';value=packet.preview;}
   for(const s of Object.values(packet.states))if(path===`/api/ai/runs/${s.detail.data.run_id}/cancel`&&s.cancel_ack){name='cancel';value=s.cancel_ack;break;}
  }else{
   reads.push(path+u.search);
   if(path==='/api/ai/features'){name='features';value=packet.features;}
   if(path===`/api/ai/admin/rca-evidence/cases/${packet.current_case.data.immutable.case_id}`){name='case';value=packet.current_case;}
   if(['/api/ai/runs','/api/ai/admin/runs'].includes(path)){name='history';value=packet.pending_directory&&activeState==='cancelled_pending'&&!path.includes('/admin/')?packet.pending_directory:packet.history[path.includes('/admin/')?'admin':'ordinary'];}
   let selected=packet.states[activeState];if(selected.detail.data.run_id!==path.split('/')[path.includes('/admin/')?5:4]){const candidate=Object.values(packet.states).find(s=>path.includes(s.detail.data.run_id));if(candidate)selected=candidate;}
   const id=selected.detail.data.run_id,admin=path.startsWith('/api/ai/admin/'),root=`/api/ai/${admin?'admin/':''}runs/${id}`;
   if(path===root){name='detail';value=admin?selected.trace:selected.detail;}
   for(const part of ['source','case','result','receipt'])if(path===root+'/rca-evidence/'+part){name='part-'+part;value=selected.parts[part];}
  }
  if(!name&&fallback)return fallback({route,request:req,path,url:u,packet,reads,writes});if(!name)return route.fulfill({status:501,contentType:'application/json',body:JSON.stringify({detail:'Unmatched RCA Task route '+req.method()+' '+path})});
  if(hold)await hold({name,request:req,route});if(failures.has(name)||status?.name===name)return route.fulfill({status:failures.get(name)||status.code,contentType:'application/json',body:JSON.stringify({detail:'synthetic current denial'})});
  let body=Object.values(packet.raw_http_responses).find(p=>p.path.split('?')[0]===path&&isDeepStrictEqual(JSON.parse(p.raw_utf8),value))?.raw_utf8||JSON.stringify(value);if(mutate)body=await mutate(name,body);return route.fulfill({contentType:'application/json',body});
 });
 await page.goto(harness.origin);if(waitForView)await expect(page.getByRole('region',{name:'事件RCA专属调查草稿助手',exact:true})).toBeVisible();return {packet,reads,writes,setState(value){activeState=value;},setFailure(name,code){if(code===null)failures.delete(name);else failures.set(name,code);}};
}
module.exports={openRcaTask};
