const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import builtins,io,json,os,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
def guard(fn):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv')
  return fn(file,*a,**kw)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**k):raise RuntimeError('No network or hospital database during schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from sqlalchemy.orm import declarative_base
db=types.ModuleType('app.database');db.Base=declarative_base();sys.modules['app.database']=db
from app.ai import charge_reconciliation_contract as m
names=['SQLFloatWitness','StoredFloat','CaptureRequest','CaseCreate','SourceReview','SourceRevoke','PatientBinding','AdmissionOriginal','ChargeOriginal','OrderOriginal','OrderItemOriginal','ExecutionOriginal','AdministrationOriginal','Collection','CaseSnapshot','CaseMetadata','CaseOriginalProof']
assert 'app.config' not in sys.modules
print(json.dumps({'schemas':{n:getattr(m,n).model_json_schema() for n in names},'policy':m.POLICY},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
const target=path.join(root,'src/api/ai/chargeReconciliationSourceSchemas.json'),text=JSON.stringify(pack(data.schemas))+'\n';
if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Charge evidence schemas differ from actual closed backend declarations');}else fs.writeFileSync(target,text);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(data.schemas).length} charge evidence schemas: ${Buffer.byteLength(text)} bytes\n`);

const policyTarget=path.join(root,'src/api/ai/chargeReconciliationFixedPolicy.json'),policyText=JSON.stringify(data.policy)+'\n';if(check){if(fs.readFileSync(policyTarget,'utf8')!==policyText)throw new Error('Actual charge projection policy differs');}else fs.writeFileSync(policyTarget,policyText);
