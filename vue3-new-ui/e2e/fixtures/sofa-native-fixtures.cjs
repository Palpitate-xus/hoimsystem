const fs=require("node:fs"),path=require("node:path"),{execFileSync}=require("node:child_process");
const names=["daily-active","seven-daily","change-unknown","change-conditional_zero","change-observed"],originals=Object.fromEntries(names.map(name=>[name,JSON.parse(fs.readFileSync(path.join(__dirname,"sofa-synthetic",name+".json"),"utf8"))]));
// Real immutable ORM projections are sent to the actual pure specialist. The
// additional view-only examples reuse the specialist's own native test fixtures;
// they establish rendering behavior, not a clinical admission or authorization.
const script=String.raw`
import json,socket,sys
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
def blocked(*a,**kw):raise RuntimeError('Native fixtures cannot open network sockets')
socket.socket.connect=blocked
from app.ai.sofa_config import runtime_descriptor,runtime_from_descriptor
from app.ai.sofa_contract import SofaSource,SofaAnalysis,SofaChangeSource,SofaChangeAnalysis,hash_content
from app.ai.sofa_model import compute_sofa,compute_change
from tests.test_ai_sofa_model import complete_source,lab,map_point,respiratory
runtime=runtime_from_descriptor(runtime_descriptor());instructions=hash_content('Explicit synthetic UI prompt provenance; no provider call')
rows=json.load(sys.stdin);result={}
for name,row in rows.items():
 source=row['specialist_source'];change=source['schema_version']=='sofa1_change_source_v1'
 typed=(SofaChangeSource if change else SofaSource).model_validate(source)
 analysis=(compute_change if change else compute_sofa)(typed,instructions,runtime)
 analysis=(SofaChangeAnalysis if change else SofaAnalysis).model_validate(analysis.model_dump())
 result[name]=dict(source=typed.model_dump(),analysis=analysis.model_dump(),scope=row)
examples={'complete_zero':complete_source()}
ceiling=complete_source();ceiling['lab_observations']=[lab('platelet_count','150','10^9/L'),lab('total_bilirubin','1','mg/dL'),lab('creatinine','5','mg/dL')];ceiling['urine_intervals']=[];examples['numeric_exact_protocol_partial']=ceiling
partial=complete_source();partial['respiratory_observations']=[respiratory('99','100',qualifying='unknown')];examples['subtotal_below_lower_bound']=partial
ties=complete_source();ties['map_observations']=[map_point('60','map-tie-a'),map_point('60','map-tie-b')];examples['all_tied_witnesses']=ties
for name,source in examples.items():
 typed=SofaSource.model_validate(source);analysis=SofaAnalysis.model_validate(compute_sofa(typed,instructions,runtime).model_dump());result[name]=dict(source=typed.model_dump(),analysis=analysis.model_dump())
print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
`;
module.exports=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||"/home/xusheng/miniconda3/bin/python",["-c",script],{cwd:path.resolve(__dirname,"../../../fastapi_be"),input:JSON.stringify(originals),encoding:"utf8",maxBuffer:8388608}));
