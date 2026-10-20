const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const sources=Object.fromEntries(['map','respiratory_support','arterial_pair','vasoactive','infection_episode'].map(kind=>[kind,JSON.parse(fs.readFileSync(path.join(__dirname,'support-synthetic',kind+'.json'),'utf8'))]));
// The actual backend projection is the fixture oracle. Import guards disable
// dotenv and socket connections; this runs no server, DB, or model service.
const script=String.raw`
import json, socket, sys
import dotenv
dotenv.load_dotenv=lambda *args,**kwargs:False
def blocked(*args,**kwargs):raise RuntimeError('Fixture cannot open network sockets')
socket.socket.connect=blocked
from app.ai.support_context import public_source, MISSING_DATA, SOURCE_SCOPE
from app.inpatient_laboratory import hash_content
sources=json.load(sys.stdin)
result={}
for kind,original in sources.items():
 original.pop('can_record',None);original.pop('can_revoke',None)
 public=public_source(original)
 result[kind]={'scope':SOURCE_SCOPE,'missing_data':list(MISSING_DATA),'selected_sources':{'support_source_id':original['support_source_id'],'support_source_kind':kind},'support_source':public,'support_source_provenance':original,'support_public_hash':hash_content(public)}
print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
`;
const packets=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',script],{cwd:path.resolve(__dirname,'../../../fastapi_be'),input:JSON.stringify(sources),encoding:'utf8',maxBuffer:1048576}));
module.exports={packets};
