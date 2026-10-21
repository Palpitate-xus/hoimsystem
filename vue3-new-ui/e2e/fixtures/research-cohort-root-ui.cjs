const{expect}=require('@playwright/test'),{load,http}=require('./load-research-cohort-shared.cjs');
async function openResearchRoot(page,harness,{kind='chat',mode='history',roles=['super_admin'],hold=null,deny=null,mutatePart=null,mutateTrace=null,mutateDirectory=null}={}){
 const packet=load(kind),state={packet,errors:[],unexpected:[],calls:[],release:null,hold,deny,reads:0};page.__researchRootState=state;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());
 await page.addInitScript(v=>{window.__researchRootInitial=v;},{mode,roles,features:[]});
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),path=u.pathname,id=packet.metadata_super.run_id,part=path.split('/parts/')[1];state.calls.push({method:req.method(),path,query:Object.fromEntries(u.searchParams)});let body,wire,status=200;const use=v=>{wire=v.raw_utf8;status=v.status;return JSON.parse(wire);};
  if(path==='/api/ai/admin/runs'){body=use(http(packet,'/api/ai/admin/runs?feature_key=research_cohort'));if(mutateDirectory){mutateDirectory(body.data);wire=null;}}
  else if(path==='/api/ai/admin/runs/'+id){if(['trace','withdrawn'].includes(state.deny)){const v=http(packet,path,{status:403});status=403;body=use(v);}else{body=use(http(packet,path));if(mutateTrace){mutateTrace(body.data);wire=null;}}}
  else if(path==='/api/ai/research-cohort/tasks/'+id||part&&path.startsWith('/api/ai/research-cohort/tasks/'+id+'/parts/')){const q=path+'?audit_only=true';if(state.deny===part||state.deny==='metadata'||state.deny==='withdrawn'){const v=http(packet,q,{status:part?403:200,last:true});status=v.status;body=use(v);}else{body=use(http(packet,q));if(part&&mutatePart){mutatePart(part,body.data);wire=null;}}}
  else{state.unexpected.push({method:req.method(),path});return route.fulfill({status:599,json:{detail:'Unexpected shared research route'}});}
  if(state.hold&&(state.hold===part||state.hold==='trace'&&path==='/api/ai/admin/runs/'+id||state.hold==='metadata'&&path==='/api/ai/research-cohort/tasks/'+id)){state.hold=null;await new Promise(resolve=>state.release=resolve);}
  if(state.hold==='proof'&&part==='result'){state.hold=null;await page.evaluate(()=>{const s=crypto.subtle,original=s.digest.bind(s);let held=false;s.digest=function(...args){if(held)return original(...args);held=true;return new Promise(resolve=>{window.__releaseResearchRootProof=async()=>{s.digest=original;resolve(await original(...args));};});};});}
  await route.fulfill({status,contentType:'application/json',body:wire??JSON.stringify(body)});
 });await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchRootProbe);return state;
}
async function inspect(page){await page.getByRole('button',{name:'执行溯源',exact:true}).first().click();}
async function accepted(page){await expect(page.getByText('当前完整Source、私有Case、原始TEXT和冻结Prompt版本已核对；技术审核不代表研究入组、伦理批准、因果或匿名认证。',{exact:true})).toBeVisible({timeout:20000});}
module.exports={openResearchRoot,inspect,accepted};
