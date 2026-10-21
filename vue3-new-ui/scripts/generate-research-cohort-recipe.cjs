const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),source=path.join(root,'../fastapi_be/app/ai'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
// Read literal assignments through the standard-library AST, without importing
// application modules, configuration, SQLAlchemy or evaluating source code.
const code=String.raw`import ast,json,sys,pathlib
root=pathlib.Path(sys.argv[1]);wanted={'research_cohort_collection.py':['FAMILY_COLUMNS','FAMILY_KEYS','FAMILY_CLOCKS'],'research_cohort_evaluator.py':['LIMITATIONS']};result={}
for filename,names in wanted.items():
 tree=ast.parse((root/filename).read_text())
 for node in tree.body:
  if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in names:
   result[node.targets[0].id]=ast.literal_eval(node.value)
 assert all(name in result for name in names)
assert not any(name in sys.modules for name in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps(result,ensure_ascii=False,separators=(',',':')))`;
const values=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-I','-S','-c',code,source],{encoding:'utf8',maxBuffer:2097152}));
const names=['research_cohort_contract.py','research_cohort_collection.py','research_cohort_evaluator.py','research_cohort_snapshot.py'];
const policy={schema_version:'research_cohort_client_recipe_v1',recipe:{rule_id:'research_recorded_predicates_kleene_v1',implementation_sha256:Object.fromEntries(names.map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(source,name))).digest('hex')]))},family_columns:values.FAMILY_COLUMNS,family_keys:values.FAMILY_KEYS,family_clocks:values.FAMILY_CLOCKS,evaluation_limitations:values.LIMITATIONS,max_roots:8192,max_bytes:8388608};
const file=path.join(root,'src/api/ai/researchCohortRecipe.json'),text=JSON.stringify(policy)+'\n';if(check){if(fs.readFileSync(file,'utf8')!==text)throw new Error('Actual research recipe differs; no current-algorithm claim allowed');}else fs.writeFileSync(file,text);
process.stdout.write(`${check?'Verified':'Generated'} exact research recorded-predicate recipe and whole-family columns\n`);
