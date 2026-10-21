const {expect}=require('@playwright/test');
const partial=require('./supply-series/partial.json'),complete=require('./supply-series/complete.json');
async function openSupplySeries(page,harness,config={}){
 const state={role:'admin',governance:false,fixture:partial,reads:[],writes:[],errors:[],releases:{},completed:[],...config},F=state.fixture;
 page.__supplySeriesState=state;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method();if(method==='GET')state.reads.push({path,query:Object.fromEntries(url.searchParams)});else state.writes.push({path,body:req.postDataJSON()});let data;
 if(path.endsWith('/supply-series/preview'))data=state.preview||F.preview;
 else if(path.endsWith('/review'))data=state.review||F.published_super;
 else if(path.endsWith('/revoke'))data=state.revoke||F.revoked_ordinary;
 else if(method==='POST')data=state.created||F.draft_ordinary;
 else if(/\/supply-series$/.test(path))data=state.list||{items:[],total:0,page:1,page_size:20};
 else data=state.detail||F.published_ordinary;
 const failure=state.failure?.(method,path),held=state.hold?.(method,path);data=structuredClone(data);if(held)await new Promise(resolve=>state.releases[held]=resolve);await route.fulfill(failure?{status:failure,json:{code:failure,msg:'isolated current permission changed'}}:{json:{code:200,data}});if(held)state.completed.push(held);
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplySeriesProbe);
 await page.evaluate(({role,governance,kind,id})=>{const p=window.__supplySeriesProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{itemKind:kind,itemId:id,governance,ready:true});},{role:state.role,governance:state.governance,kind:F.period_request.item_kind,id:F.period_request.item_id});return state;
}
async function begin(page,state){await page.getByRole('button',{name:'明确当前SKU的完整日序列',exact:true}).click();const dialog=page.getByRole('dialog',{name:'完整物资日序列与明确参数',exact:true});for(const[key,label]of[['timezone','明确IANA业务时区'],['date_from','首个完整业务日'],['date_to','最后完整业务日'],['as_of','原资料可得截止UTC']])await dialog.getByRole('textbox',{name:label,exact:true}).fill(state.fixture.period_request[key]);return dialog;}
async function capture(page,state){const d=await begin(page,state);await d.getByRole('button',{name:'读取完整候选、单位与逐日分组',exact:true}).click();await expect(d.getByRole('region',{name:'完整物资序列声明编辑',exact:true})).toBeVisible();return d;}
async function fillComplete(page,dialog,state){const F=state.fixture,R=F.create_request.request;
 await dialog.getByRole('combobox',{name:'本序列明确受审单位',exact:true}).selectOption(R.unit_definition_id);
 for(const[k,v]of Object.entries(R.parameters)){await dialog.getByRole('textbox',{name:k+' 分子',exact:true}).fill(v.numerator);await dialog.getByRole('textbox',{name:k+' 分母',exact:true}).fill(v.denominator);}
 await dialog.getByRole('textbox',{name:'本次共用审阅依据',exact:true}).fill(R.target_coverage[0].basis_note);await dialog.getByRole('button',{name:'将本次依据复制到所有尚未填写的声明',exact:true}).click();
 for(const r of R.target_coverage)for(const k of ['same_scope_confirmed','same_definition_confirmed','same_method_confirmed'])await dialog.getByRole('combobox',{name:r.target+' '+k,exact:true}).selectOption(r[k]);
 for(let i=0;i<R.member_reviews.length;i++){const r=R.member_reviews[i];if(i&&i%20===0)await dialog.getByRole('button',{name:'下一页成员',exact:true}).click();await dialog.getByRole('combobox',{name:r.source_record_id+' 原件用途',exact:true}).selectOption(r.selection);if(r.basis_note!==R.target_coverage[0].basis_note)await dialog.getByRole('textbox',{name:r.source_record_id+' 用途依据',exact:true}).fill(r.basis_note);}
 for(let i=0;i<R.days.length;i++){if(i&&i%7===0)await dialog.getByRole('button',{name:'下一页日期',exact:true}).click();const d=R.days[i];for(const r of d.selections)await dialog.getByRole('combobox',{name:d.date+' '+r.target+' 整件选择',exact:true}).selectOption(r.source_record_id??r.absent_reason);}
}
async function inspect(page,id=partial.published_ordinary.series_id){await page.getByRole('row').filter({hasText:id}).getByRole('button',{name:'核对完整物资序列',exact:true}).click();await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toBeVisible();}
async function cleared(page){await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toHaveCount(0);expect(await page.evaluate(()=>{const s=window.__supplySeriesProbe.panel.$.setupState;return{selected:s.selected,preview:s.preview,form:s.form,action:s.action};})).toEqual({selected:null,preview:null,form:null,action:null});}
module.exports={partial,complete,openSupplySeries,begin,capture,fillComplete,inspect,cleared};
