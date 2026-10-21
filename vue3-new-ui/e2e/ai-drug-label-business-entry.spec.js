const {test,expect}=require('@playwright/test');
const {startServer,setup,openAssistant,checked}=require('./fixtures/drug-label-production-entry.cjs');
let server;
test.beforeAll(async()=>{server=await startServer();});
test.afterAll(async({},info)=>{try{expect(server.unhandled).toEqual([]);}finally{await server.close();await info.attach('leaflet-canonical-production-cleanup',{body:JSON.stringify({origin:server.origin,closed:!server.listening,api_unhandled:server.unhandled,dist_manifest:server.manifest}),contentType:'application/json'});}});
for(const [kind,role]of [['chat','pharmacist'],['responses','pharmacist'],['chat','super_admin']])test('production drug row '+kind+' '+role+' binds exact SKU and complete native task',async({page})=>{
 const s=await setup(page,server,{kind,role}),d=await openAssistant(page,s);
 await expect(d.getByRole('button',{name:'生成辅助建议',exact:true})).toHaveCount(0);
 await d.getByRole('textbox',{name:'说明书抽取可选问题',exact:true}).fill(s.p.input.question);
 await expect(d.getByRole('button',{name:'提交未核实说明书字段抽取',exact:true})).toBeEnabled();
 await d.getByRole('button',{name:'提交未核实说明书字段抽取',exact:true}).click();
 await expect(d.getByLabel('说明书模型摘要',{exact:true})).toHaveText(s.p.full.data.result.summary);
 await d.getByRole('button',{name:'查看第1项第1段引文',exact:true}).click();
 const span=s.p.full.data.result.drug_label_extraction.fields[0].spans[0];
 expect(await page.getByLabel('说明书字段逐字引文',{exact:true}).textContent()).toBe(span.quote);
 expect(s.calls.filter(c=>c.method==='POST')).toEqual([{method:'POST',path:'/api/ai/runs',query:{},body:{feature_key:'drug_label_extraction',input:s.p.input,preview:false}}]);
 expect(s.calls.some(c=>c.path==='/api/ai/runs/'+s.p.full.data.run_id)).toBe(true);
 const directoryCalls=s.calls.filter(c=>c.path==='/api/ai/drug-label-sources');expect(directoryCalls.length).toBeGreaterThan(0);expect(directoryCalls.every(c=>c.query.pharmaceutical_id===String(s.p.source.data.snapshot.identity.pharmaceutical_id))).toBe(true);
 checked(s);
});
test('production pharmacist explicitly opens SKU source/signature governance and clears it on session change',async({page})=>{
 const s=await setup(page,server);expect(s.calls.filter(c=>c.path.startsWith('/api/ai/drug-label-sources'))).toEqual([]);
 await page.getByRole('row').filter({hasText:s.p.source.data.snapshot.identity.name}).getByRole('button',{name:'说明书原文与签署',exact:true}).click();
 const d=page.getByRole('dialog',{name:'本药品说明书原文与本人签署',exact:true});
 await expect(d.getByRole('combobox',{name:'明确选择目录药品',exact:true})).toBeDisabled();
 await d.getByRole('row').filter({hasText:s.p.input.drug_label_source_binding_id}).getByRole('button',{name:'读取本件完整依据',exact:true}).click();
 const detail=page.getByRole('dialog',{name:'说明书原件与独立签署核对',exact:true});await expect(detail).toContainText(s.p.source.data.snapshot.original.snapshot.raw_bytes_hash);
 await page.evaluate(()=>document.querySelector('#hoim').__vue_app__.config.globalProperties.$store.commit('user/setPermissions',['admin']));
 await expect(page.getByRole('dialog',{name:'本药品说明书原文与本人签署',exact:true})).toBeHidden();
 await expect(page.getByRole('dialog',{name:'说明书原件与独立签署核对',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'说明书原文与签署',exact:true})).toHaveCount(0);
 expect(s.calls.filter(c=>c.method==='POST')).toEqual([]);checked(s);
});
test('production ordinary administrator has no leaflet task or signing entry',async({page})=>{
 const s=await setup(page,server,{role:'admin'});await expect(page.getByRole('button',{name:'核对说明书字段',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'说明书原文与签署',exact:true})).toHaveCount(0);expect(s.calls.filter(c=>c.path.startsWith('/api/ai/drug-label-sources'))).toEqual([]);checked(s);
});
