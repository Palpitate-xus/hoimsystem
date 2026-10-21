const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');if(process.argv.slice(2).some(x=>x!=='--check'))throw new Error('Only --check');
const code=String.raw`
import ast,json,sys
from pathlib import Path
from app.ai import clinical_training_contract as c,clinical_training_registry_contract as r,clinical_training_reference_contract as ref,clinical_training_scoring as scoring
# Extract the actual pure request class and technical literal field tuples;
# this never imports service modules, settings, ORM or database.
def literals(name,selected,namespace=None):
 ns={} if namespace is None else dict(namespace)
 for node in ast.parse(Path('app/ai/'+name+'.py').read_text()).body:
  if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in selected for t in node.targets):
   exec(compile(ast.Module(body=[node],type_ignores=[]),name,'exec'),{'frozenset':frozenset},ns)
 return ns
headers={}
for name,labels in [('clinical_training_registry',['ORIGIN_COLUMNS','STATE_COLUMNS']),('clinical_training_reviews',['FLAGS','ORIGIN_COLUMNS']),('clinical_training_practice',['ORIGIN_COLUMNS'])]:
 headers[name]=literals(name,labels)
namespace={'c':c,'scoring':scoring}
node=next(n for n in ast.parse(Path('app/ai/clinical_training_practice.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='PracticeCreate')
exec(compile(ast.Module(body=[node],type_ignores=[]),'actual_PracticeCreate','exec'),namespace)
models={}
for module,names in [(c,['PrivateTrainingLesson','PublicTrainingLesson']),(r,['TrainingLessonCreate','TrainingLessonReview','TrainingSourceRevoke','TrainingReviewedLesson']),(ref,['TrainingReferenceSnapshot']),(scoring,['LessonSubmission','PracticeFeedback'])]:
 for name in names:models[name]=getattr(module,name).model_json_schema()
models['PracticeCreate']=namespace['PracticeCreate'].model_json_schema()
roles=literals('clinical_training_write_guard',['TRAINING_STAFF_ROLES'])['TRAINING_STAFF_ROLES']
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy','dotenv'))
print(json.dumps({'models':models,'policy':{'whole_bytes':c.WHOLE_BYTES,'text_bytes':c.TEXT_BYTES,'staff_roles':sorted(roles),'headers':headers}},ensure_ascii=False,separators=(',',':')))
`;
const d=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const[name,value]of[['clinicalTrainingSourceSchemas.json',pack(d.models)],['clinicalTrainingSourcePolicy.json',d.policy]]){const p=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';if(check){if(fs.readFileSync(p,'utf8')!==text)throw new Error(name+' differs from actual Source contract');}else fs.writeFileSync(p,text);process.stdout.write(`${check?'Verified':'Generated'} ${name} ${Buffer.byteLength(text)} bytes\n`);}
