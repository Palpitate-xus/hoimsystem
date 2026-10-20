const {test,expect}=require('@playwright/test'),{startSurgeryHarness}=require('./fixtures/surgery-source-harness.cjs'),{providers:P,openSurgery}=require('./fixtures/surgery-source-ui.cjs');
let harness;test.beforeAll(async()=>harness=await startSurgeryHarness());test.afterAll(async()=>harness?.close());
for(const[name,item]of Object.entries(P.cases))test(`实际JWT/ASGI ${name} metadata核四core与政策，只报告声明不执行预约`,async({page})=>{
 const response=item.response,state=await openSurgery(page,harness,{mode:'provider',response}),d=response.data,dialog=page.getByRole('dialog',{name:'本地手术候选优化服务核对',exact:true});
 await expect(dialog).toContainText(d.capabilities.runtime_digest);await expect(dialog).toContainText(d.capabilities.timezone_database_digest);await expect(dialog).toContainText('平台仅鉴权 GET 服务 /capabilities');await expect(dialog).toContainText('不自动预约');
 for(const issue of d.issues)await expect(dialog).toContainText(issue);
 expect(state.writes).toEqual([{method:'POST',path:`/api/ai/admin/providers/${d.provider_id}/surgery-capabilities`,body:{expected_revision:d.provider_revision}}]);expect(state.errors).toEqual([]);
});
test('模型差异仅显式回填原CAS编辑表单，待用户保存，不自动启用或更改验证',async({page})=>{
 const response=P.cases.model_mismatch.response,state=await openSurgery(page,harness,{mode:'provider',response});await page.getByRole('button',{name:'填写实际模型，待保存',exact:true}).click();const d=response.data;
 expect(await page.evaluate(()=>window.__surgeryProbe.events)).toEqual([{type:'edit-model',value:{provider_id:d.provider_id,revision:d.provider_revision,configured_model:d.configured_model,model:d.capabilities.model_version,session:'synthetic-surgery-session'}},{type:'close'}]);expect(state.writes).toHaveLength(1);
});
for(const change of ['token','role','revision','model','feature','deactivate','unmount'])test(`手术能力迟到遇${change}变化拒旧声明与CAS回填`,async({page})=>{
 const state=await openSurgery(page,harness,{mode:'provider',response:P.cases.model_mismatch.response,hold:()=> 'metadata'});await expect.poll(()=>!!state.releases.metadata).toBe(true);
 await page.evaluate(change=>{const p=window.__surgeryProbe;if(change==='token')p.store.commit('user/token','later-session');if(change==='role')p.store.commit('user/permissions',['admin']);if(change==='revision')p.scope.providers[0].revision++;if(change==='model')p.scope.providers[0].model='surgery:'+'f'.repeat(64);if(change==='feature')p.scope.providers[0].supported_features=[];if(change==='deactivate')p.scope.mounted=false;if(change==='unmount')p.scope.destroyed=true;},change);
 state.releases.metadata();await expect.poll(()=>state.completed).toContain('metadata');await expect(page.getByRole('button',{name:'填写实际模型，待保存',exact:true})).toHaveCount(0);expect(await page.evaluate(()=>window.__surgeryProbe.events.filter(x=>x.type==='edit-model'))).toEqual([]);expect(state.errors).toEqual([]);
});
test('普通运营admin不请求Super metadata，provider整数路径不接bool/string/UUID',async({page})=>{
 const state=await openSurgery(page,harness,{mode:'provider',role:'admin'});await expect(page.getByRole('dialog')).toHaveCount(0);expect(state.writes).toEqual([]);
 expect(await page.evaluate(()=>{const a=window.__surgeryProbe.provider;return[true,'1','00000000-0000-0000-0000-000000000000',0,2147483648].map(id=>{try{a.checkSurgeryProvider(id,1);return false;}catch{return true;}});})).toEqual(Array(5).fill(true));
});
test('错误CAS回执与自报compatible不能覆盖已保存模型差异',async({page})=>{
 const response=structuredClone(P.cases.model_mismatch.response);response.data.compatible=true;response.data.issues=[];await openSurgery(page,harness,{mode:'provider',response,targetReceipt:P.cases.model_mismatch.response});await expect(page.getByRole('alert')).toContainText('核对回执与当前已保存手术服务或完整能力声明不一致');await expect(page.getByRole('button',{name:'填写实际模型，待保存',exact:true})).toHaveCount(0);
});
test('原能力的core/政策/预约边界不可由重算runtime摘要自证，schema12须原字符串',async({page})=>{
 await openSurgery(page,harness);const result=await page.evaluate(async response=>{const p=window.__surgeryProbe,out=[],fields=['engine','python_version','engine_versions','core_sha256','recipe_digest','input_policy_digest','timezone_database_digest','clinical_validation','operational_validation','prompt_handling'];for(const mutate of [c=>c.core_sha256[Object.keys(c.core_sha256)[0]]='0'.repeat(64),c=>c.recipe.rule_id='unreviewed_rule',c=>c.automatic_booking=true,c=>c.candidate_only=false,c=>c.schema_version=12]){const c=structuredClone(response.data.capabilities);mutate(c);c.recipe_digest=await p.supportDigest(c.recipe);c.input_policy_digest=await p.supportDigest(c.input_policy);c.runtime_digest=await p.supportDigest(Object.fromEntries(fields.map(k=>[k,c[k]])));c.model_version=`surgery:${c.runtime_digest}`;out.push(await p.provider.verifySurgeryCapabilities(c));}return out;},P.cases.compatible.response);expect(result).toEqual(Array(5).fill(false));
});
