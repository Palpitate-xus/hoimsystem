const actual=require('./supply-sources/panel.json');
const clone=v=>JSON.parse(JSON.stringify(v));
function metadata(v){return Object.fromEntries(Object.entries(v).filter(([k])=>!['payload','parent_binding','review_basis_note','revoke_reason'].includes(k)));}
async function openSupplySources(page,harness,config={}){
 const state={reads:[],writes:[],errors:[],unexpected:[],releases:{},completed:[],role:'pharmacist',selected:null,...config};
 page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method(),body=method==='POST'?r.postDataJSON():null;(method==='GET'?state.reads:state.writes).push({method,path,params:Object.fromEntries(u.searchParams),body});const held=state.hold?.(method,path,u);if(held)await new Promise(resolve=>state.releases[held]=resolve);const custom=await state.respond?.(r,path,state);if(custom!==undefined){await route.fulfill(custom);if(held)state.completed.push(held);return;}
  let data;
  const role=state.role==='super_admin'?'super':state.role;
  if(path==='/api/ai/supply-sources/options'){const kind=u.searchParams.get('item_kind');data=kind?(u.searchParams.has('item_id')?actual.catalogs_by_role[role]?.[kind]:actual.catalog_full[kind]):actual.options_by_role[role];}
  else if(path==='/api/ai/admin/supply-sources')data=state.list||actual.governance_draft_list;
  else if(path.startsWith('/api/ai/admin/supply-sources/'))data=state.detail||actual.governance_draft_detail;
  else {const m=/^\/api\/ai\/supply-sources\/(units|daily)(?:\/([^/]+))?(?:\/(review|revoke))?$/.exec(path);if(m){const[,group,id,action]=m,kind=group==='units'?'unit':'daily';if(method==='GET'){if(id)data=state.detail||(kind==='unit'?actual.units.pharmaceutical.published:actual.daily.gross_fulfilled_issue_quantity.published);else if(group==='units')data=u.searchParams.get('page_size')==='100'?actual.unit_candidates:actual.unit_list;else data=state.list||actual.daily_list;}else if(!id)data=state.created||(kind==='unit'?actual.units.pharmaceutical.draft:actual.daily.gross_fulfilled_issue_quantity.draft);else if(action==='review')data=body.decision==='reject'?actual.rejection.super_response:actual.daily.gross_fulfilled_issue_quantity.published;else data=state.revoked||actual.revocation.ordinary;}}
  if(data===undefined){state.unexpected.push({method,path});await route.fulfill({status:404,json:{code:404,msg:'unexpected synthetic source route'}});}else await route.fulfill({status:200,json:{code:200,data:clone(data)}});if(held)state.completed.push(held);
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplySourceProbe);
 await page.evaluate(config=>{const p=window.__supplySourceProbe;p.store.commit('user/permissions',[config.role]);Object.assign(p.scope,{governance:!!config.governance,itemKind:config.itemKind??null,itemId:config.itemId??null,mode:'sources'});},{role:state.role,governance:state.governance,itemKind:state.itemKind,itemId:state.itemId});
 return state;
}
async function select(page,label,option){const input=page.getByRole('combobox',{name:label,exact:true});await input.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")][1]').click();const id=await input.getAttribute('aria-controls');await page.locator('[id="'+id+'"]').getByRole('option',{name:option,exact:typeof option==='string'}).click();}
module.exports={actual,metadata,openSupplySources,select};
