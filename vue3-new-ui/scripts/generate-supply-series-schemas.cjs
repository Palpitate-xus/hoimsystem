const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const code=String.raw`
import builtins,io,json,os,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
def guard(fn):
 def call(file,*a,**k):
  if not isinstance(file,int) and os.path.basename(os.fspath(file)).startswith('.env'):raise RuntimeError('No dotenv access')
  return fn(file,*a,**k)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**k):raise RuntimeError('No schema generation network or hospital database')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from sqlalchemy.orm import declarative_base
db=types.ModuleType('app.database');db.Base=declarative_base();sys.modules['app.database']=db
sys.modules['app.ai.governance']=types.ModuleType('app.ai.governance')
from app.ai import supply_series_input,supply_series,supply_snapshot
models={name:getattr(module,name).model_json_schema() for module,names in ((supply_series_input,('SeriesPeriodRequest','SeriesRequest')),(supply_series,('SeriesCreate','SeriesReview','SeriesRevoke')),(supply_snapshot,('PrivateSnapshot',))) for name in names}
print(json.dumps(models,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const root=path.resolve(__dirname,'..'),target=path.join(root,'src/api/ai/supplySeriesSchemas.json');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const actual=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
const output=JSON.stringify(pack(actual))+'\n';
if(process.argv.includes('--check')){if(fs.readFileSync(target,'utf8')!==output)throw new Error('Supply Series schemas differ from actual closed models');}
else fs.writeFileSync(target,output);
process.stdout.write(`${process.argv.includes('--check')?'Verified':'Generated'} ${Object.keys(actual).length} actual Supply Series schemas, ${Buffer.byteLength(output)} bytes\n`);
