const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{pack}=require('./surgery-schema-storage.cjs');const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check');
const code=String.raw`
import json,sys
from app.ai import deidentification_task_contract as t,deidentification_frozen as f,deidentification_draft as d,deidentification_prompt as p
models={n:getattr(t,n).model_json_schema() for n in ['TaskInput','FrozenProvider','FrozenValidation','RequesterEpoch','FrozenExecution','PublicBinding','FrozenTaskRecord','TaskSourceRecord']}
models.update({n:getattr(f,n).model_json_schema() for n in ['DatabasePromptSnapshot','DeidentificationFrozenPrompt']})
models.update({n:getattr(d,n).model_json_schema() for n in ['SourceDocument','DeidentificationPublicSource','SpanCandidate','DeidentificationDraft']})
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':models,'fixed':{'system_prompt':p.SYSTEM_PROMPT,'native_task_version':p.TASK_VERSION,'categories':d.CATEGORIES,'partial_notice':d.PARTIAL_NOTICE,'max_candidates':d.MAX_CANDIDATES}},ensure_ascii=False,separators=(',',':')))
`;
const actual=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const[name,value]of [['deidentificationTaskSchemas.json',pack(actual.models)],['deidentificationTaskFixed.json',actual.fixed]]){const file=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';if(check){if(fs.readFileSync(file,'utf8')!==text)throw new Error(name+' differs');}else fs.writeFileSync(file,text);process.stdout.write(`${check?'Verified':'Generated'} ${name} ${Buffer.byteLength(text)} bytes\n`);}
