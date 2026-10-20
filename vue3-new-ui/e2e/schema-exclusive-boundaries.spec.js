const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('../scripts/surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),original=fs.readFileSync(path.join(root,'src/api/sofaSchema.js'),'utf8');
const source=original.replace(/^import registry.*$/m,`const registry=${fs.readFileSync(path.join(root,'src/api/sofaSchemas.json'),'utf8')};`).replace(/^export \{.*$/gm,'').replace(/^export /gm,'')+'\nwindow.schemaProbe={generatedSchemaMatches,decodeGeneratedSchemas:unpackRegistry};';
const actual=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',"import json,sys;from app.ai.supply_source_input import UnitCreate;assert 'app.database' not in sys.modules and 'app.config' not in sys.modules;print(json.dumps(UnitCreate.model_json_schema()['properties']['item_id']))"],{cwd:path.resolve(root,'../fastapi_be'),encoding:'utf8'}));
test('actual strict SKU Positive schema retains exclusive zero boundary through static DAG storage',async({page})=>{
 await page.setContent('<p>实际闭集schema数值边界</p>');await page.addScriptTag({content:source});
 const value=JSON.parse(JSON.stringify(actual));delete value.title;
 const packed=pack({ActualPositive:value}),results=await page.evaluate(packed=>{const p=window.schemaProbe,models=p.decodeGeneratedSchemas(packed);return{schema:models.ActualPositive,values:[-1,0,1,2147483647,2147483648,true,false,'1',1.1,null,NaN,Infinity].map(v=>p.generatedSchemaMatches(models,'ActualPositive',v))};},packed);
 expect(results.schema).toEqual(value);expect(results.schema.exclusiveMinimum).toBe(0);expect(results.values).toEqual([false,false,true,true,false,false,false,false,false,false,false,false]);
});
test('numeric exclusive bounds are strict, conjunctive and malformed declarations fail closed',async({page})=>{
 await page.setContent('<p>实际闭集schema严格比较</p>');await page.addScriptTag({content:source});
 const results=await page.evaluate(()=>{const p=window.schemaProbe,valid={type:'number',exclusiveMinimum:0.5,exclusiveMaximum:2.5,minimum:0,maximum:3},check=(schema,value)=>p.generatedSchemaMatches({Boundary:schema},'Boundary',value);return{values:[0,0.5,0.5000001,2,2.5,3,NaN,Infinity,true,'1'].map(v=>check(valid,v)),malformed:[true,null,'0',NaN,Infinity,9007199254740992].flatMap(bound=>['exclusiveMinimum','exclusiveMaximum'].map(key=>check({type:'number',[key]:bound},1))),both:[check({type:'integer',minimum:2,exclusiveMinimum:0,maximum:3,exclusiveMaximum:3},1),check({type:'integer',minimum:2,exclusiveMinimum:0,maximum:3,exclusiveMaximum:3},2),check({type:'integer',minimum:2,exclusiveMinimum:0,maximum:3,exclusiveMaximum:3},3)],unknown:check({type:'integer',exclusiveLower:0},1)};});
 expect(results.values).toEqual([false,false,true,true,false,false,false,false,false,false]);expect(results.malformed).toEqual(Array(12).fill(false));expect(results.both).toEqual([false,true,false]);expect(results.unknown).toBe(false);
});
