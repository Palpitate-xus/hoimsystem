const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'e2e/fixtures/supply-native'),target=path.join(folder,'capabilities.json');
const code=String.raw`import json,sys
from app.ai.supply_config import runtime_descriptor
assert not any(n in sys.modules for n in ['app.config','app.database','app.models'])
print(json.dumps(runtime_descriptor(),ensure_ascii=False,sort_keys=True,separators=(',',':')))`;
const text=execFileSync('/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8'});
if(process.argv.includes('--check')){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Supply fixture differs from actual runtime_descriptor');}else fs.writeFileSync(target,text);
process.stdout.write('Actual native metadata '+Buffer.byteLength(text)+' bytes\n');

// The following fixtures are synthetic typed public sources passed to the real
// frozen native calculator. They make no ORM/current-authorization/worker claim.
const native=String.raw`import json,sys,hashlib
from pathlib import Path
from fractions import Fraction
from app.ai.supply_contract import SupplySource,canonical_json,rational
from app.ai.supply_config import runtime_descriptor,runtime_from_descriptor,implementation_hashes
from app.ai.supply_model import compute_supply,generation_result_for_analysis
from tests.test_ai_supply_contract import make_source
assert not any(n in sys.modules for n in ['app.config','app.database','app.models'])
runtime=runtime_from_descriptor(runtime_descriptor())
cases={}
def emit(name,source,horizon):
    source=SupplySource.model_validate(source).model_dump(mode='json')
    analysis=compute_supply(source,horizon,'a'*64,runtime)
    cases[name]={'scope':'synthetic public Source and actual compute_supply; not ORM, worker or HTTP','horizon_days':horizon,'source':source,'analysis':analysis.model_dump(mode='json'),'result':generation_result_for_analysis(analysis)}
emit('complete-h14',make_source(),14)
emit('zero-h7',make_source(values=['0.000000']*112),7)
v=['0']*112
v[0],v[95]='4','8'
emit('partial-h7',make_source(values=v),7)
s=make_source()
s['observations'][0]['quantity']={'value':None,'absent_reason':'not_recorded'}
emit('unknown-h7',s,7)
s=make_source()
s['observations'][-3]['unit_token']='e'*64
s['observations'][-3]['quantity']['value']='999999999999999999.123456'
emit('unit-mismatch-h7',s,7)
s=make_source(values=['0','4','0','0','8']+['0']*107)
s['parameters']={'alpha_size':rational(Fraction(1)),'alpha_interval':rational(Fraction(1,1000)),'beta_occurrence':rational(Fraction(1))}
emit('split-parameters-h7',s,7)
print(canonical_json({'cases':cases,'core_sha256':implementation_hashes(),'scope':'actual native pure calculation fixtures; no patient data, database, network, HTTP or authorization claim'}))`;
const raw=execFileSync('/home/xusheng/miniconda3/bin/python',['-c',native],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:32*1024*1024}),value=JSON.parse(raw),crypto=require('node:crypto'),files={};
for(const [name,data]of Object.entries(value.cases)){const output=JSON.stringify(data)+'\n',filename=name+'.json';files[filename]={bytes:Buffer.byteLength(output),sha256:crypto.createHash('sha256').update(output).digest('hex')};const file=path.join(folder,filename);if(process.argv.includes('--check')){if(fs.readFileSync(file,'utf8')!==output)throw new Error('Native calculation fixture differs: '+name);}else fs.writeFileSync(file,output);}
const manifest=JSON.stringify({scope:value.scope,core_sha256:value.core_sha256,files},null,2)+'\n',manifestPath=path.join(folder,'native-manifest.json');if(process.argv.includes('--check')){if(fs.readFileSync(manifestPath,'utf8')!==manifest)throw new Error('Native calculation manifest differs');}else fs.writeFileSync(manifestPath,manifest);
process.stdout.write('Six actual native pure-calculation fixtures '+Object.values(files).reduce((n,v)=>n+v.bytes,0)+' bytes\n');
