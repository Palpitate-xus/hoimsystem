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
from app.ai import coding_evidence_input as m
names=['CaptureRequest','CaseCreate','RulePackageCreate','SourceReview','SourceRevoke','Governance','PackageMetadata','PackageOriginalProof','Collection','CaseSnapshot','CaseMetadata','CaseOriginalProof','CaseWrapper','PackageWrapper']
assert 'app.config' not in sys.modules
print(json.dumps({n:getattr(m,n).model_json_schema() for n in names},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
const target=path.join(root,'src/api/ai/codingEvidenceSchemas.json'),text=JSON.stringify(pack(data))+'\n';
if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Coding evidence schemas differ from actual closed backend declarations');}else fs.writeFileSync(target,text);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(data).length} coding evidence schemas: ${Buffer.byteLength(text)} bytes\n`);
