const{expect}=require('@playwright/test');
const{loadOperationsPackets}=require('./operations-support-packets.cjs');
const packet=loadOperationsPackets('source-lifecycle'),BASE='/api/ai/operations-support';
function exact(stage,method,path){const rows=packet.rows.filter(x=>x.stage===stage&&x.method===method&&x.path===BASE+path);if(rows.length!==1)throw new Error('Actual stage response missing/ambiguous: '+[stage,method,path]);return rows[0];}
const original=packet.data(packet.rows.find(x=>x.stage==='original_flow'&&x.method==='POST'&&x.path===BASE+'/originals')),release=packet.data(packet.rows.find(x=>x.stage==='original_flow'&&x.method==='POST'&&x.path===BASE+'/releases')),caseRow=packet.data(packet.rows.find(x=>x.stage==='original_flow'&&x.method==='POST'&&x.path===BASE+'/cases'));
const request=(path)=>JSON.parse(packet.rows.find(x=>x.method==='POST'&&x.path===BASE+path).request_body);
function originalFlow(method,path){if(method==='GET'&&path==='/releases'){const rows=packet.rows.filter(x=>x.stage==='original_flow'&&x.method===method&&x.path===BASE+path);const row=rows.find(x=>packet.data(x).items.every(v=>!Object.hasOwn(v,'created_by')));if(!row)throw new Error('Missing actual ordinary release directory');return row;}return exact('original_flow',method,path);}
async function installOperationsSources(page,{published=true,role='admin'}={}){
 const state={phase:published?'published':'original',role,seen:[],unknown:[],hold:null,deny:false,caseRevoked:false};
 await page.route('**/api/**',async route=>{
  const r=route.request(),u=new URL(r.url()),path=u.pathname.slice(BASE.length),method=r.method();state.seen.push({path:u.pathname,method,body:r.postDataJSON(),search:u.search});
  if(state.hold?.match({path,method})){const hold=state.hold;await hold.promise;}
  if(state.deny)return route.fulfill({status:403,contentType:'application/json',body:'{"detail":"current authorization lost"}'});
  let row;
  if(method==='POST'){
   row=originalFlow(method,path);expect(r.postDataJSON()).toEqual(JSON.parse(row.request_body));
   if(path==='/originals')state.phase='original';else if(path==='/releases')state.phase='draft';else if(path.endsWith('/review'))state.phase='published';else if(path===`/cases/${caseRow.case_id}/revoke`)state.caseRevoked=true;
  }else if(method==='GET'){
   if(path==='/originals')row=exact('original_current','GET',path);
   else if(path==='/releases')row=state.role==='super_admin'?exact(state.phase==='draft'?'draft_current':'reviewed_current','GET',path):originalFlow('GET',path);
   else if(path==='/cases')row=exact('case_current','GET',path);
   else if(path===`/originals/${original.original_id}`)row=exact('original_current','GET',path);
   else if(path===`/releases/${release.release_id}`||path===`/releases/${release.release_id}/draft`)row=exact(state.phase==='draft'?'draft_current':'reviewed_current','GET',path);
   else if(path===`/cases/${caseRow.case_id}`)row=exact(state.caseRevoked?'revoked_current':'case_current','GET',path);
   else if(path===`/cases/${caseRow.case_id}/parts/source`)row=exact('case_current','GET',path);
   else row=originalFlow('GET',path);
  }
  if(!row){state.unknown.push({method,path});return route.fulfill({status:599,body:'unknown isolated API'});}
  await route.fulfill({status:row.status,contentType:'application/json',body:row.body,headers:row.parts_wire?{'X-AI-Parts-Wire':row.parts_wire}:{}});
 });return state;
}
async function openOperations(page,harness,{role='admin',governance=false,username='synthetic-operations'}={}){
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__operationsProbe)).toBe(true);
 await page.evaluate(({role,governance,username})=>{const p=window.__operationsProbe;p.store.commit('user/permissions',[role]);p.store.commit('user/username',username);p.scope.governance=governance;},{role,governance,username});
}
function holdOperation(state,match){let resolve;state.hold={match,promise:new Promise(r=>resolve=r)};return()=>{state.hold=null;resolve();};}
async function directory(page,name){await page.getByRole('button',{name,exact:true}).click();await page.getByRole('button',{name:'读取当前目录',exact:true}).click();await expect(page.locator('tbody tr')).toHaveCount(1);}
async function inspectFirst(page){await page.getByRole('button',{name:'核对本条完整来源',exact:true}).first().click();await expect(page.getByRole('dialog',{name:'完整受审运维来源',exact:true})).toBeVisible();}
module.exports={installOperationsSources,openOperations,holdOperation,directory,inspectFirst,actualOperationsSource:{packet,original,release,caseRow,request}};
