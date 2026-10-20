const {expect}=require('@playwright/test');
const {P,C,R,S,O,F,metadata,choose,fill,fillBedSource}=require('./bed-series-ui.cjs');
async function setupBedInput(page,harness,config={}){
 const state={role:'admin',fixture:P,rows:null,writes:[],reads:[],errors:[],releases:{},completed:[],...config};state.rows??=[state.fixture.ordinary_published];page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),path=u.pathname,method=req.method();let data;
  if(method==='GET'){
   state.reads.push({path,query:Object.fromEntries(u.searchParams)});
   if(path.endsWith('/bed-sources/options'))data=u.searchParams.has('department_id')?O.department_source_options:O.source_options;
   else if(path.includes('/bed-sources')){const record=state.fixture.ordinary_published.snapshot.facts.find(r=>r.source.source_record_id===path.split('/').at(-1));data=record?.source||{items:[],total:0,page:1,page_size:20};}
   else if(path.includes('/bed-series')){if(/[a-f0-9-]{36}$/.test(path))data=state.detail||state.rows.find(r=>path.endsWith(r.series_id));else{const rows=state.rows.filter(r=>(!u.searchParams.has('department_id')||r.department_id===Number(u.searchParams.get('department_id')))&&(!u.searchParams.has('ward_id')||r.ward_id===Number(u.searchParams.get('ward_id'))));data={items:rows.map(metadata),total:rows.length,page:Number(u.searchParams.get('page')||1),page_size:20};}}
  }else{const body=req.postDataJSON();state.writes.push({path,body});if(path.includes('/bed-sources/'))data=F.kinds.census.draft;else if(path.endsWith('/revoke')){data=state.role==='super_admin'?P.super_revoked:P.ordinary_revoked;state.rows=[data];}}
  if(!data){state.errors.push(`Unhandled isolated ${method} ${path}`);await route.fulfill({status:500,json:{code:500,msg:'Synthetic route missing'}});return;}
  const failure=state.failure?.(method,path,req),held=state.hold?.(method,path,req);if(held)await new Promise(resolve=>state.releases[held]=resolve);
  try{await route.fulfill(failure?{status:failure,json:{code:failure,msg:'Synthetic current scope unavailable'}}:{json:{code:200,data:state.mutate?state.mutate(data,path,method)??data:data}});}finally{if(held)state.completed.push(held);}
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__bedInputProbe);await page.evaluate(({role,departmentId,wardId,initialReferences,echo})=>{const p=window.__bedInputProbe;p.store.commit('user/permissions',[role]);p.scope.departmentId=departmentId??null;p.scope.wardId=wardId??null;p.scope.initialReferences=initialReferences??null;p.scope.echo=!!echo;p.scope.ready=true;},{role:state.role,departmentId:state.departmentId,wardId:state.wardId,initialReferences:state.initialReferences,echo:state.echo});return state;
}
async function scope(page){await choose(page,'床位预测科室','内科 · #1');await choose(page,'床位预测病区','合成病区 · #1');await expect(page.getByRole('button',{name:'核对完整床位序列',exact:true}).first()).toBeVisible();}
async function horizon(page,days=14){await choose(page,'床位预测期限',`完整${days}个业务日`);}
async function select(page){await page.getByRole('button',{name:'核对完整床位序列',exact:true}).first().click();const dialog=page.getByRole('dialog',{name:'完整床位序列冻结核对与治理',exact:true});await dialog.getByRole('button',{name:'选择此已发布床位序列',exact:true}).click();return dialog;}
async function selection(page){return page.evaluate(()=>window.__bedInputProbe.events.filter(e=>e.type==='selection').at(-1)?.value??null);}
async function bound(page,id){await expect(page.getByLabel('已绑定床位预测序列',{exact:true})).toContainText(id);}
module.exports={P,C,R,S,O,F,setupBedInput,scope,horizon,select,selection,bound,choose,fill,fillBedSource};
