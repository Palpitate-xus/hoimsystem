const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'e2e/fixtures/inventory-native'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from app.ai.inventory_contract import InventorySource,canonical_json
from app.ai.inventory_model import compute_inventory,generation_result_for_analysis,implementation_hashes
from app.ai.inventory_config import runtime_descriptor,runtime_from_descriptor
from tests.test_ai_inventory_contract import make_source,amount,candidate,receipt,refresh,lot,constraint
from tests.test_ai_inventory_model import opening
assert not any(n in sys.modules for n in ['app.config','app.database','app.models','sqlalchemy'])
runtime=runtime_from_descriptor(runtime_descriptor());cases={}
def emit(name,source):
 source=InventorySource.model_validate(source).model_dump()
 analysis=compute_inventory(source,'a'*64,runtime)
 cases[name]={'scope':'synthetic public Source and actual compute_inventory; not ORM, worker, HTTP or current authorization','source':source,'analysis':analysis.model_dump(),'result':generation_result_for_analysis(analysis)}
emit('complete',make_source())
s=make_source();s['candidates']=[candidate('no-purchase',[])];refresh(s)
for day in s['scenario']['days']:day['required_quantity']=amount('0.000000')
s['scenario']['budget']=constraint('0',True);emit('zero',s)
s=make_source();opening(s,[lot('frozen','3','2','2026-10-21')]);s['candidates'][0]['orders'][0]['lines']=[receipt(quantity='2',arrival='2026-10-21',expiry='2026-10-20',price='3')];emit('expiry-frozen',s)
s=make_source();s['observation']['method']='legacy_current_capture';s['observation']['observed_at']=None;emit('legacy-capture',s)
s=make_source();s['observation']['legacy_snapshot']['catalog_quantity']=amount('-2');emit('negative-legacy',s)
s=make_source();s['candidates'].append(candidate('unknown',[receipt('unknown',price=None)]));refresh(s);emit('unknown-plan',s)
s=make_source();s['candidates'].append(candidate('tie',[receipt('tie')]));refresh(s);emit('all-ties',s)
s=make_source(days=31);s['observation']['lots'][0]['quantity']['value']='999999999999999999.123456';s['observation']['declared_total_quantity']=s['observation']['lots'][0]['quantity'].copy();s['observation']['legacy_snapshot']['catalog_quantity']=s['observation']['declared_total_quantity'].copy();s['observation']['legacy_snapshot']['batch_quantity_sum']=s['observation']['declared_total_quantity'].copy();emit('max-precision-31days',s)
s=make_source();s['candidates'][0]['plan_fixed_fee']=amount('1.125',True);s['candidates'][0]['orders'][0]['order_fixed_fee']=amount('2.5',True);s['scenario']['budget']=constraint('6',True);s['scenario']['days'][0]['minimum_end_usable']=constraint('4');s['scenario']['days'][1]['maximum_end_total']=constraint('2');emit('fees-budget-constraints',s)
s=make_source();s['scenario']['days'][1]['maximum_end_total']=constraint(mode='unknown');emit('unknown-constraint',s)
s=make_source();opening(s,[lot('none','2','0',None),lot('a','2','0','2026-10-25'),lot('b','2','0','2026-10-25')]);s['candidates']=[candidate('no-purchase',[])];refresh(s);emit('fefo-lot-tie',s)
s=make_source();s['candidates'][0]['completeness']='incomplete';emit('incomplete-plan',s)
s=make_source();s['candidates'][0]['orders'][0]['lines'][0]['unit_price']['unit_token']='f'*64;emit('cost-unit-mismatch',s)
s=make_source();s['observation']['lots'][0]['quantity']['unit_token']='f'*64;emit('stock-unit-mismatch',s)
print(canonical_json({'cases':cases,'capabilities':runtime_descriptor(),'core_sha256':implementation_hashes(),'scope':'actual independent native calculation only, synthetic no hospital data'}))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:16777216}));
const files={};
for(const[name,value]of Object.entries({...data.cases,capabilities:data.capabilities})){
 const file=name+'.json',text=JSON.stringify(value)+'\n',p=path.join(folder,file);files[file]={bytes:Buffer.byteLength(text),sha256:crypto.createHash('sha256').update(text).digest('hex')};
 if(check){if(fs.readFileSync(p,'utf8')!==text)throw new Error('Actual native fixture differs: '+name);}else fs.writeFileSync(p,text);
}
const p=path.join(folder,'manifest.json'),text=JSON.stringify({scope:data.scope,core_sha256:data.core_sha256,files},null,2)+'\n';
if(check){if(fs.readFileSync(p,'utf8')!==text)throw new Error('Actual fixture manifest differs');}else fs.writeFileSync(p,text);
process.stdout.write(`Actual native fixtures: ${Object.keys(data.cases).length} computations, ${Object.values(files).reduce((n,v)=>n+v.bytes,0)} bytes\n`);
