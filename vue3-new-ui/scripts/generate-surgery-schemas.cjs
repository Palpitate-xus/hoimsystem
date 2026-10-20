const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

// Actual model declarations only. No dotenv, engine connection, server or model
// request is allowed while exporting static constraints and fixed core hashes.
const python = String.raw`
import builtins, io, json, os, socket, sys, types
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
def guard(factory):
 def call(file,*a,**kw):
  if not isinstance(file,int) and os.path.basename(os.fspath(file))=='.env':raise RuntimeError('No dotenv')
  return factory(file,*a,**kw)
 return call
builtins.open=guard(builtins.open);io.open=guard(io.open)
def blocked(*a,**kw):raise RuntimeError('No network for schema generation')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
from sqlalchemy.orm import declarative_base
database=types.ModuleType('app.database');database.Base=declarative_base();sys.modules['app.database']=database
governance=types.ModuleType('app.ai.governance');governance.provider_credential=blocked;governance.validate_endpoint=blocked;sys.modules['app.ai.governance']=governance
gateway=types.ModuleType('app.ai.gateway');gateway.AIExecutionError=RuntimeError;sys.modules['app.ai.gateway']=gateway
from app.ai import surgery_facts
from app.ai.surgery_probe import SurgeryCapabilities
from app.ai.surgery_collection import SafeResourceOriginalWrapper
from app.ai.surgery_contract import SurgeryRuntime, RECIPE, INPUT_POLICY, hash_content
from app.ai.surgery_config import runtime_descriptor
names=('SourceCreate','RegistryCreate','SourceReview','SourceRevoke','ProtectedCapsuleCreate','SourceWrapper','SourceParentBinding','RegistryParentBinding','SafeBusyCapsuleWrapper')
runtime=runtime_descriptor()
result={'source':{**{name:getattr(surgery_facts,name).model_json_schema() for name in names},'SafeResourceOriginalWrapper':SafeResourceOriginalWrapper.model_json_schema()},'provider':{'SurgeryCapabilities':SurgeryCapabilities.model_json_schema()},'fixed':{'recipe':RECIPE,'input_policy':INPUT_POLICY,'recipe_digest':hash_content(RECIPE),'input_policy_digest':hash_content(INPUT_POLICY),'core_sha256':runtime['core_sha256'],'runtime_fields':list(SurgeryRuntime.model_fields)}}
print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const allowed = new Set(['$defs','$ref','additionalProperties','anyOf','const','discriminator','enum','items','maxItems','minItems','maxProperties','minProperties','maxLength','maximum','minLength','minimum','oneOf','pattern','properties','propertyNames','required','type']);
function compact(schema) {
  if (typeof schema === 'boolean') return schema;
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) throw new Error('Invalid actual schema');
  const result = {};
  for (const [key,value] of Object.entries(schema)) {
    if (['title','description','default','examples'].includes(key)) continue;
    if (!allowed.has(key)) throw new Error(`Unsupported surgery schema constraint: ${key}`);
    if (key === '$ref') { if (!/^#\/\$defs\/[A-Za-z][A-Za-z0-9_]*$/.test(value)) throw new Error('Only local named references'); result[key]=value; }
    else if (['$defs','properties'].includes(key)) result[key]=Object.fromEntries(Object.entries(value).map(([name,entry])=>[name,compact(entry)]));
    else if (['items','additionalProperties','propertyNames'].includes(key)) result[key]=compact(value);
    else if (['anyOf','oneOf'].includes(key)) result[key]=value.map(compact);
    else if (key === 'discriminator') {
      if (Object.keys(value).sort().join(',') !== 'mapping,propertyName' || typeof value.propertyName !== 'string' || !value.mapping || typeof value.mapping !== 'object') throw new Error('Unsupported discriminator');
      for(const branch of Object.values(value.mapping)) {
        if(typeof branch==='string') { if(!/^#\/\$defs\/[A-Za-z][A-Za-z0-9_]*$/.test(branch))throw new Error('Unsupported discriminator reference'); }
        else { if(!branch||!Array.isArray(branch.oneOf))throw new Error('Unsupported nested discriminator');compact(branch); }
      }
      // Complete oneOf branches still enforce this closed tagged union.
    } else result[key]=value;
  }
  return result;
}
function pack(source) {
  const actual=Object.fromEntries(Object.entries(source).map(([name,schema])=>[name,compact(schema)])),nodes=[],seen=new Map();
  function intern(value) {
    const key=JSON.stringify(value);if(seen.has(key))return seen.get(key);
    const encode=item=>item!==null&&typeof item==='object'?[intern(item)]:item;
    const node=Array.isArray(value)?value.map(encode):Object.fromEntries(Object.entries(value).map(([key,item])=>[key,encode(item)]));
    const index=nodes.length;nodes.push(node);seen.set(key,index);return index;
  }
  const models=Object.fromEntries(Object.entries(actual).map(([name,schema])=>[name,intern(schema)])),restored=[];
  for (const [index,node] of nodes.entries()) {
    const decode=value=>{if(!Array.isArray(value))return value;if(value.length!==1||!Number.isSafeInteger(value[0])||value[0]<0||value[0]>=index)throw new Error('Invalid backward reference');return restored[value[0]];};
    restored.push(Array.isArray(node)?node.map(decode):Object.fromEntries(Object.entries(node).map(([key,value])=>[key,decode(value)])));
  }
  if(JSON.stringify(Object.fromEntries(Object.entries(models).map(([name,index])=>[name,restored[index]])))!==JSON.stringify(actual))throw new Error('Actual complete constraints changed during DAG storage');
  return {models,nodes};
}
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(value=>value!=='--check'))throw new Error('Only --check is supported');
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',python],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const [name,value] of [['surgerySourceSchemas.json',pack(data.source)],['surgeryProviderSchemas.json',pack(data.provider)],['surgeryFixedPolicy.json',data.fixed]]) {
  const target=path.join(root,'src/api/ai',name),text=JSON.stringify(value)+'\n';
  if(check) { if(fs.readFileSync(target,'utf8')!==text)throw new Error(`${name} differs from actual backend declarations`); }
  else { fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,text); }
  process.stdout.write(`${check?'Verified':'Generated'} ${name}: ${Buffer.byteLength(text)} bytes\n`);
}
