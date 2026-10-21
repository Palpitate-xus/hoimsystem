const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import io,json,os,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
def guard(fn):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv')
  return fn(file,*a,**kw)
 return call
import builtins
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**k):raise RuntimeError('No network or hospital access')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
gateway=types.ModuleType('app.ai.gateway');gateway.AIExecutionError=RuntimeError;sys.modules['app.ai.gateway']=gateway
governance=types.ModuleType('app.ai.governance');governance.provider_credential=blocked;governance.validate_endpoint=blocked;sys.modules['app.ai.governance']=governance
from app.ai.inventory_probe import InventoryCapabilities
from app.ai.inventory_contract import InventorySource,InventoryAnalysis,InventoryRuntime,RECIPE,INPUT_POLICY,recipe_digest,input_policy_digest
from app.ai.inventory_config import runtime_descriptor
from app.ai.inventory_context import InventoryContextBinding,SCOPE_NOTE,MISSING_DATA
assert not any(n in sys.modules for n in ['app.config','app.database','app.models','sqlalchemy'])
r=runtime_descriptor()
print(json.dumps({'models':{c.__name__:c.model_json_schema() for c in [InventorySource,InventoryAnalysis,InventoryRuntime,InventoryContextBinding,InventoryCapabilities]},'fixed':{'recipe':RECIPE,'input_policy':INPUT_POLICY,'recipe_digest':recipe_digest(),'input_policy_digest':input_policy_digest(),'core_sha256':r['core_sha256'],'runtime_fields':list(InventoryRuntime.model_fields),'scope_note':SCOPE_NOTE,'missing_data':list(MISSING_DATA)}},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const[name,value]of[['inventoryResultSchemas.json',pack(data.models)],['inventoryFixedPolicy.json',data.fixed]]){
 const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error(name+' differs from actual source');}else fs.writeFileSync(target,text);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}: ${Buffer.byteLength(text)} bytes\n`);
}
