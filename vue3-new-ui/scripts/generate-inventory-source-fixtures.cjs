const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source='/tmp/hoim-inventory-source-ui-final-real-fixtures.json',target=path.resolve(__dirname,'../e2e/fixtures/inventory-source/actual.json'),raw=fs.readFileSync(source,'utf8'),value=JSON.parse(raw),text=JSON.stringify(value)+'\n';
assert.equal(value.schema_version,'inventory_source_actual_main_fixtures_v1');
for(const[k,v]of Object.entries(value.kinds)){assert.equal(k,v.published.source_kind);assert.equal(v.draft.source_record_id,v.published.source_record_id);assert.deepEqual(v.create_request.payload,v.published.payload);}
if(process.argv.slice(2).some(x=>x!=='--check'))throw new Error('Only --check supported');
if(process.argv.includes('--check'))assert.deepEqual(JSON.parse(fs.readFileSync(target,'utf8')),value);else{fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,text);}
process.stdout.write(`${process.argv.includes('--check')?'Verified':'Copied'} actual main-JWT inventory Source DTOs: ${Buffer.byteLength(text)} bytes\n`);
