const {fillNativeDetails}=require('./native-ui-details.cjs');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {startCodingProductionServer, styles} = require('./coding-production-entry.cjs');

// production_mock only. Main/JWT payloads come from one fresh synthetic V3 case.
// Common auth shell is synthetic. Task GET data is wrapped for transport without
// changing its fields; that wrapper is not claimed as a captured POST response.
const wrapped = data => ({code:200,msg:'success',data});
function loadProductionStates() {
  const filename = path.join(__dirname,'research-variable-task/production-states.json');
  const bytes = fs.readFileSync(filename);
  const fixtureHash=crypto.createHash('sha256').update(bytes).digest('hex');
  if(fixtureHash!=='4d26117432aa3a8b64207f7fdaa4f8b440373838309010626c99e62f8335f9fa')throw new Error('Production V3 fixture bytes changed; require an explicit new actual-case review');
  const value = JSON.parse(bytes.toString('utf8'));
  if (!value.management?.bootstrap || !value.source_metadata?.batches || !value.dictionary_parts ||
      !value.states?.succeeded_partial || typeof value.selection?.question!=='string' ||
      /[\r\n]/u.test(value.selection.question)) throw new Error('Require the complete same-case V3 production fixture; never splice V2');
  const batch = value.selection.research_variable_batch_id;
  if(Object.values(value.states).some(packet=>packet.detail.research_variable_batch_id!==batch))throw new Error('Cross-case task fixture');
  return {value,filename,sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
}
async function setupResearchVariableProduction(page,server,{role='admin'}={}) {
  const fixture=loadProductionStates(),F=fixture.value;
  const state={fixture:F,fixtureSha256:fixture.sha256,bootstrap:[],reads:[],writes:[],errors:[],unknown:[],external:[],cssErrors:[],assetErrors:[],getState:'succeeded_partial',denyCurrent:false,releases:{},completed:[]};
  page.__researchVariableProduction=state;
  page.on('pageerror',error=>state.errors.push(error.message));
  page.on('response',response=>{const u=new URL(response.url());if(u.origin===server.origin&&response.status()>=400&&!u.pathname.startsWith('/api/')){state.assetErrors.push({path:u.pathname,status:response.status()});if(u.pathname.endsWith('.css'))state.cssErrors.push(u.pathname);}});
  await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-variable-production-session'));
  await page.context().route('**/*',route=>{const request=route.request();if(new URL(request.url()).origin===server.origin)return route.continue();state.external.push({method:request.method(),url:request.url()});return route.abort('blockedbyclient');});
  await page.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method(),pathname=url.pathname,query=Object.fromEntries(url.searchParams),call={method,path:pathname,query};
    if(pathname==='/api/userInfo'&&method==='POST'){
      state.bootstrap.push({...call,body:request.postDataJSON(),classification:'platform-authentication-read'});
      return route.fulfill({json:{code:200,data:{username:'synthetic-variable-'+role,permissions:[role],avatar:''}}});
    }
    if(pathname==='/api/events/stream'&&method==='GET'){state.bootstrap.push({...call,classification:'platform-notification-bootstrap-read'});return route.fulfill({status:204,body:''});}
    if(method==='GET')state.reads.push(call);else state.writes.push({...call,body:request.postDataJSON()});
    const batch=F.selection.research_variable_batch_id,management=F.management;
    let reply;
    if(method==='GET'&&pathname==='/api/ai/features')reply=F.features;
    else if(method==='GET'&&pathname==='/api/ai/runs')reply=F.history;
    else if(method==='GET'&&pathname==='/api/ai/research-variables/batches/'+batch)reply=F.source_metadata.batches;
    else if(method==='GET'&&pathname.startsWith('/api/ai/research-variables/batches/'+batch+'/parts/'))reply=F.source_parts[pathname.split('/').at(-1)];
    else if(method==='POST'&&pathname==='/api/ai/research-variables/context')reply=F.preview;
    else if(method==='POST'&&pathname==='/api/ai/runs')reply=F.queued_receipt||wrapped(F.states.queued.detail);
    else if(method==='GET'&&pathname==='/api/ai/runs/'+F.states.succeeded_partial.detail.run_id){
      if(state.denyCurrent)return route.fulfill({status:403,json:{detail:'Synthetic current project or patient-purpose permission lost'}});
      reply=wrapped(F.states[state.getState].detail);
    }
    else if(method==='POST'&&pathname==='/api/ai/runs/'+F.states.succeeded_partial.detail.run_id+'/feedback')reply=F.feedback;
    else if(method==='GET'&&pathname.startsWith('/api/ai/runs/'+F.states.succeeded_partial.detail.run_id+'/research-variables/'))reply=F.states[state.getState].parts[pathname.split('/').at(-1)];
    else if(method==='GET'&&pathname==='/api/ai/research-cohort/scopes')reply=management.scope_directory;
    else if(method==='GET'&&pathname==='/api/ai/research-cohort/scopes/'+F.scope.data.scope_id)reply=F.scope;
    else if(method==='GET'&&pathname.startsWith('/api/ai/admin/'))reply=management.bootstrap[pathname.slice('/api/ai/admin/'.length)];
    else if(method==='GET'&&pathname==='/api/ai/research-variables/dictionaries')reply=management.source_directory.dictionaries;
    else if(method==='GET'&&pathname.startsWith('/api/ai/research-variables/dictionaries/')){
      const id=management.source_metadata.dictionaries.data.record_id;
      if(pathname==='/api/ai/research-variables/dictionaries/'+id)reply=management.source_metadata.dictionaries;
      else if(pathname.startsWith('/api/ai/research-variables/dictionaries/'+id+'/parts/'))reply=management.dictionary_parts[pathname.split('/').at(-1)];
    }
    if(!reply){state.unknown.push(call);return route.fulfill({status:599,json:{detail:'No explicitly reviewed production_mock endpoint'}});}
    const held=state.hold?.(method,pathname);
    if(held)await new Promise(resolve=>{state.releases[held]=resolve;});
    try{return await route.fulfill({json:reply});}finally{if(held)state.completed.push(held);}
  });
  return state;
}
async function openResearchVariableWorkbench(page,server){
  await page.goto(server.origin+'/#/ai/workbench?feature=research_extraction');
  const panel=page.getByTestId('research-variable-assistant');
  await panel.getByRole('button',{name:'选择变量来源',exact:true}).waitFor();
  return panel;
}
async function chooseResearchVariableBatch(page,panel,state){
  const {expect}=require('@playwright/test');
  await expect(panel.getByTestId('variable-inspect')).toBeDisabled();
  await expect(panel.getByTestId('variable-submit')).toBeDisabled();
  const before=state.reads.length,batch=state.fixture.selection.research_variable_batch_id;
  await fillNativeDetails(panel,'明确已授权批次引用',batch);
  await panel.getByRole('button',{name:'读取已知批次',exact:true}).click();
  await expect(panel.getByRole('button',{name:'清除本次选择',exact:true})).toBeVisible();
  expect(state.reads.slice(before).map(row=>row.path)).toEqual([
    '/api/ai/research-variables/batches/'+batch,
    '/api/ai/research-variables/batches/'+batch+'/parts/source',
    '/api/ai/research-variables/batches/'+batch+'/parts/snapshot',
    '/api/ai/research-variables/batches/'+batch,
  ]);
  await panel.getByTestId('variable-question').fill(state.fixture.selection.question);
  await panel.getByTestId('variable-inspect').click();
  await expect(panel.getByTestId('variable-preview')).toBeVisible();
}
async function generateResearchVariableTask(page,panel,state){
  const {expect}=require('@playwright/test');
  await chooseResearchVariableBatch(page,panel,state);
  await panel.getByTestId('variable-submit').click();
  await expect(panel.getByTestId('variable-feedback')).toBeVisible();
  await expect(panel.getByLabel('科研变量任务状态',{exact:true})).toHaveText('草稿已接收，未审核');
}
module.exports={loadProductionStates,startResearchVariableProductionServer:startCodingProductionServer,styles,setupResearchVariableProduction,openResearchVariableWorkbench,chooseResearchVariableBatch,generateResearchVariableTask};
