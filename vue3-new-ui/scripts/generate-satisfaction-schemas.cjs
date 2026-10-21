const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import builtins,io,json,os,socket,sys
def guard(fn):
 def call(file,*args,**kwargs):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv during pure schema generation')
  return fn(file,*args,**kwargs)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*args,**kwargs):raise RuntimeError('No network or database during pure schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from app.ai import satisfaction_contract as m
names=['CaptureRequest','CaseCreate','SourceReview','SourceRevoke','Snapshot','CaseMetadata','CaseWrapper','SafeCapture','SafeSnapshot','SatisfactionSource']
assert not any(v in sys.modules for v in ['app.config','app.database','sqlalchemy','dotenv'])
print(json.dumps({'schemas':{n:getattr(m,n).model_json_schema() for n in names},'policy':m.POLICY},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const value=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
const text=JSON.stringify({schemas:pack(value.schemas),policy:value.policy})+'\n',target=path.join(root,'src/api/ai/satisfactionSchemas.json');
if(check){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Satisfaction schemas differ from actual closed backend declarations');}else fs.writeFileSync(target,text);
process.stdout.write(`${check?'Verified':'Generated'} ${Object.keys(value.schemas).length} satisfaction models: ${Buffer.byteLength(text)} bytes\n`);
