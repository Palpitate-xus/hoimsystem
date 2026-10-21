const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from app.ai import research_cohort_contract as c
names=['ScopeCreate','ProjectACLCreate','PatientAuthorizationCreate','AuthorizationReview','SourceReview','SourceRevoke','CaptureRequest','CaseCreate','ResearchCohortSource']
models={n:getattr(c,n).model_json_schema() for n in names}
policy={'scalar_fields':{k:sorted(v) for k,v in c.SCALAR_FIELDS.items()},'date_fields':{k:sorted(v) for k,v in c.DATE_FIELDS.items()},'text_fields':{k:sorted(v) for k,v in c.TEXT_FIELDS.items()},'max_source_bytes':8388608,'max_response_bytes':33554432,'max_criteria_nodes':64,'max_criteria_depth':8,'authorization_limitation':c.AUTHORIZATION_LIMITATION,'protected_case_access_policy':c.PROTECTED_CASE_ACCESS_POLICY}
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':models,'policy':policy},ensure_ascii=False,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const [name,value]of [['researchCohortSourceSchemas.json',pack(data.models)],['researchCohortSourcePolicy.json',data.policy]]){
 const file=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(file,'utf8')!==text)throw new Error('Actual research Source schema/policy differs');}else fs.writeFileSync(file,text);
}
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(data.models).length} strict research Source schemas and exact policy\n`);
