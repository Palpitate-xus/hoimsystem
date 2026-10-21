const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const{pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import sys,os,builtins,io,socket,json,types,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)) and Path(os.fsdecode(args[0])).name.startswith('.env'):raise RuntimeError('No dotenv')
 if event in {'socket.connect','socket.getaddrinfo'}:raise RuntimeError('No network')
sys.addaudithook(guard)
from sqlalchemy.orm import declarative_base
stub=types.ModuleType('app.database');stub.Base=declarative_base();sys.modules['app.database']=stub
from pydantic import BaseModel
from app.ai import infection_cluster_contract as c,infection_cluster_projection as p,infection_cluster_input as i,infection_cluster_registry as r,infection_cluster_statistics_contract as k,infection_cluster_scenario_input as s,infection_cluster_profile_input as v,infection_cluster_task_contract as t,infection_cluster_task_view_contract as w
from app.ai.infection_cluster_implementation import implementation_descriptor
modules=[c,p,i,r,k,s,v,t,w];models={}
for module in modules:
 for name,value in vars(module).items():
  if isinstance(value,type) and issubclass(value,BaseModel) and value.__module__==module.__name__:
   if name in models:raise ValueError('Ambiguous schema model name '+name)
   models[name]=value.model_json_schema()
assert 'app.config' not in sys.modules
print(json.dumps({'schemas':models,'fixed':{'recipe':k.RECIPE,'recipe_hash':c.digest(k.RECIPE),'statistics_limitations':k.LIMITATIONS,'source_limitations':p.LIMITATIONS,'implementation':implementation_descriptor(),'local_task_text':t.LOCAL_TASK_TEXT,'local_prompt_hash':t.LOCAL_PROMPT_HASH,'whole_bytes':c.MAX_BYTES,'max_roots':c.MAX_ROOTS,'max_json_depth':c.MAX_JSON_DEPTH,'max_json_tokens':c.MAX_JSON_TOKENS}},ensure_ascii=False,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-I','-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:8388608}));
for(const[name,value]of [['infectionClusterSchemas.json',pack(data.schemas)],['infectionClusterFixed.json',data.fixed]]){const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Actual closed infection contracts changed: '+name);}else fs.writeFileSync(target,text);}
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(data.schemas).length} actual infection Source/scenario/profile/statistics/task models\n`);
