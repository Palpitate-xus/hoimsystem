const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import builtins,hashlib,io,json,os,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
def guard(fn):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv')
  return fn(file,*a,**kw)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**k):raise RuntimeError('No network or hospital database during schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from sqlalchemy.orm import declarative_base
db=types.ModuleType('app.database');db.Base=declarative_base();sys.modules['app.database']=db
from app.ai.coding_evidence_context import CodingContextBinding,SCOPE_NOTE,MISSING_DATA
from app.ai.coding_evidence_contract import CodingEvidenceDraft
from app.ai.coding_evidence_frozen import CodingFrozenProvider,CodingFrozenValidation
from app.ai.coding_evidence_result import CodingGenerationResult,WARNINGS,MISSING
from app.ai.coding_evidence_prompt import CODING_SYSTEM_PROMPT
assert 'app.config' not in sys.modules
print(json.dumps({'schemas':{m.__name__:m.model_json_schema() for m in [CodingContextBinding,CodingEvidenceDraft,CodingGenerationResult,CodingFrozenProvider,CodingFrozenValidation]},'fixed':{'schema_version':'coding_ui_fixed_v1','scope_note':SCOPE_NOTE,'context_missing':list(MISSING_DATA),'output_warnings':WARNINGS,'output_missing':MISSING,'system_prompt_digest':hashlib.sha256(CODING_SYSTEM_PROMPT.encode()).hexdigest()}},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const[name,value]of [['codingResultSchemas.json',pack(data.schemas)],['codingFixedPolicy.json',data.fixed]]){
 const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error(`${name} differs from actual backend declarations`);}else fs.writeFileSync(target,text);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}: ${Buffer.byteLength(text)} bytes\n`);
}
