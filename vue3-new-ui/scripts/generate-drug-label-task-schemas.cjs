const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),assert=require('node:assert/strict');
const {pack,compact}=require('./surgery-schema-storage.cjs'),root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import base64,gzip,json,sys
from pathlib import Path
from app.ai import drug_label_task_view_contract as v,drug_label_context_contract as c,drug_label_draft as d
from app.ai.drug_label_result import DrugLabelGenerationResult,result_for_draft
from app.ai.drug_label_run_contract import DrugLabelResultPointer,DrugLabelUsageReceipt
names=['DrugLabelShortContext','DrugLabelTaskMetadata','DrugLabelArtifactView','DrugLabelTaskFindings','DrugLabelTaskEvidence','DrugLabelExpandedContext','DrugLabelPreview','DrugLabelRunSummary','DrugLabelRunDetail','DrugLabelRawFrozenJson','DrugLabelFrozenTask','DrugLabelRunTrace']
models={name:getattr(v,name).model_json_schema() for name in names}
models.update(DrugLabelRequest=c.DrugLabelRequest.model_json_schema(),DrugLabelContextBinding=c.DrugLabelContextBinding.model_json_schema(),DrugLabelGenerationResult=DrugLabelGenerationResult.model_json_schema(),DrugLabelResultPointer=DrugLabelResultPointer.model_json_schema(),DrugLabelUsageReceipt=DrugLabelUsageReceipt.model_json_schema())
packed=json.loads(Path('../vue3-new-ui/e2e/fixtures/drug-label-tasks/actual.packed.json').read_text())['chat']
actual=json.loads(gzip.decompress(base64.b64decode(packed['gzip_base64'])))['states']['succeeded']['detail']
source=actual['drug_label_findings']['drug_label_source'];instructions=actual['context_metadata']['instructions_digest']
result=result_for_draft(d.build_draft({'fields':[]},source,instructions),source,instructions).model_dump(mode='json');del result['drug_label_extraction'];result['summary']=result['summary'].replace('0项','{count}项');result['sections']=[{**section,'source_ids':[]} for section in result['sections']]
assert not any(name in sys.modules for name in ['app.config','app.database','app.models','sqlalchemy'])
print(json.dumps({'models':models,'fixed':{'system_prompt':d.SYSTEM_PROMPT,'coverage_note':d.COVERAGE_NOTE,'field_names':list(d.FIELD_NAMES),'scope_note':c.SCOPE_NOTE,'missing_data':list(c.MISSING_DATA),'explanation':result}},ensure_ascii=False,separators=(',',':')))
`;
const value=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
function unpack(v){const nodes=[];for(const node of v.nodes){const decode=x=>Array.isArray(x)?nodes[x[0]]:x;nodes.push(Array.isArray(node)?node.map(decode):Object.fromEntries(Object.entries(node).map(([k,x])=>[k,decode(x)])));}return Object.fromEntries(Object.entries(v.models).map(([k,x])=>[k,structuredClone(nodes[x])]));}
// Reuse the existing full Source definitions at runtime. Reconstructing every
// model must remain byte-for-byte structurally equal to actual compact schemas.
const existing=unpack(require('../src/api/ai/drugLabelSourceSchemas.json')),external={};
for(const[name,schema]of Object.entries(existing)){for(const[k,v]of Object.entries(schema.$defs||{}))external[k]=v;const{$defs,...body}=schema;external[name]=body;}
const full=Object.fromEntries(Object.entries(value.models).map(([k,v])=>[k,compact(v)])),reduced=structuredClone(full),links={};
for(const[name,schema]of Object.entries(reduced)){links[name]=[];for(const[k,v]of Object.entries(schema.$defs||{})){if(external[k]&&JSON.stringify(external[k])===JSON.stringify(v)){delete schema.$defs[k];links[name].push(k);}}}
const packed=pack(reduced),restored=unpack(packed);for(const[name,names]of Object.entries(links))for(const key of names)restored[name].$defs[key]=structuredClone(external[key]);assert.deepEqual(restored,full);
for(const[name,v]of [['drugLabelTaskSchemas.json',packed],['drugLabelTaskSchemaLinks.json',links],['drugLabelTaskFixed.json',value.fixed]]){const target=path.join(root,'src/api/ai',name),raw=JSON.stringify(v)+'\n';if(check)assert.equal(fs.readFileSync(target,'utf8'),raw);else fs.writeFileSync(target,raw);}
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(full).length} actual task schemas, full reconstruction and shared Source definitions\n`);
