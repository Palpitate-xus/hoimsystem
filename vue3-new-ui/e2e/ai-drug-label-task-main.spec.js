const {test,expect}=require('@playwright/test');
const {startDrugLabelTaskHarness}=require('./fixtures/drug-label-task-harness.cjs');
const {load}=require('./fixtures/load-drug-label-main.cjs');
let harness;test.beforeAll(async()=>{harness=await startDrugLabelTaskHarness({findings:true});});test.afterAll(async()=>harness?.close());
for(const kind of ['chat','responses']){
 const p=load(kind),run=p.full.data,trace=p.trace.data;
 test(`actual main ${kind} nonempty preview/full/independent Super/full trace pass unchanged complete guards`,async({page})=>{
  await page.addInitScript(()=>{window.__drugLabelTaskRole='super_admin';});await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelTaskProbe);
  expect(await page.evaluate(async p=>{const a=window.__drugLabelTaskProbe.api;return [await a.verifyDrugLabelContext(p.preview.data),await a.verifyDrugLabelRun(p.full.data),await a.verifyDrugLabelRun(p.super_full.data,{}, {allowFrozenAudit:true,auditOnly:true}),await a.verifyDrugLabelTrace(p.trace.data,p.full.data,{}, {allowFrozenAudit:true})];},p)).toEqual([true,true,true,true]);
  expect(run.result.drug_label_extraction.fields).toHaveLength(1);
 });
 test(`actual main ${kind} nonempty literal DOM keeps BOM CRLF emoji combining marks UTC6 and codepoint span`,async({page})=>{
  await page.addInitScript(({run,trace})=>{window.__drugLabelTaskRole='super_admin';window.__drugLabelTaskScope={run,trace};},{run,trace});await page.goto(harness.origin);
  await expect(page.getByLabel('说明书核验范围')).toBeVisible();await expect(page.getByLabel('说明书逐字字段表')).toBeVisible();
  const span=run.result.drug_label_extraction.fields[0].spans[0],original=run.drug_label_findings.drug_label_source.text;
  expect(Array.from(original).slice(span.start,span.end).join('')).toBe(span.quote);
  await page.getByRole('button',{name:'查看第1项第1段引文',exact:true}).click();expect(await page.getByLabel('说明书字段逐字引文').textContent()).toBe(span.quote);
  await page.getByRole('dialog',{name:'本次原文逐字区间'}).getByRole('button',{name:'Close this dialog'}).click();
  await page.getByRole('button',{name:'展开完整说明书原文',exact:true}).click();expect(await page.getByLabel('任务完整说明书原文').textContent()).toBe(original);
  expect(original.startsWith('\ufeff')).toBe(true);expect(original).toContain('\r\n');expect(original).toContain('😀é');expect(original).toContain('2026-10-21T12:00:00.123456Z');
  await expect(page.getByLabel('说明书核验范围')).toContainText('原Task三JSON字符串逐字UTF8核对');
 });
}
