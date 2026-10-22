const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs'),root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw Error('Only --check accepted');
const program=String.raw`
import ast,json,pathlib,sys
from app.ai.research_variables_contract import VariableDefinition,DictionaryCreate,BatchCapture,BatchCreate,DefinitionReview
from app.ai.research_cohort_contract import ScopeReference,SourceReview,SourceRevoke
base=pathlib.Path('app/ai')
def constant(filename,name):
 tree=ast.parse((base/filename).read_text());nodes=[n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name)and t.id==name for t in n.targets)];assert len(nodes)==1
 return ast.literal_eval(nodes[0])
columns={key:constant('research_variables_views.py',key) for key in ['COMMON_COLUMNS','DICTIONARY_COLUMNS','BATCH_COLUMNS']}
assert not any(n in sys.modules for n in ('app.database','app.config','app.models','sqlalchemy'))
print(json.dumps({'models':{m.__name__:m.model_json_schema() for m in [VariableDefinition,DictionaryCreate,BatchCapture,BatchCreate,DefinitionReview,ScopeReference,SourceReview,SourceRevoke]},'columns':columns},ensure_ascii=False,separators=(',',':'),sort_keys=True))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',program],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const[name,value]of [['researchVariableSourceSchemas.json',pack(data.models)],['researchVariableSourceColumns.json',data.columns]]){
 const file=path.join(root,'src/api/ai',name),raw=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(file,'utf8')!==raw)throw Error(name+' differs from actual Source contract');}else fs.writeFileSync(file,raw);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}, ${Buffer.byteLength(raw)} bytes\n`);
}
