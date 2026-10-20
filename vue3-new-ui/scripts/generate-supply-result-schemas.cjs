const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import hashlib,io,json,os,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
def guard(fn):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv')
  return fn(file,*a,**kw)
 return call
import builtins
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**k):raise RuntimeError('No network or hospital credentials')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
gateway=types.ModuleType('app.ai.gateway');gateway.AIExecutionError=RuntimeError;sys.modules['app.ai.gateway']=gateway
governance=types.ModuleType('app.ai.governance');governance.provider_credential=blocked;governance.validate_endpoint=blocked;sys.modules['app.ai.governance']=governance
from app.ai.supply_contract import SupplySource,SupplyAnalysis,SupplyRuntime,RECIPE,INPUT_POLICY,recipe_digest,input_policy_digest
from app.ai.supply_config import runtime_descriptor
from app.ai.supply_probe import SupplyCapabilities
from app.ai.supply_context import SupplyContextBinding
from app.ai.supply_snapshot import PrivateSnapshot
from app.ai.supply_source_input import SourceWrapper, FrozenIdentity, Governance, UnitPayload, DailyPayload
from app.ai.supply_series_input import SeriesRequest,SeriesPeriodRequest
def exact_integer_bounds(value):
 if isinstance(value,list):return [exact_integer_bounds(v) for v in value]
 if not isinstance(value,dict):return value
 result={k:exact_integer_bounds(v) for k,v in value.items()}
 for exclusive,inclusive,delta in [('exclusiveMinimum','minimum',1),('exclusiveMaximum','maximum',-1)]:
  if exclusive in result:
   bound=result.pop(exclusive)
   if result.get('type')!='integer' or type(bound) is not int or abs(bound)>9007199254740990:raise RuntimeError('Unsupported exclusive bound')
   translated=bound+delta
   result[inclusive]=(max if delta==1 else min)(translated,result.get(inclusive,translated))
 return result
r=runtime_descriptor()
assert not any(n in sys.modules for n in ['app.config','app.database','app.models'])
print(json.dumps({'models':{c.__name__:exact_integer_bounds(c.model_json_schema()) for c in [SupplySource,SupplyAnalysis,SupplyRuntime,SupplyCapabilities,SupplyContextBinding,PrivateSnapshot,SourceWrapper,FrozenIdentity,Governance,UnitPayload,DailyPayload,SeriesRequest,SeriesPeriodRequest]},'fixed':{'recipe':RECIPE,'input_policy':INPUT_POLICY,'recipe_digest':recipe_digest(),'input_policy_digest':input_policy_digest(),'core_sha256':r['core_sha256'],'runtime_fields':list(SupplyRuntime.model_fields)}},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const[name,value]of[['supplyResultSchemas.json',pack(data.models)],['supplyFixedPolicy.json',data.fixed]]){
 const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error(name+' differs from actual source');}
 else fs.writeFileSync(target,text);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}: ${Buffer.byteLength(text)} bytes\n`);
}
