const {test,expect}=require('@playwright/test');
const {loadProductionStates,startResearchVariableProductionServer,styles,setupResearchVariableProduction,openResearchVariableWorkbench,chooseResearchVariableBatch,generateResearchVariableTask}=require('./fixtures/research-variable-production-entry.cjs');
let server;
test.beforeAll(async()=>{server=await startResearchVariableProductionServer();});
test.afterAll(async({},info)=>{if(!server)return;try{expect(server.unhandled).toEqual([]);}finally{await server.close();await info.attach('research-variable-production-static-cleanup',{body:JSON.stringify({scope:'production_mock static dist; no backend or API proxy',origin:server.origin,closed:!server.listening,unhandled:server.unhandled,dist:server.manifest}),contentType:'application/json'});}});
test.afterEach(async({page},info)=>{const state=page.__researchVariableProduction;for(const release of Object.values(state?.releases||{}))release();if(info.status!==info.expectedStatus)await info.attach('research-variable-production-diagnostic',{body:JSON.stringify({state,body:await page.locator('body').innerText().catch(()=>null)},null,2),contentType:'application/json'});});
function checked(state,{authentication=true}={}){
 expect(state.errors).toEqual([]);expect(state.unknown).toEqual([]);expect(state.external).toEqual([]);expect(state.cssErrors).toEqual([]);expect(state.assetErrors).toEqual([]);
 expect(state.bootstrap.filter(row=>row.path==='/api/userInfo')).toEqual(authentication?[{method:'POST',path:'/api/userInfo',query:{},body:{accesstoken:'synthetic-variable-production-session'},classification:'platform-authentication-read'}]:[]);
 expect(state.writes.every(row=>row.path==='/api/ai/research-variables/context'||row.path==='/api/ai/runs'||row.path==='/api/ai/runs/'+state.fixture.states.succeeded_partial.detail.run_id+'/feedback')).toBe(true);
 expect(state.reads.some(row=>/patients|encounters|service-options|operational-context/u.test(row.path))).toBe(false);
}

test('production workbench76 explicitly verifies a real Batch then previews and expands one queued Task to literal Findings and manual feedback',async({page})=>{
 const state=await setupResearchVariableProduction(page,server),panel=await openResearchVariableWorkbench(page,server);
 expect(state.reads.map(row=>row.path)).toEqual(['/api/ai/features']);
 await generateResearchVariableTask(page,panel,state);
 await styles(page,panel.getByTestId('variable-refresh'));
 const actual=state.fixture.states.succeeded_partial,candidate=actual.parts.result.result.research_variable_extraction.literal_draft.candidates[0];
 expect(await panel.getByLabel('科研变量第1条逐字引文',{exact:true}).textContent()).toBe(candidate.quote);
 await expect(panel.getByLabel('科研变量实际用量',{exact:true})).toContainText('实际输入用量：11；实际输出用量：未知');
 await panel.getByTestId('variable-feedback-outcome').click();await page.getByRole('option',{name:'修改后再核',exact:true}).click();
 const comment='实际人工复核仍需逐项核对，未自动生成科研矩阵';await panel.getByTestId('variable-feedback-comment').fill(comment);await panel.getByTestId('variable-feedback').click();
 await expect(panel.getByText('人工复核已记录；未生成已审核矩阵、导出或临床写入。',{exact:true})).toBeVisible();
 expect(state.writes).toEqual([
  {method:'POST',path:'/api/ai/research-variables/context',query:{},body:state.fixture.selection},
  {method:'POST',path:'/api/ai/runs',query:{},body:{feature_key:'research_extraction',input:state.fixture.selection,preview:false}},
  {method:'POST',path:'/api/ai/runs/'+actual.detail.run_id+'/feedback',query:{},body:{outcome:'modified',comment}},
 ]);
 expect(state.reads.filter(row=>row.path==='/api/ai/runs/'+actual.detail.run_id)).toHaveLength(1);
 expect(state.reads.filter(row=>row.path.startsWith('/api/ai/runs/'+actual.detail.run_id+'/research-variables/')).map(row=>row.path.split('/').at(-1)).sort()).toEqual(['binding','receipt','result','scope','source']);
 checked(state);
});

test('production ordinary history retains the exact selected Batch and rechecks complete parts before displaying a historical draft',async({page})=>{
 const state=await setupResearchVariableProduction(page,server),panel=await openResearchVariableWorkbench(page,server);await chooseResearchVariableBatch(page,panel,state);
 await panel.getByTestId('variable-history').click();const actual=state.fixture.states.succeeded_partial;
 await panel.getByRole('button',{name:actual.detail.run_id+' · succeeded',exact:true}).click();
 await expect(panel.getByLabel('科研变量任务状态',{exact:true})).toHaveText('草稿已接收，未审核');
 expect(state.reads.find(row=>row.path==='/api/ai/runs').query).toEqual({feature_key:'research_extraction',research_variable_batch_id:state.fixture.selection.research_variable_batch_id,limit:'30'});
 expect(state.reads.some(row=>row.path.startsWith('/api/ai/admin/'))).toBe(false);
 expect(state.writes.map(row=>row.path)).toEqual(['/api/ai/research-variables/context']);checked(state);
});

test('production failed current Task authorization clears prior Source and Findings and keeps the error without resubmitting',async({page})=>{
 const state=await setupResearchVariableProduction(page,server),panel=await openResearchVariableWorkbench(page,server);await generateResearchVariableTask(page,panel,state);state.denyCurrent=true;
 const before=state.reads.length;await panel.getByTestId('variable-refresh').click();
 await expect(panel.getByText('完整任务与原批次、问题或实际回执无法核对，请明确重新读取；未回退为通用结果。',{exact:true})).toBeVisible();
 await expect(panel.getByTestId('variable-preview')).toHaveCount(0);await expect(panel.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);await expect(panel.getByTestId('variable-question')).toHaveValue('');await expect(panel.getByTestId('variable-submit')).toBeDisabled();
 await expect(panel.getByTestId('variable-inspect')).toBeDisabled();expect(state.reads.slice(before)).toEqual([{method:'GET',path:'/api/ai/runs/'+state.fixture.states.succeeded_partial.detail.run_id,query:{}}]);
 expect(state.writes.filter(row=>row.path==='/api/ai/runs')).toHaveLength(1);checked(state);
});

test('production Super management loads Source only on demand then verifies the actual Scope and both independent dictionary pieces',async({page})=>{
 const state=await setupResearchVariableProduction(page,server,{role:'super_admin'});await page.goto(server.origin+'/#/ai/manage');await expect(page.getByRole('heading',{name:'AI 管理中心',exact:true})).toBeVisible();
 const sources=()=>state.reads.filter(row=>row.path.includes('/research-variables/')||row.path.includes('/research-cohort/'));
 expect(sources()).toEqual([]);await page.getByRole('tab',{name:'科研变量字典与完整批次治理',exact:true}).click();expect(sources()).toEqual([]);
 await page.getByRole('button',{name:'读取明确项目目录',exact:true}).click();await page.getByRole('button',{name:'核对并明确本项目',exact:true}).click();await expect(page.getByText(/明确项目 .*；用途已记录 research_variable_extraction/u)).toBeVisible();
 await page.getByRole('button',{name:'刷新变量来源目录',exact:true}).click();await page.getByRole('button',{name:'按当前授权读取完整两件',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'变量来源完整核对',exact:true});await expect(dialog).toContainText('两份完整分件、原件字面值、治理关系和末次元数据已核对');
 await dialog.getByRole('button',{name:'显式展开完整来源原件',exact:true}).click();await expect(dialog.getByLabel('完整变量来源原件',{exact:true})).toContainText(state.fixture.management.source_metadata.dictionaries.data.content_hash);
 await styles(page,dialog.getByRole('button',{name:'收起完整来源原件',exact:true}));expect(sources().filter(row=>row.path.includes('/parts/')).map(row=>row.path.split('/').at(-1))).toEqual(['definition','scope']);
 expect(state.writes).toEqual([]);checked(state);
});

test('production ordinary doctor management route is rejected before any admin or Source private request',async({page})=>{
 const state=await setupResearchVariableProduction(page,server,{role:'doctor'});await page.goto(server.origin+'/#/ai/manage');await expect(page).toHaveURL(/#\/404/u);
 expect(state.reads.some(row=>row.path.startsWith('/api/ai/admin/')||row.path.includes('/research-variables/')||row.path.includes('/research-cohort/'))).toBe(false);expect(state.writes).toEqual([]);checked(state);
});

test('production exact inert icon record preserves all293 actual geometries with real static CSS',async({page})=>{
 // Minimal same-origin synthetic HTML only: no app route, API call, or invented
 // product gallery endpoint. Glyph bytes and CSS are the canonical dist assets.
 const state=await setupResearchVariableProduction(page,server);
 const manifest=require('../src/api/iconGallery.json'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
 const dist=path.join(__dirname,'../dist'),candidates=[];
 const index=fs.readFileSync(path.join(dist,'index.html'),'utf8');
 const records=index.match(/<script id="hoim-schema-data" type="application\/json">(.*?)<\/script>/u);
 expect(records).not.toBeNull();
 const envelope=JSON.parse(records[1]);expect(envelope.schema_version).toBe('hoim_static_schema_document_v1');
 const {decodeSchemaText,decodeStaticCodeBytes}=require('../src/api/schemaDataCodec.cjs');
 for(const [digest,record]of Object.entries(envelope.entries)){
  const packed=Buffer.from(decodeStaticCodeBytes(record.encoded,record.packedBytes),'binary');expect(crypto.createHash('sha256').update(packed).digest('hex')).toBe(digest);expect(packed.length).toBe(record.packedBytes);
  const decoded=JSON.parse(decodeSchemaText(record.encoded,record.byteLength));
  if(decoded&&Object.keys(decoded).join(',')==='svg'&&typeof decoded.svg==='string'&&crypto.createHash('sha256').update(decoded.svg).digest('hex')===manifest.sprite_sha256)candidates.push(decoded.svg);
 }
 expect(candidates).toHaveLength(1);expect(manifest.names).toHaveLength(293);
 const sprite='',originalSprite=candidates[0].replace('<svg ','<svg style="position:absolute;width:0;height:0;overflow:hidden" ');
 // Preserve only the actual initial document stylesheet tags and their order.
 // Do not inject unrelated lazy-page CSS or assert an invented card border.
 const cssTags=[...index.matchAll(/<link\b[^>]*>/gu)].map(match=>match[0]).filter(tag=>/\brel\s*=\s*(?:"stylesheet"|'stylesheet'|stylesheet)(?=\s|\/?>)/u.test(tag));
 expect(cssTags.length).toBeGreaterThan(0);
 const cssUrls=cssTags.map(tag=>{const match=tag.match(/\bhref\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/u);expect(match).not.toBeNull();const value=new URL(match[1]||match[2]||match[3],server.origin+'/');expect(value.origin).toBe(server.origin);expect(fs.existsSync(path.join(dist,decodeURIComponent(value.pathname)))).toBe(true);return value.href;});
 const links=cssTags.join('');
 const icons=manifest.names.map(name=>'<div><i class="el-icon" style="font-size:24px;color:rgb(20,60,100)"><svg viewBox="0 0 1024 1024" width="24" height="24" aria-label="'+name+'"><use href="'+sprite+'#icon-'+name+'"></use></svg></i></div>').join('');
 const entry=server.origin+'/__research_variable_static_gallery.html';
 await page.route(entry,route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><meta charset="utf-8">'+links+originalSprite+'<section aria-label="生产静态图标完整资产核对" style="display:grid;grid-template-columns:repeat(12,1fr)">'+icons+'</section>'}));
 await page.goto(entry);const gallery=page.getByRole('region',{name:'生产静态图标完整资产核对',exact:true});await expect(gallery.locator('svg')).toHaveCount(293);
 await expect.poll(()=>gallery.locator('svg').evaluateAll(nodes=>nodes.filter(node=>{try{const b=node.getBBox();return b.width>0&&b.height>0;}catch{return false;}}).length)).toBe(293);
 const loaded=await gallery.locator('svg').evaluateAll(nodes=>nodes.map(node=>({width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,viewBox:node.getAttribute('viewBox'),use:node.querySelector('use').getAttribute('href')})));
 expect(loaded.every(row=>row.width===24&&row.height===24&&row.viewBox==='0 0 1024 1024')).toBe(true);expect(loaded.map(row=>row.use.split('#icon-')[1])).toEqual(manifest.names);
 expect(await page.evaluate(()=>[...document.styleSheets].filter(sheet=>sheet.href).map(sheet=>sheet.href))).toEqual(cssUrls);
 expect(await gallery.locator('.el-icon').first().evaluate(node=>getComputedStyle(node).display)).toBe('inline-flex');
 expect(await gallery.locator('svg').evaluateAll(nodes=>nodes.every(node=>getComputedStyle(node).fill==='rgb(20, 60, 100)'&&getComputedStyle(node).color==='rgb(20, 60, 100)'))).toBe(true);
 expect(state.bootstrap).toEqual([]);expect(state.reads).toEqual([]);expect(state.writes).toEqual([]);checked(state,{authentication:false});
});


test('production pharmacist under an explicit synthetic five-role configuration reads the actual76 project context without the74 registry',async({page})=>{
 const state=await setupResearchVariableProduction(page,server,{role:'pharmacist'}),actual=require('./fixtures/research-variable-pharmacist-fixture.cjs').loadPharmacistLifecycle();
 const features=structuredClone(state.fixture.features),feature=features.data.find(row=>row.key==='research_extraction');feature.allowed_roles=[...feature.default_roles];
 // Explicit UI configuration declaration; the original actual feature response
 // is preserved in its fixture. The Source context body below is unchanged Main.
 await page.route('**/api/ai/features',route=>{state.reads.push({method:'GET',path:'/api/ai/features',query:{}});return route.fulfill({json:features});});
 await page.route('**/api/ai/research-variables/scopes/*',route=>{const q=route.request(),url=new URL(q.url());state.reads.push({method:q.method(),path:url.pathname,query:Object.fromEntries(url.searchParams)});expect(url.pathname).toBe('/api/ai/research-variables/scopes/'+actual.id);const row=actual.byStage['scope.context'];return route.fulfill({status:row.status,body:row.body,headers:row.response_headers});});
 const panel=await openResearchVariableWorkbench(page,server);await panel.getByRole('button',{name:'打开完整变量来源目录',exact:true}).click();await expect(page.getByRole('button',{name:'读取明确项目目录',exact:true})).toHaveCount(0);await page.getByLabel('已授权变量项目标识',{exact:true}).fill(actual.id);await page.getByRole('button',{name:'读取授权变量项目',exact:true}).click();await expect(page.getByRole('button',{name:'登记明确变量字典',exact:true})).toBeVisible();expect(state.reads.map(row=>row.path)).toEqual(['/api/ai/features','/api/ai/research-variables/scopes/'+actual.id]);expect(state.writes).toEqual([]);checked(state);
});
