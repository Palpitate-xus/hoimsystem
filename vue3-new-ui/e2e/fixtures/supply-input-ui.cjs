const {expect}=require('@playwright/test');
const F=require('./supply-series/input.json');
async function openSupplyInput(page,harness,config={}){
 const state={role:'admin',business:true,fixture:F,reads:[],errors:[],completed:[],releases:{},...config},f=state.fixture;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname,query=Object.fromEntries(url.searchParams);state.reads.push({path,query});let data;
  if(path.endsWith('/supply-sources/options'))data=state.catalog?.(query)||f.catalogs[query.item_id?'selected':query.item_kind||'all'];
  else if(path.endsWith('/supply-series'))data=state.directory||f.directory;
  else data=state.detail||f.published;
  const failed=state.failure?.(path,query),hold=state.hold?.(path,query);data=structuredClone(data);if(hold)await new Promise(resolve=>state.releases[hold]=resolve);
  await route.fulfill(failed?{status:failed,json:{code:failed,msg:'isolated current source access changed'}}:{json:{code:200,data}});if(hold)state.completed.push(hold);
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplySeriesProbe);
 await page.evaluate(({role,business,refs,kind,id})=>{const p=window.__supplySeriesProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{itemKind:business?kind:null,itemId:business?id:null,initialReferences:refs??null,ready:true});},{role:state.role,business:state.business,refs:state.initialReferences,kind:f.published.item_kind,id:f.published.item_id});return state;
}
async function selectMenu(page,label){await page.getByRole('combobox',{name:label,exact:true}).locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")][1]').click();}
async function horizon(page,days){await selectMenu(page,'物资预测期限');await page.getByRole('option',{name:`完整${days}个业务日`,exact:true}).click();}
async function selectSeries(page){await page.getByRole('row').filter({hasText:F.published.series_id}).getByRole('button',{name:'核对完整物资序列',exact:true}).click();await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toBeVisible();await page.getByRole('button',{name:'选择此完整受审物资序列',exact:true}).click();}
async function bound(page){await expect(page.getByLabel('已绑定物资预测序列',{exact:true})).toBeVisible();}
async function cleared(page){await expect(page.getByLabel('已绑定物资预测序列',{exact:true})).toHaveCount(0);expect(await page.evaluate(()=>window.__supplySeriesProbe.panel.$.setupState.chosen)).toBeNull();}
module.exports={F,openSupplyInput,selectMenu,horizon,selectSeries,bound,cleared};
