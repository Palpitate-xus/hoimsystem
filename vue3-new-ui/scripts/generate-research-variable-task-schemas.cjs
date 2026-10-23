const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const program=String.raw`
import ast,hashlib,json,pathlib,sys
from typing import Annotated,Literal
from pydantic import Field
from app.ai import research_variables_contract as originals
from app.ai import research_variables_draft as literal
from app.ai import research_variables_task_contract as task
from app.ai import research_variables_task_binding as binding
from app.ai import research_variables_storage_contract as storage
from app.ai import research_variables_task_result as result
from app.ai import research_variables_task_view_contract as view
from app.ai import research_variables_fields as fields
from app.ai import research_variables_prompt as prompt
from app.ai.research_cohort_contract import SHA,UTC,UUID,Positive,StrictModel
base=pathlib.Path('app/ai')
# Only the named declarative class AST is evaluated; the SQL module is never
# imported. Keep its actual annotations and fields instead of a JS DTO copy.
namespace={'Annotated':Annotated,'Literal':Literal,'Field':Field,'SHA':SHA,'UTC':UTC,'UUID':UUID,'Positive':Positive,'StrictModel':StrictModel,'MAX_WIRE_BYTES':task.MAX_WIRE_BYTES,'RESULT_SCHEMA':'research_variable_result_v1','VariableUsageReceipt':storage.VariableUsageReceipt}
extracted=[]
for filename,name in [('research_variables_result_storage.py','VariableResultReference'),('research_variables_receipts.py','VariableReceiptRecord')]:
 tree=ast.parse((base/filename).read_text());nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name];assert len(nodes)==1
 node=nodes[0];assert not node.decorator_list and len(node.bases)==1 and isinstance(node.bases[0],ast.Name) and node.bases[0].id=='StrictModel'
 assert all(isinstance(n,(ast.AnnAssign,ast.Expr)) for n in node.body)
 exec(compile(ast.Module(body=[node],type_ignores=[]),filename,'exec'),namespace);extracted.append(namespace[name])
classes=[originals.VariableDefinition,originals.DictionaryCreate,originals.BatchCapture,originals.BatchCreate,originals.DefinitionReview,literal.LiteralDocument,literal.Candidate,literal.VariableDraft,task.VariableTaskSelection,task.PatientAuthorizationAnchor,task.VariableTaskAccessManifest,task.VariableSourceRecipe,task.VariableSourceRecord,task.VariableTaskSource,binding.VariableTaskBinding,storage.VariableFrozenProvider,storage.VariableFrozenValidation,storage.VariablePromptOrigin,storage.VariableBindingReference,storage.VariableShortContext,storage.VariableTaskSnapshot,storage.VariableUsageReceipt,result.VariableExtractionDraft,result.VariableGenerationResult,view.VariableTaskAnchorRecord,*extracted]
def constant(filename,name):
 tree=ast.parse((base/filename).read_text());values=[n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)];assert len(values)==1
 return ast.literal_eval(values[0])
policies=constant('research_variables_capture_proof.py','POLICIES')
snapshot_keys=sorted(constant('research_variables_snapshot.py','SNAPSHOT_KEYS'))
record_keys=sorted(constant('research_variables_capture_proof.py','RECORD_KEYS'))
family_clocks=constant('research_cohort_collection.py','FAMILY_CLOCKS')
lifecycle=constant('research_variables_collection.py','LIFECYCLE')
source=json.loads(pathlib.Path('tests/fixtures/research_variables_task/actual-public-source.json').read_text())
source=task.VariableTaskSource.model_validate(source)
draft=result.bind_draft({'schema_version':'research_variable_draft_v1','coverage':'partial_candidates_only','candidates':[]},source,'1'*64)
explanation=result.result_for_draft(draft,source,'1'*64).model_dump(mode='json');explanation.pop('research_variable_extraction')
assert explanation['summary'].count('0')==1
explanation['summary']=explanation['summary'].replace('0','{count}')
for section in explanation['sections']:
 section['source_ids']=['{source_id}'] if section['source_ids'] else []
fixed={'feature_key':task.FEATURE_KEY,'input_mode':task.INPUT_MODE,'reference_key':task.REFERENCE_KEY,'source_domain':task.SOURCE_DOMAIN,'system_prompt':prompt.SYSTEM_PROMPT,'task_prompt':prompt.DEFAULT_TASK_PROMPT,'task_version':prompt.VARIABLE_TASK_VERSION,'limitations':list(fields.LIMITATIONS),'variable_fields':fields.VARIABLE_FIELDS,'policies':policies,'snapshot_keys':snapshot_keys,'record_keys':record_keys,'family_clocks':family_clocks,'lifecycle':lifecycle,'max_wire_bytes':task.MAX_WIRE_BYTES,'max_run_text_bytes':task.MAX_RUN_TEXT_BYTES,'max_binding_bytes':task.MAX_BINDING_BYTES,'max_json_depth':task.MAX_JSON_DEPTH,'max_json_nodes':task.MAX_JSON_NODES,'source_recipe':{'rule_id':'research_variable_literal_projection_v1','implementation_sha256':{name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in task.RECIPE_FILES}},'explanation':explanation,'hmac_validation_basis':'server_frozen_projection_anchor_and_ordered_original_literal_reconstruction_not_client_hmac_recomputation'}
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':{m.__name__:m.model_json_schema() for m in classes},'fixed':fixed},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',program],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const [name,value]of [['researchVariableTaskSchemas.json',pack(data.models)],['researchVariableTaskFixed.json',data.fixed]]){
 const file=path.join(root,'src/api/ai',name),content=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(file,'utf8')!==content)throw new Error(name+' differs from actual pure contract');}else fs.writeFileSync(file,content);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}, ${Buffer.byteLength(content)} bytes\n`);
}
