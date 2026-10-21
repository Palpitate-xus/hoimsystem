const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from app.ai.research_cohort_draft import ResearchCohortDraft,COVERAGE,MAX_BYTES,MAX_TARGETS
from app.ai.research_cohort_prompt import RESEARCH_SYSTEM_PROMPT,RESEARCH_TASK_VERSION,packaged_task_prompt
from app.ai.research_cohort_result import SUMMARY,LIMITATIONS
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':{'ResearchCohortDraft':ResearchCohortDraft.model_json_schema()},'constants':{'coverage':COVERAGE,'max_bytes':MAX_BYTES,'max_targets':MAX_TARGETS,'system_prompt':RESEARCH_SYSTEM_PROMPT,'native_task_version':RESEARCH_TASK_VERSION,'packaged_task_prompt':packaged_task_prompt(),'summary':SUMMARY,'limitations':list(LIMITATIONS)}},ensure_ascii=False,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:1048576}));
for(const[name,value]of [['researchCohortResultSchemas.json',pack(data.models)],['researchCohortResultPolicy.json',data.constants]]){
 const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Actual research question/result schema differs');}else fs.writeFileSync(target,text);
}
process.stdout.write(`${check?'Verified':'Generated'} pure research question schema and fixed System/result policy\n`);
