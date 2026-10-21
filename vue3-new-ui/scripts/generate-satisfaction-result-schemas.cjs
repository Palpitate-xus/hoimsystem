const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const{pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import ast,builtins,io,json,os,socket,sys
from pathlib import Path
def guard(fn):
 def call(file,*args,**kwargs):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv during pure result schema generation')
  return fn(file,*args,**kwargs)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*args,**kwargs):raise RuntimeError('No network or database during pure result schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from typing import Annotated,Literal
from pydantic import Field,model_validator
from app.ai.satisfaction_contract import SHA,UUID,StrictModel
from app.ai.satisfaction_draft import SatisfactionEvidenceDraft
from app.ai.satisfaction_result import SatisfactionGenerationResult,WARNINGS,MISSING
from app.ai.satisfaction_context import SatisfactionContextBinding,SatisfactionFrozenCase,FEATURE_KEY,SCOPE_NOTE,MISSING_DATA
from app.ai.satisfaction_frozen import SatisfactionFrozenProvider,SatisfactionFrozenValidation
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT
# Compile the actual two pure declarations, without importing the receipt
# module's SQL services or replacing their fields with a second schema.
tree=ast.parse(Path('app/ai/satisfaction_receipts.py').read_text())
nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'SatisfactionUsage','SatisfactionUsageEvent'} or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TokenCount' for t in n.targets)]
assert len(nodes)==3
exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual_satisfaction_receipt_declarations','exec'),globals())
names=['SatisfactionEvidenceDraft','SatisfactionGenerationResult','SatisfactionContextBinding','SatisfactionFrozenCase','SatisfactionFrozenProvider','SatisfactionFrozenValidation','SatisfactionUsage','SatisfactionUsageEvent']
assert not any(v in sys.modules for v in ['app.config','app.database','sqlalchemy','dotenv'])
print(json.dumps({'schemas':{n:globals()[n].model_json_schema() for n in names},'constants':{'warnings':WARNINGS,'missing_data':MISSING,'feature_key':FEATURE_KEY,'scope_note':SCOPE_NOTE,'context_missing_data':MISSING_DATA,'system_prompt':SATISFACTION_SYSTEM_PROMPT}},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const value=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
const text=JSON.stringify({schemas:pack(value.schemas),constants:value.constants})+'\n',target=path.join(root,'src/api/ai/satisfactionResultSchemas.json');
if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Satisfaction result schemas differ from actual closed backend declarations');}else fs.writeFileSync(target,text);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(value.schemas).length} satisfaction result models: ${Buffer.byteLength(text)} bytes\n`);
