const {execFileSync}=require('node:child_process'),path=require('node:path');
let cached;
// Pure typed core engineering cases. These are not private series, hospital
// data or database fixtures. No dotenv/database/network initialization is used.
function bedNativeCases(){if(cached)return cached;const script=String.raw`
import json,socket
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
def blocked(*a,**kw):raise RuntimeError('Native fixture export cannot open a socket')
socket.socket.connect=blocked
from datetime import datetime,timedelta
from app.ai.bed_contract import BedSource,hash_content
from app.ai.bed_model import compute_bed
from tests.test_ai_bed_model import make_source,runtime,clone_capacity
cases={}
def add(name,value):
 source=BedSource.model_validate(value)
 analysis=compute_bed(source,7,'a'*64,runtime())
 cases[name]={'source':source.model_dump(mode='json'),'analysis':analysis.model_dump(mode='json')}
spring=make_source(start='2025-11-17',timezone='America/New_York',values=[12]*112)
spring['capacity_intervals'][-2]['operational_total_beds']['value']=2147483647
add('spring_23h_big_integral',spring)
add('fall_25h',make_source(timezone='America/New_York'))
zero=make_source(values=[0]*112)
for item in zero['capacity_intervals']:item['operational_total_beds']['value']=0
add('zero_denominators',zero)
unknown=make_source();unknown['census_observations'][-1]['occupied_beds']={'value':None,'absent_reason':'not_recorded'}
unknown['flow_observations'][0]['discharge_events']={'value':None,'absent_reason':'unknown'}
unknown['capacity_intervals'][-1]['end_at']=(datetime.fromisoformat(unknown['days'][-1]['day_end_at'].replace('Z','+00:00'))+timedelta(days=1)).isoformat(timespec='microseconds').replace('+00:00','Z')
add('unknown_axes_halfopen_end',unknown)
print(json.dumps(cases,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;cached=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',script],{cwd:path.resolve(__dirname,'../../../fastapi_be'),encoding:'utf8',maxBuffer:64*1024*1024}));return cached;}
module.exports={bedNativeCases};
