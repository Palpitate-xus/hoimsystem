const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import builtins,hashlib,io,json,os,re,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
def guard(fn):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv')
  return fn(file,*a,**kw)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**k):raise RuntimeError('No network or database engine during schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
import sqlalchemy
sqlalchemy.create_engine=blocked
from sqlalchemy.orm import declarative_base
db=types.ModuleType('app.database');db.Base=declarative_base();sys.modules['app.database']=db
from app.ai.charge_reconciliation_context import ChargeContextBinding,SCOPE_NOTE,MISSING_DATA,charge_evidence
from app.ai.charge_reconciliation_draft import ChargeReconciliationDraft,KINDS,source_hash
from app.ai.charge_reconciliation_frozen import ChargeFrozenProvider,ChargeFrozenValidation
from app.ai.charge_reconciliation_result import ChargeReconciliationResult,WARNINGS,MISSING,result_for_draft
from app.ai.charge_reconciliation_view_contract import ChargeArtifactRecord,ChargeUsage,ChargeReceiptEvent,ChargeResultReference
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
sizes={'charges':11,'orders':13,'order_items':17,'executions':19,'administrations':23}
sample={'schema_version':'charge_ledger_source_v1','source_id':'charge_case:synthetic-template'}
for group,kind in KINDS.items():sample[group]=[{'source_id':'charge_'+kind+':'+format(i,'064x')} for i in range(sizes[group])]
for i,row in enumerate(sample['charges']):row['order_association']='not_recorded' if i<2 else 'recorded_same_admission' if i<5 else 'unresolved_or_out_of_scope'
draft=ChargeReconciliationDraft(schema_version='charge_reconciliation_draft_v1',source_id=sample['source_id'],source_projection_hash=source_hash(sample),coverage='partial_questions_no_completeness_or_correctness_claim',observations=[])
result=result_for_draft(sample,draft,source_hash(sample)).model_dump(mode='json')
markers={0:'observations_count',11:'charges_count',13:'orders_count',17:'order_items_count',19:'executions_count',23:'administrations_count',2:'association_not_recorded',3:'association_same_admission',6:'association_unresolved'}
def template(text):return re.sub(r'\d+',lambda match:'{'+markers[int(match.group())]+'}',text)
bound=ChargeContextBinding(schema_version='charge_context_binding_v1',case_snapshot_id='00000000-0000-0000-0000-000000000069',patient_id=1,admission_id='00000000-0000-0000-0000-000000000070',source_id='charge_case:00000000-0000-0000-0000-000000000069:'+('a'*12),content_hash='a'*64,publication_governance_hash='b'*64,projection_hash='c'*64,collection_digest='d'*64,manifest_hash='e'*64,policy_hash='f'*64,captured_at='2026-10-21T00:00:00.000000Z',float_capture_basis='sqlite_orm_float_only',department_ids=[]).model_dump(mode='json')
evidence=charge_evidence(bound)
fixed={'evidence_title':evidence['title'],'evidence_kind':evidence['kind'],'python_whitespace_codepoints':[i for i in range(0x110000) if chr(i).isspace()],'schema_version':'charge_ui_fixed_v1','scope_note':SCOPE_NOTE,'context_missing':list(MISSING_DATA),'output_warnings':WARNINGS,'output_missing':MISSING,'system_prompt_digest':hashlib.sha256(CHARGE_RECONCILIATION_SYSTEM_PROMPT.encode()).hexdigest(),'result_templates':{'summary':template(result['summary']),'sections':[{'title':row['title'],'content':template(row['content'])} for row in result['sections']]}}
models=[ChargeContextBinding,ChargeReconciliationDraft,ChargeReconciliationResult,ChargeFrozenProvider,ChargeFrozenValidation,ChargeArtifactRecord,ChargeUsage,ChargeReceiptEvent,ChargeResultReference]
assert 'app.config' not in sys.modules and 'app.ai.runtime' not in sys.modules
print(json.dumps({'schemas':{m.__name__:m.model_json_schema() for m in models},'fixed':fixed},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const[name,value]of [['chargeReconciliationResultSchemas.json',pack(data.schemas)],['chargeReconciliationUiFixed.json',data.fixed]]){
 const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error(`${name} differs from actual backend declarations`);}else fs.writeFileSync(target,text);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}: ${Buffer.byteLength(text)} bytes\n`);
}
