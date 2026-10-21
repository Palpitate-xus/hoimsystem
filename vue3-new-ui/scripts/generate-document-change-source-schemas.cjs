const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(value=>value!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from pydantic import TypeAdapter
from app.ai import document_change_contract as c
names=['ScopeCaptureRequest','ScopeCreate','LinkCreate','ReviewRequest','TargetSnapshot','LinkRecord','ScopeRecord','Inventory','DocumentChangeSource']
models={n:getattr(c,n).model_json_schema() for n in names}
models['RevokeRequest']=c.e.RevokeRequest.model_json_schema()
models['TargetReference']=TypeAdapter(c.TargetReference).json_schema()
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps(models,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const models=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
const target=path.join(root,'src/api/ai/documentChangeSourceSchemas.json'),content=JSON.stringify(pack(models))+'\n';
if(check){if(fs.readFileSync(target,'utf8')!==content)throw new Error('Document change Source schemas differ from actual strict types');}else fs.writeFileSync(target,content);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(models).length} document change Source schemas, ${Buffer.byteLength(content)} bytes\n`);
