const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from app.ai import drug_label_contract as c
from app.ai.drug_label_projection import DrugLabelPublicSource
names=['Identity','SourceCreate','CAS','RevokeRequest','ProfessionalSign','ProfessionalReference','SourceReview','SourceSnapshot','ProfessionalSnapshot','ProfessionalGovernance','ProfessionalRecord','SourceGovernance','SourceRecord']
models={n:getattr(c,n).model_json_schema() for n in names};models['DrugLabelPublicSource']=DrugLabelPublicSource.model_json_schema()
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':models,'policy':{'comparison_fields':list(c.COMPARISON_FIELDS),'missing_evidence':list(c.UNKNOWN_EVIDENCE),'source_max_utf8_bytes':c.MAX_SOURCE_BYTES}},ensure_ascii=False,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const [name,value]of [['drugLabelSourceSchemas.json',pack(data.models)],['drugLabelSourcePolicy.json',data.policy]]){const file=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';if(check){if(fs.readFileSync(file,'utf8')!==text)throw new Error('Actual drug-label schema/policy differs');}else fs.writeFileSync(file,text);}
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(data.models).length} strict drug-label schemas and source policy\n`);
