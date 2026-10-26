// production_mock: canonical dist only. AI replies are the unchanged same-Case
// V5 mounted Main/JWT packets; only the platform login/SSE shell is synthetic.
const {expect}=require('@playwright/test');
const {startSupplyProductionServer:startOperationsProductionServer}=require('./supply-production-entry.cjs');
const {installOperationsAssistantUI,selectObjective,actualOperationsAssistant:actual}=require('./operations-support-assistant-ui.cjs');
async function setupOperationsProduction(page,server,{role='admin',preview=false,forceSuccess=false,withdrawn=false}={}){
 const state=await installOperationsAssistantUI(page,{preview,forceSuccess,managementRole:role});state.withdrawn=withdrawn;state.bootstrap=[];state.errors=[];state.cssErrors=[];state.external=[];
 page.on('pageerror',e=>state.errors.push(e.message));page.on('response',r=>{if(new URL(r.url()).pathname.endsWith('.css')&&r.status()>=400)state.cssErrors.push({url:r.url(),status:r.status()});});
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-operations-production-entry'));
 await page.context().route('**/*',route=>{if(new URL(route.request().url()).origin===server.origin)return route.continue();state.external.push(route.request().url());return route.abort('blockedbyclient');});
 await page.route('**/api/**',async route=>{const req=route.request(),p=new URL(req.url()).pathname;if(p==='/api/userInfo'&&req.method()==='POST'){state.bootstrap.push({path:p,method:req.method(),body:req.postDataJSON()});return route.fulfill({status:200,json:{code:200,data:{username:'合成运维生产入口',permissions:role==='super_admin'?['super_admin','admin']:[role],avatar:''}}});}if(p==='/api/events/stream'&&req.method()==='GET')return route.fulfill({status:204,body:''});return route.fallback();});
 return state;
}
async function chooseOperationsProductionCase(page){
 const input=page.getByRole('region',{name:'明确运维材料集输入',exact:true});await input.getByRole('button',{name:'读取当前目录',exact:true}).click();await input.getByRole('button',{name:'核对本条完整来源',exact:true}).click();const dialog=page.getByRole('dialog',{name:'完整受审运维来源',exact:true});await dialog.getByRole('button',{name:'选择本条当前材料集',exact:true}).click();await expect(input.getByText('已选择材料集',{exact:false})).toBeVisible();return input;
}
async function assertOperationsStyles(page,button){await expect(button).toBeVisible();expect(['inline-flex','flex']).toContain(await button.evaluate(e=>getComputedStyle(e).display));expect(await button.evaluate(e=>getComputedStyle(e).borderTopStyle)).toBe('solid');expect(await page.evaluate(()=>Array.from(document.styleSheets).some(s=>s.href&&new URL(s.href).origin===location.origin&&new URL(s.href).pathname.endsWith('.css')))).toBe(true);}
function checkedOperationsProduction(state){expect(state.bootstrap).toEqual([{path:'/api/userInfo',method:'POST',body:{accesstoken:'synthetic-operations-production-entry'}}]);expect(state.errors).toEqual([]);expect(state.cssErrors).toEqual([]);expect(state.external).toEqual([]);expect(state.unknown).toEqual([]);expect(state.seen.some(x=>/service-options|operational-context|\/ai\/patients|\/ai\/encounters/u.test(x.path))).toBe(false);}
module.exports={actual,startOperationsProductionServer,setupOperationsProduction,chooseOperationsProductionCase,selectObjective,assertOperationsStyles,checkedOperationsProduction};
