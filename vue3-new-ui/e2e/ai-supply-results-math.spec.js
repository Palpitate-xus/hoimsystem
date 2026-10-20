const fs=require('node:fs'),path=require('node:path');
const {test,expect}=require('@playwright/test');
const {startSupplyHarness}=require('./fixtures/supply-result-harness.cjs');
const read=name=>JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/supply-native',name+'.json'),'utf8'));
let harness;
test.beforeAll(async()=>{harness=await startSupplyHarness({results:true});});
test.afterAll(async()=>{await harness?.close();});
async function open(page){const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/api/**',route=>route.abort());await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplyProbe?.results);return errors;}
for(const name of ['complete-h14','zero-h7','partial-h7','unknown-h7','unit-mismatch-h7','split-parameters-h7'])test('independently recomputes actual native pure calculation '+name,async({page})=>{
 const errors=await open(page),fixture=read(name);
 expect(await page.evaluate(async f=>{const r=window.__supplyProbe.results;return{source:await r.verifySupplySource(f.source),analysis:await r.verifySupplyAnalysis(f.source,f.analysis),selected:f.analysis.selected_model};},fixture)).toEqual({source:true,analysis:true,selected:null});
 expect(errors).toEqual([]);
});
test('preserves native zero, undefined denominators, partial folds and foreign unit exclusion',async({page})=>{
 await open(page);
 const zero=read('zero-h7'),partial=read('partial-h7'),foreign=read('unit-mismatch-h7');
 expect(zero.analysis.targets[0].last_day_value).toBe('0.000000');expect(zero.analysis.targets[0].models[3].prediction.values).toEqual([{numerator:'0',denominator:'1'}]);
 expect(zero.analysis.targets[0].models[3].metrics.wape).toBeNull();expect(zero.analysis.targets[0].models[3].metrics.mase).toBeNull();
 expect(partial.analysis.targets[0].models[0]).toMatchObject({status:'partial_backtest',eligible_origin_count:10,directly_comparable:false});
 expect(foreign.analysis.targets[0]).toMatchObject({status:'input_unknown',last_day_value:null,known_observed_sum:{numerator:'222',denominator:'1'}});
 expect(await page.evaluate(()=>{const r=window.__supplyProbe.results;return[r.supplyExactText({numerator:'0',denominator:'1'}),r.supplyExactText(null),r.supplyExactText({numerator:'9007199254740993',denominator:'2'})];})).toEqual(['0','未定义（null）','9007199254740993 / 2']);
});
for(const change of ['prediction','rolling_scale','training_digest','daily_mse','lead_denominator','cumulative_mase','distinct_dates','partial_comparable','source_binding','runtime','unknown_zero','extra'])test('rejects native proof tamper '+change,async({page})=>{
 await open(page);const f=read(change==='partial_comparable'?'partial-h7':change==='unknown_zero'?'unknown-h7':'complete-h14');
 expect(await page.evaluate(async({f,change})=>{const a=f.analysis,m=a.targets[0].models[0];if(change==='prediction')m.prediction.values[0].numerator='3';else if(change==='rolling_scale')m.rolling_origins[0].origin_scale={numerator:'1',denominator:'1'};else if(change==='training_digest')m.rolling_origins[0].training_digest='f'.repeat(64);else if(change==='daily_mse')m.metrics.mse={numerator:'1',denominator:'1'};else if(change==='lead_denominator')m.by_lead[0].metrics.count=29;else if(change==='cumulative_mase')m.cumulative_horizon_metrics.mase={numerator:'0',denominator:'1'};else if(change==='distinct_dates')a.distinct_planned_target_dates=392;else if(change==='partial_comparable')m.directly_comparable=true;else if(change==='source_binding')a.source_binding.projection_hash='f'.repeat(64);else if(change==='runtime'){a.local_runtime.core_sha256.supply_server='f'.repeat(64);const p=window.__supplyProbe;const base=Object.fromEntries(Object.entries(a.local_runtime).filter(([k])=>!['runtime_digest','model_version'].includes(k)));a.local_runtime.runtime_digest=await p.supportDigest(base);a.local_runtime.model_version='supply:'+a.local_runtime.runtime_digest;}else if(change==='unknown_zero')a.targets[0].observed_sum={numerator:'0',denominator:'1'};else a.private_question='secret';return window.__supplyProbe.results.verifySupplyAnalysis(f.source,a);},{f,change})).toBe(false);
});
for(const change of ['number_quantity','false_quantity','calendar','false_eligible','noncanonical_parameter','precision','omit_parameter','unmatched_original','private_text','unknown_model_root','prototype_root'])test('closed source and schema reject '+change,async({page})=>{
 await open(page);const f=read('complete-h14');
 expect(await page.evaluate(async({s,change})=>{const p=window.__supplyProbe,r=p.results;if(change==='unknown_model_root')return r.supplySchemaMatches('UnregisteredNativeModel',s);if(change==='prototype_root')return r.supplySchemaMatches('__proto__',s);if(change==='number_quantity')s.observations[0].quantity.value=0;else if(change==='false_quantity')s.observations[0].quantity.value=false;else if(change==='calendar')s.observations[0].observed_at='2026-02-30T00:00:00.000000Z';else if(change==='false_eligible'){s.member_manifest[0].eligible=0;s.member_manifest_hash=await p.supportDigest(s.member_manifest);}else if(change==='noncanonical_parameter')s.parameters.alpha_size={numerator:'2',denominator:'20'};else if(change==='precision')s.observations[0].quantity.value='0.0000001';else if(change==='omit_parameter')delete s.parameters.alpha_interval;else if(change==='unmatched_original')s.days[0].selections[0].source_id=s.days[1].selections[0].source_id;else s.notes='patient private text';return r.verifySupplySource(s);},{s:f.source,change})).toBe(false);
});
test('historical source audit explicitly differs from current-recipe execution',async({page})=>{
 await open(page);const {source}=read('complete-h14');
 expect(await page.evaluate(async s=>{const r=window.__supplyProbe.results;s.recipe_digest='f'.repeat(64);return[await r.verifySupplySource(s),await r.verifySupplySource(s,{validateCurrentRecipe:false})];},source)).toEqual([false,true]);
});
test('exact fraction and UTC validators fail closed without numeric coercion',async({page})=>{
 await open(page);
 const invalid=[{numerator:0,denominator:'1'},{numerator:false,denominator:'1'},{numerator:'00',denominator:'1'},{numerator:'0',denominator:'2'},{numerator:'2',denominator:'4'},{numerator:'1',denominator:'0'},{numerator:'-0',denominator:'1'},{numerator:'1e3',denominator:'1'}];
 expect(await page.evaluate(values=>values.map(v=>window.__supplyProbe.results.supplyFractionValid(v)),invalid)).toEqual(invalid.map(()=>false));
 expect(await page.evaluate(()=>['2026-02-30T00:00:00.000000Z','2026-01-01T24:00:00.000000Z','2026-01-01T00:00:00.000Z','2026-01-01T00:00:00.000000+00:00'].map(v=>window.__supplyProbe.results.supplyClock(v)))).toEqual([false,false,false,false]);
});
test('cancelled verification does not accept a late full mathematical proof',async({page})=>{
 await open(page);const f=read('complete-h14');
 expect(await page.evaluate(async f=>{let checks=0;return window.__supplyProbe.results.verifySupplyAnalysis(f.source,f.analysis,{current:()=>++checks<3});},f)).toBe(false);
});
