const {test,expect}=require('@playwright/test');
const source=require('./fixtures/bed-synthetic/sources.json');
const series=require('./fixtures/bed-synthetic/series-partial.json');
const metadataReply=require('./fixtures/bed-synthetic/provider-model-mismatch.json');
const catalog=require('./fixtures/bed-synthetic/catalog-prompt.json');
const sourceMetadata=row=>Object.fromEntries(Object.entries(row).filter(([k])=>!['payload','parent_binding','review_basis_note','revoke_reason'].includes(k)));
const seriesMetadata=row=>Object.fromEntries(Object.entries(row).filter(([k])=>!['snapshot','public_source','review_basis_note','revoke_reason'].includes(k)));

// These exercise the built application with isolated intercepted API responses.
// Original source/series/metadata DTOs are actual synthetic backend exports.
async function setup(page,role='super_admin',config={}){
  const state={reads:[],writes:[],bootstrap:[],errors:[]};
  const feature={...catalog.feature,input_mode:'bed',revision:3,prompt_version:0,active_prompt_id:null,enabled:!!config.operational,validation_status:config.operational?'validated':'unreviewed',validation_note:'',allowed_roles:catalog.feature.default_roles,provider_id:null,daily_limit:50,setup_check:{ready:false,issues:[],scope_note:'合成界面配置；未启用实际运营预测'}};
  page.on('pageerror',error=>state.errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-bed-production'));
  await page.context().route('**/*',route=>new URL(route.request().url()).origin===new URL(process.env.E2E_BASE_URL||'http://127.0.0.1:4180').origin?route.continue():route.abort('blockedbyclient'));
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method();let data=[];
    if(path==='/api/userInfo')state.bootstrap.push({method,path,body:req.postDataJSON()});
    else if(method==='GET')state.reads.push({path,query:Object.fromEntries(url.searchParams)});
    else state.writes.push({method,path,body:req.postDataJSON()});
    if(path==='/api/userInfo')data={username:'合成床位生产入口',permissions:[role],avatar:''};
    if(['/api/ai/admin/features','/api/ai/features'].includes(path))data=[feature];
    if(path==='/api/ward/getList')data=[{ward_id:1,department_id:1,name:'合成病区',bed_total:1,bed_used:0,bed_free:1}];
    if(path==='/api/departmentManagement/getList')data=[{id:1,name:'内科'}];
    if(path==='/api/ai/bed-series')data={items:[],total:0,page:1,page_size:20};
    if(path==='/api/ai/admin/providers')data=[{provider_id:metadataReply.data.provider_id,revision:metadataReply.data.provider_revision,model:metadataReply.data.configured_model,kind:'specialist',name:'合成床位固定服务',supported_features:['bed_forecast'],enabled:false,allows_patient_data:false,timeout_seconds:110,max_output_tokens:16000,temperature:0,validation_report:'尚未进行实际运营范围验证'}];
    if(path.endsWith('/bed-capabilities'))data=metadataReply.data;
    if(path==='/api/ai/bed-sources/options')data=url.searchParams.has('department_id')?source.department_options:source.options;
    if(path==='/api/ai/admin/bed-sources')data={items:[sourceMetadata(source.kinds.census.super_revoked)],total:1,page:1,page_size:20};
    if(path==='/api/ai/admin/bed-sources/'+source.kinds.census.super_revoked.source_record_id)data=source.kinds.census.super_revoked;
    if(path==='/api/ai/admin/bed-series')data={items:[seriesMetadata(series.super_revoked)],total:1,page:1,page_size:20};
    if(path==='/api/ai/admin/bed-series/'+series.super_revoked.series_id)data=series.super_revoked;
    if(path==='/api/ai/admin/prompts/bed_forecast'){
      data=method==='POST'?{prompt_id:'synthetic-bed-prompt-v1',version:1,revision:4}:{system_prompt:catalog.system_prompt,versions:[{prompt_id:null,version:0,change_note:'实际目录默认版本',task_prompt:catalog.task_prompt}]};
      if(method==='POST')feature.revision=4;
    }
    await route.fulfill({json:{code:200,msg:'success',data}});
  });
  return state;
}
function bootstrapChecked(state){expect(state.bootstrap).toEqual([{method:'POST',path:'/api/userInfo',body:{accesstoken:'synthetic-bed-production'}}]);expect(state.errors).toEqual([]);}

test('生产Super按需加载床位原来源和完整序列，撤销冻结审计保留原文且不能用于新预测',async({page})=>{
  const state=await setup(page);await page.goto('/#/ai/manage');
  await expect(page.getByRole('heading',{name:'AI 管理中心',exact:true})).toBeVisible();
  expect(state.reads.some(r=>r.path.includes('/bed-'))).toBe(false);
  await page.getByRole('tab',{name:'床位原来源治理',exact:true}).click();
  await page.getByRole('button',{name:'核对床位原来源',exact:true}).click();
  const original=page.getByRole('dialog',{name:'病区床位原来源冻结核对',exact:true});
  await expect(original).toContainText(source.kinds.census.super_revoked.content_hash);
  await expect(original).toContainText('超级管理员独立冻结审计');
  await original.getByText('院内核对完整原量、原时刻与自由依据',{exact:true}).click();
  await expect(original.locator('pre')).toContainText(source.kinds.census.super_revoked.payload.coverage_basis_note);
  await original.getByRole('button',{name:'关闭此对话框',exact:true}).click();
  await expect(original).toBeHidden();
  await page.getByRole('tab',{name:'床位完整序列治理',exact:true}).click();
  await page.getByRole('button',{name:'核对完整床位序列',exact:true}).click();
  const frozen=page.getByRole('dialog',{name:'完整床位序列冻结核对与治理',exact:true});
  await expect(frozen).toContainText(series.super_revoked.content_hash);
  await expect(frozen).toContainText('不能恢复旧来源作新运行');
  await frozen.getByRole('button',{name:'展开院内完整冻结原件',exact:true}).click();
  await expect(frozen.getByLabel('院内完整床位序列原件',{exact:true})).toContainText(series.super_revoked.snapshot.request.business_timezone);
  await expect(frozen.getByRole('button',{name:'选择此已发布床位序列',exact:true})).toHaveCount(0);
  expect(state.writes).toEqual([]);bootstrapChecked(state);
});

test('生产Super核对床位实际版本后只回填编辑表，不自动保存启用或验证',async({page})=>{
  const state=await setup(page);await page.goto('/#/ai/manage');
  await page.getByRole('tab',{name:'模型服务',exact:true}).click();
  await page.getByRole('button',{name:'检查本地床位服务',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'本地床位固定预测服务核对',exact:true});
  await expect(dialog).toContainText(metadataReply.data.capabilities.runtime_digest);
  await expect(dialog).toContainText(metadataReply.data.capabilities.timezone_database_digest);
  await dialog.getByRole('button',{name:'填写实际模型，待保存',exact:true}).click();
  const edit=page.getByRole('dialog',{name:'编辑模型服务',exact:true});
  await expect(edit.getByPlaceholder('服务端实际提供的模型名称',{exact:true})).toHaveValue(metadataReply.data.capabilities.model_version);
  await expect(edit.locator('.el-form-item').filter({hasText:'适配器验证报告'}).getByRole('textbox')).toHaveValue('尚未进行实际运营范围验证');
  expect(state.writes).toEqual([{method:'POST',path:`/api/ai/admin/providers/${metadataReply.data.provider_id}/bed-capabilities`,body:{expected_revision:metadataReply.data.provider_revision}}]);
  bootstrapChecked(state);
});

test('生产Super读取床位独立Prompt并按原revision保存新版本，保持未启用未验证',async({page})=>{
  const state=await setup(page);await page.goto('/#/ai/manage');
  await page.getByRole('button',{name:'Prompt',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'床位占用与流转预测：Prompt 版本',exact:true});
  await expect(dialog.locator('textarea')).toHaveValue(catalog.task_prompt);
  expect(catalog.task_prompt).toContain('28个滚动原点');expect(catalog.task_prompt).toContain('不自动调床、收治或出院');
  await dialog.getByPlaceholder('说明本次修改目的和适用范围',{exact:true}).fill('合成版本验证：保留固定配方、原时刻和五目标独立缺项');
  await dialog.getByRole('button',{name:'保存为新版本',exact:true}).click();
  await expect.poll(()=>state.writes.length).toBe(1);
  expect(state.writes).toEqual([{method:'POST',path:'/api/ai/admin/prompts/bed_forecast',body:{expected_revision:3,task_prompt:catalog.task_prompt,change_note:'合成版本验证：保留固定配方、原时刻和五目标独立缺项',activate:false}}]);
  bootstrapChecked(state);
});

test('生产普通管理员直达AI管理页不会读取床位治理或管理接口',async({page})=>{
  const state=await setup(page,'admin');await page.goto('/#/ai/manage');
  await expect(page).toHaveURL(/#\/404/);
  expect(state.reads.filter(r=>r.path.startsWith('/api/ai/admin'))).toEqual([]);
  expect(state.writes).toEqual([]);bootstrapChecked(state);
});


test('生产病区页面把当前科室和病区传入AI，不默认选择序列或期限',async({page})=>{
  const state=await setup(page,'admin',{operational:true});await page.goto('/#/inpatient/wardManagement');
  await page.getByRole('row').filter({hasText:'合成病区'}).click();
  await page.getByRole('button',{name:'AI 床位占用与流转预测',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'AI 床位占用与实际流转辅助',exact:true});
  await expect(drawer.locator('.el-form-item').filter({hasText:'床位预测科室'})).toContainText('内科 · #1');
  await expect(drawer.locator('.el-form-item').filter({hasText:'床位预测病区'})).toContainText('合成病区 · #1');
  await expect(drawer.locator('.el-form-item').filter({hasText:'床位预测期限'})).toContainText('明确7或14天，不默认');
  await expect(drawer.getByRole('button',{name:'生成辅助建议',exact:true})).toBeDisabled();
  expect(state.reads.some(r=>r.path==='/api/ai/bed-series'&&r.query.department_id==='1'&&r.query.ward_id==='1')).toBe(true);
  expect(state.reads.some(r=>r.path==='/api/ai/service-options')).toBe(false);
  expect(state.writes).toEqual([]);bootstrapChecked(state);
});
