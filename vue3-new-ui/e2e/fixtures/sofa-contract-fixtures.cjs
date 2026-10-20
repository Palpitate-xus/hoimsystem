const path=require("node:path"),{execFileSync}=require("node:child_process");
// Actual strict model validation is the structural oracle. These are synthetic
// contract examples, not actual ORM assessments, calculated scores or clinical validation.
const script=String.raw`
import copy,json,socket,sys,types
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
def blocked(*a,**kw):raise RuntimeError('Contract fixture cannot open a socket')
socket.socket.connect=blocked
from sqlalchemy.orm import declarative_base
database=types.ModuleType('app.database');database.Base=declarative_base();sys.modules['app.database']=database
from app.ai import sofa_contract as public,sofa_sources as private
from tests.test_ai_sofa_contract import empty_source
cases=[]
def add(name,model,data,root=None,definition=None):
 try:model.model_validate(data);valid=True
 except ValueError:valid=False
 cases.append(dict(name=name,schema=root or model.__name__,definition=definition,value=data,valid=valid))
source=public.SofaSource.model_validate(empty_source()).model_dump()
add('实际typed空清单保留未知而非正常',public.SofaSource,source)
bad=copy.deepcopy(source);bad['patient_id']=11;add('公开投影禁止本地患者字段',public.SofaSource,bad)
bad=copy.deepcopy(source);bad['population']['applicability_confirmed']=1;add('确认不能数值替代bool',public.SofaSource,bad)
bad=copy.deepcopy(source);bad.pop('respiratory_support_observations');add('完整根分支不能省略',public.SofaSource,bad)
for name,value in [('原数值字符串零','0.00000000'),('原缺测',None),('数值零不能强转',0),('指数写法不可改原精度','1e-3')]:
 q=dict(value=value,unit='mm[Hg]',absent_reason='unknown' if value is None else None)
 add(name,public.Quantity,q,'SofaSource','Quantity')
for name,data in [('LIS原负值不被补零',dict(value='-1.25000000',unit='mg/dL',original_unit_hash=public.hash_content('mg/dL'),absent_reason=None,value_kind='numeric')),('LIS原定性不外发正文',dict(value=None,unit='mg/dL',original_unit_hash=public.hash_content('mg/dL'),absent_reason='unknown',value_kind='qualitative'))]:
 add(name,public.SofaLabQuantity,data,'SofaSource','SofaLabQuantity')
period=dict(patient_id=11,admission_id='11111111-1111-4111-8111-111111111111',period_start='2026-10-19T00:00:00.000000Z',period_end='2026-10-20T00:00:00.000000Z',as_of='2026-10-20T00:00:00.000000Z')
add('实际PeriodRequest',private.PeriodRequest,period)
for name,changes in [('患者ID不得bool',dict(patient_id=True)),('患者ID不得字符串',dict(patient_id='11')),('原请求禁止额外score',dict(score=0))]:add(name,private.PeriodRequest,{**period,**changes})
print(json.dumps(dict(cases=cases,period=period),ensure_ascii=False,separators=(',',':')))
`;
module.exports=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||"/home/xusheng/miniconda3/bin/python",["-c",script],{cwd:path.resolve(__dirname,"../../../fastapi_be"),encoding:"utf8",maxBuffer:1048576}));
