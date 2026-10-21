const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');if(process.argv.slice(2).some(x=>x!=='--check'))throw new Error('Only --check');
const code=String.raw`
import json,sys
from app.ai import operations_support_contract as c, operations_support_projection as p, operations_support_registry_contract as r, operations_support_task_contract as t, operations_support_task_view_contract as v, operations_support_task_prompt as prompt, operations_support_usage_contract as usage
models={}
for module,names in [(c,['OperationsOriginal','Redaction','DeclaredOperationsReview']),(p,['PrivateOperationsCollection','ReleasedOperationsDocument','OperationsSupportSource']),(r,['OriginalCreate','ReleaseCreate','ReleaseReview','SourceRevoke','CaseCreate']),(t,['OperationsTaskSelection','OperationsDraft']),(v,['OperationsViewBinding','OperationsTaskMetadata','OperationsTaskPart','OperationsBindingPart']),(usage,['OperationsUsage'])]:
 for name in names:models[name]=getattr(module,name).model_json_schema()
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy','dotenv'))
print(json.dumps({'models':models,'fixed':{'system_prompt':prompt.SYSTEM_PROMPT,'task_prompt':prompt.TASK_PROMPT,'native_task_version':prompt.PROMPT_VERSION,'objectives':prompt.OBJECTIVES,'max_part_bytes':c.MAX_WHOLE_BYTES,'max_text_bytes':c.MAX_TEXT_BYTES,'max_sources':c.MAX_SOURCES}},ensure_ascii=False,separators=(',',':')))
`;
const value=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const [name,body]of [['operationsSupportSchemas.json',pack(value.models)],['operationsSupportFixed.json',value.fixed]]){const file=path.join(root,'src/api/ai',name),text=JSON.stringify(body)+'\n';if(check){if(fs.readFileSync(file,'utf8')!==text)throw new Error(name+' differs from actual pure contract');}else fs.writeFileSync(file,text);process.stdout.write(`${check?'Verified':'Generated'} ${name} ${Buffer.byteLength(text)} bytes\n`);}
