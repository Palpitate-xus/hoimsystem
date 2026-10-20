const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),target=path.join(root,'e2e/fixtures/supply-native/capabilities.json');
const code=String.raw`import json,sys
from app.ai.supply_config import runtime_descriptor
assert not any(n in sys.modules for n in ['app.config','app.database','app.models'])
print(json.dumps(runtime_descriptor(),ensure_ascii=False,sort_keys=True,separators=(',',':')))`;
const text=execFileSync('/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8'});
if(process.argv.includes('--check')){if(fs.readFileSync(target,'utf8')!==text)throw new Error('Supply fixture differs from actual runtime_descriptor');}else fs.writeFileSync(target,text);
process.stdout.write('Actual native metadata '+Buffer.byteLength(text)+' bytes\n');
