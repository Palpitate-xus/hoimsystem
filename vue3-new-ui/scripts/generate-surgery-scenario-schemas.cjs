const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{pack}=require('./surgery-schema-storage.cjs');
const python=String.raw`import builtins, io, json, os, socket, sys, types
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
def guard(factory):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file))=='.env':raise RuntimeError('No dotenv')
  return factory(file,*a,**kw)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**kw):raise RuntimeError('No network for schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from sqlalchemy.orm import declarative_base
database=types.ModuleType('app.database');database.Base=declarative_base();sys.modules['app.database']=database
governance=types.ModuleType('app.ai.governance');governance.provider_credential=blocked;governance.validate_endpoint=blocked;sys.modules['app.ai.governance']=governance
gateway=types.ModuleType('app.ai.gateway');gateway.AIExecutionError=RuntimeError;sys.modules['app.ai.gateway']=gateway

from app.ai.surgery_snapshot import PrivateSnapshot,SourceMetadata,RegistryMetadata,CaseMetadata,COLLECTION_FIELDS,DIGEST_FIELDS
from app.ai.surgery_scenario_input import ScenarioCreate
from app.ai.surgery_collection import CaptureRequest
from app.ai.surgery_contract import SurgerySource,SurgeryAnalysis
from app.ai.surgery_context import SurgeryContextBinding
models=(PrivateSnapshot,SourceMetadata,RegistryMetadata,CaseMetadata,ScenarioCreate,CaptureRequest,SurgerySource,SurgeryAnalysis,SurgeryContextBinding)
print(json.dumps({"models":{model.__name__:model.model_json_schema() for model in models},"collection_fields":sorted(COLLECTION_FIELDS),"digest_fields":list(DIGEST_FIELDS)},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check is supported');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',python],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const [name,value] of [['surgeryScenarioSchemas.json',pack(data.models)],['surgeryScenarioFields.json',{collection:data.collection_fields,digests:data.digest_fields}]]){const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error(name+' differs from actual declarations');}else fs.writeFileSync(target,text);process.stdout.write((check?'Verified':'Generated')+' '+name+': '+Buffer.byteLength(text)+' bytes\n');}
