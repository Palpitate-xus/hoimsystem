const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');if(process.argv.slice(2).some(x=>x!=='--check'))throw new Error('Only --check');
const code=String.raw`
import ast,json,sys
from pathlib import Path
from typing import Annotated,Literal
from pydantic import Field,model_validator
from app.ai import clinical_training_contract as c,clinical_training_task_contract as task,clinical_training_task_view_contract as view,clinical_training_usage_contract as usage,clinical_training_task_prompt as prompt
models={}
for module,names in [(task,['TrainingTaskSelection','TrainingFeedbackSource','TrainingFeedbackDraft']),(view,['TrainingViewBinding','TrainingTaskMetadata','TrainingTaskPart','TrainingBindingPart']),(usage,['TrainingUsage'])]:
 for name in names:models[name]=getattr(module,name).model_json_schema()
# The actual receipt/ack classes are pure; do not import their SQL services.
namespace={'c':c,'Annotated':Annotated,'Literal':Literal,'Field':Field,'model_validator':model_validator,'TrainingUsage':usage.TrainingUsage}
for name,label in [('clinical_training_receipts','TrainingUsageEvent'),('clinical_training_cancellation','TrainingCancelAcknowledgement')]:
 for node in ast.parse(Path('app/ai/'+name+'.py').read_text()).body:
  if isinstance(node,ast.Assign) and any(isinstance(n,ast.Name) and n.id=='ErrorCode' for n in node.targets) or isinstance(node,ast.ClassDef) and node.name==label:
   exec(compile(ast.Module(body=[node],type_ignores=[]),name,'exec'),namespace)
 models[label]=namespace[label].model_json_schema()
roles={}
for node in ast.parse(Path('app/dependencies.py').read_text()).body:
 if isinstance(node,ast.Assign) and any(isinstance(n,ast.Name) and (n.id.startswith('ROLE_') or n.id=='VALID_USER_ROLES') for n in node.targets):
  exec(compile(ast.Module(body=[node],type_ignores=[]),'actual_roles','exec'),roles)
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy','dotenv'))
print(json.dumps({'models':models,'policy':{'whole_bytes':c.WHOLE_BYTES,'frame_bytes':262144,'raw_text_bytes':65535,'platform_roles':sorted(roles['VALID_USER_ROLES']),'objectives':task.OBJECTIVES,'native_task_version':prompt.PROMPT_VERSION,'system_prompt':prompt.SYSTEM_PROMPT,'packaged_task_prompt':prompt.TASK_PROMPT,'parts':['task','source','binding','result']}},ensure_ascii=False,separators=(',',':')))
`;
const d=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const[name,value]of[['clinicalTrainingTaskSchemas.json',pack(d.models)],['clinicalTrainingTaskPolicy.json',d.policy]]){const file=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';if(check){if(fs.readFileSync(file,'utf8')!==text)throw new Error(name+' differs from actual Task contract');}else fs.writeFileSync(file,text);process.stdout.write(`${check?'Verified':'Generated'} ${name} ${Buffer.byteLength(text)} bytes\n`);}
