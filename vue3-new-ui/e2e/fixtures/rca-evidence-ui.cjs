const {isDeepStrictEqual}=require('node:util');
const {expect}=require('@playwright/test'),{load}=require('./load-rca-evidence.cjs');
async function openRcaSource(page,harness,{scope={},role='super_admin',hold=null,status=null,mutate=null}={}){
 const fixture=load('source'),reads=[],writes=[];
 await page.addInitScript(({scope,role})=>{window.__rcaEvidenceScope=scope;window.__rcaEvidenceRole=role;},{scope:{eventId:fixture.event_id,expectedPatientId:fixture.patient_id,...scope},role});
 const base='/api/ai/admin/rca-evidence';
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;let name=null;
  if(req.method()==='GET'){
   reads.push(path+url.search);
   if(path===base+'/options')name='options';
   if(path==='/api/user/getList')name='super_directory';
   for(const kind of ['grants','originals','cases'])if(path===`${base}/events/${fixture.event_id}/directory/${kind}`)name=kind+'_directory';
   if(path===`${base}/events/${fixture.event_id}/capture`)name='capture';
   if(path===`${base}/events/${fixture.event_id}/legacy-witness`)name='legacy_event';
   for(const key of ['manual_review','draft_create','rejected_review','revoked_revoke','timeline_review','published_case_review','rejected_case_revoke','draft_revoked_case_revoke','event_grant','patient_grant']){
    const data=fixture.packets[key].response.data,s=data.identity||data.immutable,kind=s.grant_id?'grants':s.original_id?'originals':'cases',id=s.grant_id||s.original_id||s.case_id;if(path===`${base}/${kind}/${id}`)name=key;
   }
   if(path===`${base}/cases/${fixture.packets.published_case_review.response.data.immutable.case_id}/public-source`)name='public_source';
  }else{
   const body=req.postDataJSON();writes.push({path,body});
   for(const [key,b]of Object.entries(fixture.requests)){const p=fixture.packets[key];if(!name&&p.method==='POST'&&p.path.split('?')[0]===path&&isDeepStrictEqual(b,body))name=key;}
  }
  if(!name)return route.fulfill({status:501,contentType:'application/json',body:JSON.stringify({detail:'Unmatched actual RCA route '+req.method()+' '+path})});
  if(hold)await hold({name,route,request:req});
  if(status?.name===name)return route.fulfill({status:status.code,contentType:'application/json',body:JSON.stringify({detail:'synthetic denial'})});
  let body=fixture.packets[name].raw_utf8;if(mutate)body=await mutate(name,body);
  await route.fulfill({contentType:'application/json',body});
 });
 await page.goto(harness.origin);await expect(page.getByRole('region',{name:'事件RCA来源治理',exact:true})).toBeVisible();
 return {fixture,reads,writes};
}
async function choose(page,label,value){const select=page.getByRole('combobox',{name:label,exact:true});await select.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")][1]').click();const id=await select.getAttribute('aria-controls');await page.locator('[id="'+id+'"]').getByRole('option',{name:value,exact:true}).click();}
module.exports={openRcaSource,choose};
