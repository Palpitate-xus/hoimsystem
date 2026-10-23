const{expect}=require('@playwright/test');
const{loadResearchVariableSource}=require('./research-variable-source-ui.cjs');
const F=loadResearchVariableSource();
// Every full part/ACK is an unchanged actual HTTP response. Draft-phase directory
// wrappers below are explicitly derived from those actual bodyless headers; the
// exporter captured published/terminal directories, not every intermediate page.
async function openResearchVariableSource(page,harness,{mode='sources',roles=['admin'],phase='published',batchPhase='published',auditOnly=false,rejected=false,initialReferences={},hold=null,deny=false,corrupt=false,token='synthetic-variable-session',username='synthetic-variable-author'}={}){
 const state={phase,batchPhase,hold,release:null,seen:[],unexpected:[],errors:[],posts:[]};page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());
 await page.addInitScript(v=>{window.__researchVariableSourceInitial=v;},{mode,roles,auditOnly,initialReferences,token,username});
 await page.route('**/api/**',async route=>{const q=route.request(),u=new URL(q.url()),path=u.pathname,request={method:q.method(),path,query:Object.fromEntries(u.searchParams),body:q.postData()?q.postDataJSON():null};state.seen.push(request);let stage,derived;
  if(path==='/api/ai/research-cohort/scopes')stage='scope.admin_candidates';
  else if(path==='/api/ai/research-cohort/scopes/'+F.source.scope_reference.scope_id)stage='scope.super_current';
  else if(path==='/api/ai/research-variables/batches/preview'){expect(request.body).toEqual(F.record('batch.preview').request_json);stage='batch.preview';}
  else if(q.method()==='POST'){
   if(path==='/api/ai/research-variables/dictionaries'){stage='dictionary.create';state.phase='draft';}
   else if(path.endsWith('/definition-review')){stage='dictionary.definition_review';state.phase='definition_reviewed';}
   else if(path.includes('/dictionaries/')&&path.endsWith('/review')){stage='dictionary.publish';state.phase='published';}
   else if(path.includes('/dictionaries/')&&path.endsWith('/revoke')){stage='dictionary.revoke';state.phase='revoked';}
   else if(path==='/api/ai/research-variables/batches'){stage='batch.create';state.batchPhase='draft';}
   else if(path.includes('/batches/')&&path.endsWith('/review')){stage='batch.publish';state.batchPhase='published';}
   else if(path.includes('/batches/')&&path.endsWith('/revoke')){stage='batch.revoke';state.batchPhase='revoked';}
   if(stage){expect(request.body).toEqual(F.record(stage).request_json);state.posts.push(request);}
  }else{
   const technical=path.includes('/technical/'),recordKind=path.includes('/dictionaries')?'dictionary':path.includes('/batches')?'batch':null,name=recordKind==='dictionary'?'dictionaries':'batches',stem=recordKind==='dictionary'?(rejected?'rejected_dictionary.rejected':'dictionary.'+state.phase):'batch.'+state.batchPhase;
   if(recordKind&&path.endsWith('/'+name)){
    if(!technical)expect(request.query).toEqual({...F.source.scope_reference,page:'1',size:'20'});else expect(request.query).toEqual({page:'1',size:'20'});
    const actual=F.data(technical?'technical.'+name+'.published':'directory.'+name+'.current');derived=structuredClone(actual);const metadata=F.data(stem+'.metadata');if(technical)metadata.technical_only=true;derived.items=[metadata];derived.total=1;
   }else if(recordKind){const part=path.includes('/parts/')?path.split('/').at(-1):'metadata';stage=stem+'.'+part;if(technical){derived=structuredClone(F.data(stage));derived.technical_only=true;stage=null;}}
  }
  if(state.hold&&((state.hold==='preview'&&stage==='batch.preview')||(state.hold==='source'&&stage?.endsWith('.source'))||(state.hold==='definition'&&stage?.endsWith('.definition')))){await new Promise(resolve=>{state.release=resolve;});state.hold=null;}
  if(deny&&path.startsWith('/api/ai/research-variables/')&&!path.includes('/technical/'))return route.fulfill({status:403,body:F.record('withdrawn.admin_user.batches.metadata').body,headers:{'Content-Type':'application/json'}});
  if(corrupt&&stage?.endsWith('.snapshot')){derived=F.data(stage);derived.value.snapshot.capture.records.pop();stage=null;}
  if(derived)return route.fulfill({json:{code:200,msg:'success',data:derived}});
  if(!stage){state.unexpected.push(request);return route.fulfill({status:599,json:{detail:'Unexpected isolated Source route'}});}
  const row=F.record(stage);return route.fulfill({status:row.status,body:row.body,headers:row.response_headers});
 });await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchVariableSourceProbe);return state;
}
async function chooseProject(page){await page.getByRole('button',{name:'读取明确项目目录',exact:true}).click();await page.getByRole('button',{name:'核对并明确本项目',exact:true}).click();await expect(page.getByText(/明确项目 .*；用途已记录/)).toBeVisible();}
async function directory(page,kind='dictionary'){if(kind==='batch')await page.getByText('完整变量批次',{exact:true}).click();await page.getByRole('button',{name:'刷新变量来源目录',exact:true}).click();await page.getByRole('button',{name:'按当前授权读取完整两件',exact:true}).click();await expect(page.getByRole('dialog',{name:'变量来源完整核对',exact:true})).toBeVisible();}
async function select(page,label,value){const input=page.getByRole('combobox',{name:label,exact:true});await input.press('ArrowDown');await page.getByRole('option',{name:value,exact:true}).click();}
function assertClean(state){expect(state.errors).toEqual([]);expect(state.unexpected).toEqual([]);}
module.exports={F,openResearchVariableSource,chooseProject,directory,select,assertClean};
