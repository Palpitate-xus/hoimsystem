const {test,expect}=require('@playwright/test');
const {startRcaProductionServer,openRcaProduction,checkedRcaProduction}=require('./fixtures/rca-evidence-production-entry.cjs');
let server;
test.beforeAll(async()=>server=await startRcaProductionServer());
test.afterAll(async({},info)=>{try{expect(server.unhandled).toEqual([]);}finally{await server.close();await info.attach('rca-canonical-production-cleanup',{body:JSON.stringify({closed:!server.listening,unhandled:server.unhandled,dist_manifest:server.manifest}),contentType:'application/json'});}});

test('canonical production Sup governance remains bodyless without an actual event',async({page})=>{
 const api=await openRcaProduction(page,server,{view:'manage'});
 await expect(page.getByRole('tab',{name:'说明书原文与独立签署治理',exact:true})).toBeVisible();
 await page.getByRole('tab',{name:'完整事件RCA来源治理',exact:true}).click();
 await expect(page.getByText('请从实际事件业务行进入并明确关联范围。',{exact:true})).toBeVisible();
 expect(api.reads.some(path=>path.includes('/rca-evidence/'))).toBe(false);
 expect(api.writes.filter(call=>call.path!=='/api/userInfo')).toEqual([]);
 checkedRcaProduction(api);
});

test('canonical production actual event row selects complete Case and accepts split native Task',async({page})=>{
 const api=await openRcaProduction(page,server);
 await page.getByRole('button',{name:'完整RCA来源与调查草稿',exact:true}).click();
 await page.getByRole('row').filter({hasText:'published'}).getByRole('button',{name:'明确读取本件完整证明',exact:true}).click();
 await page.getByRole('button',{name:'明确选择本件当前Case',exact:true}).click();
 await page.getByRole('button',{name:'明确重读所选RCA Case',exact:true}).click();
 await expect(page.getByLabel('RCA已核对Case锚')).toBeVisible();
 const input=api.packet.states.succeeded.detail.data.rca_evidence_findings.input;
 await page.getByRole('textbox',{name:'RCA原样可选问题',exact:true}).fill(input.question);
 await page.getByText('明确以Super试运行RCA',{exact:true}).click();
 const button=page.getByRole('button',{name:'提交未核实RCA假设任务',exact:true});
 await expect(button).toBeEnabled();await button.click();
 await expect(page.getByLabel('RCA未核实假设列表')).toContainText('合成模型意见仍待核实');
 expect(api.writes.filter(call=>call.path!=='/api/userInfo')).toEqual([{path:'/api/ai/runs',body:{feature_key:'incident_rca',input,preview:true}}]);
 await expect(page.getByLabel('RCA完整私有Case')).toHaveCount(0);
 checkedRcaProduction(api);
});
