const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import ast,json,sys
from pathlib import Path
from typing import Annotated,Literal
from pydantic import BaseModel,Field
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as s
from app.ai import rca_evidence_case_contract as k
from app.ai import rca_evidence_task_contract as t
from app.ai import rca_evidence_storage_contract as f
from app.ai import rca_evidence_task_views as v
from app.ai import rca_evidence_task_wire_contract as w
from app.ai import rca_evidence_result as r
models={}
for module in (c,i,s,k,t,f,v,w,r):
 for name,value in vars(module).items():
  if isinstance(value,type) and issubclass(value,BaseModel) and value.__module__==module.__name__ and name!='StrictModel':
   assert name not in models,name
   models[name]=value.model_json_schema()
# Directory classes are actual source AST, without importing SQL, settings or DB.
file=Path('app/ai/rca_evidence_directory.py')
tree=ast.parse(file.read_text())
namespace=dict(c=c,i=i,Annotated=Annotated,Literal=Literal,Field=Field)
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.ClassDef)],type_ignores=[]),str(file),'exec'),namespace)
for name in ('OriginalMetadata','CaseMetadata','GrantMetadata','Directory'):
 models[name]=namespace[name].model_json_schema()
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps(models,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const schemas=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:8388608}));
const target=path.join(root,'src/api/ai/rcaEvidenceSchemas.json'),content=JSON.stringify(pack(schemas))+'\n';
if(check){if(fs.readFileSync(target,'utf8')!==content)throw new Error('RCA schemas differ from actual closed backend types');}else fs.writeFileSync(target,content);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(schemas).length} RCA models, ${Buffer.byteLength(content)} bytes\n`);
