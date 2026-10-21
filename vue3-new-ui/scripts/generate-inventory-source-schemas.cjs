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
def blocked(*a,**k):raise RuntimeError('No external I/O during source schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from sqlalchemy.orm import declarative_base
database=types.ModuleType('app.database');database.Base=declarative_base();sys.modules['app.database']=database
governance=types.ModuleType('app.ai.governance');governance.audit=blocked;sys.modules['app.ai.governance']=governance
from app.ai import inventory_native_source_input as m
classes=[getattr(m,n) for n in ['SourceCreate','SourceReview','SourceRevoke','FrozenIdentity','SourceMetadata','SourceWrapper','CaptureSourceWrapper','CapturePeriod','LegacyCaptureRequest']]
assert 'app.config' not in sys.modules
print(json.dumps({c.__name__:c.model_json_schema() for c in classes},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
const target=path.join(root,'src/api/ai/inventorySourceSchemas.json'),text=JSON.stringify(pack(data))+'\n';
if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Source schemas differ from actual backend declarations');}else fs.writeFileSync(target,text);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(data).length} inventory source schemas: ${Buffer.byteLength(text)} bytes\n`);
