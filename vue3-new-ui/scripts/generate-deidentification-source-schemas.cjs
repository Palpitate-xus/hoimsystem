const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const{pack}=require('./surgery-schema-storage.cjs'),root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check');
// Read actual pure contracts and literal SQL column declarations. No settings,
// application metadata import, database engine, credential or dotenv is needed.
const code=String.raw`
import ast,json,pathlib,sys
from app.ai import deidentification_contract as c,research_cohort_contract as r
from app.ai import deidentification_draft as d
names=['FieldSelection','PatientScopeRequest','CaptureRequest','CaseCreate','SpanEdit','ReviewCreate','ResidualReview','GovernanceReview','GovernanceRevoke','ReleaseCreate','ReleaseAuthorityReview']
models={n:getattr(c,n).model_json_schema() for n in names}
models.update({n:getattr(r,n).model_json_schema() for n in ['ScopeCreate','ProjectACLCreate','PatientAuthorizationCreate']})
models['SourceDocument']=d.SourceDocument.model_json_schema()
tree=ast.parse(pathlib.Path('app/ai/research_cohort_collection.py').read_text())
constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['FAMILY_COLUMNS','FAMILY_KEYS','FAMILY_CLOCKS']}
model_tree=ast.parse(pathlib.Path('app/models.py').read_text());classes={n.name:n for n in model_tree.body if isinstance(n,ast.ClassDef)}
types={}
for family,cls in dict(patient_demographics='Patient',registrations='Registration',admissions='Admission',medical_records='MedicalRecord',structured_medical_records='StructuredMedicalRecord').items():
 declarations={n.targets[0].id:n.value for n in classes[cls].body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
 fields={}
 for name in constants['FAMILY_COLUMNS'][family]:
  node=declarations[name];assert isinstance(node,ast.Call) and node.func.id=='Column'
  typ=node.args[0];typ=typ.func.id if isinstance(typ,ast.Call) else typ.id
  assert typ in ['Integer','String','Text','Date','DateTime'],(family,name,typ)
  fields[name]=typ
 types[family]=fields
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':models,'policy':{'text_fields':c.TEXT_FIELDS,'limitations':c.LIMITATIONS,'masks':c.MASKS,'family_columns':constants['FAMILY_COLUMNS'],'family_keys':constants['FAMILY_KEYS'],'family_clocks':constants['FAMILY_CLOCKS'],'raw_column_types':types,'max_bytes':c.MAX_BYTES,'max_roots':c.MAX_ROOTS,'max_documents':c.MAX_DOCUMENTS,'max_edits':c.MAX_EDITS,'source_roles':sorted(c.SOURCE_ROLES)}},ensure_ascii=False,separators=(',',':')))
`;
const actual=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const[name,value]of [['deidentificationSourceSchemas.json',pack(actual.models)],['deidentificationSourcePolicy.json',actual.policy]]){
 const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error(name+' differs from actual contracts');}else fs.writeFileSync(target,text);
 process.stdout.write(`${check?'Verified':'Generated'} ${name} ${Buffer.byteLength(text)} bytes\n`);
}
