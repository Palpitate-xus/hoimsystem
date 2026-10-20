const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

// Import only model declarations. Disable dotenv, database initialization and
// socket connections before importing hospital modules; no service is started.
const script = String.raw`
import json, socket, sys, types
import dotenv
dotenv.load_dotenv=lambda *a,**kw:False
def blocked(*a,**kw):raise RuntimeError('Schema generation cannot open a socket')
socket.socket.connect=blocked
from sqlalchemy.orm import declarative_base
database=types.ModuleType('app.database');database.Base=declarative_base()
sys.modules['app.database']=database
sys.modules['app.ai.governance']=types.ModuleType('app.ai.governance')
from app.ai import bed_facts
models={name:getattr(bed_facts,name).model_json_schema() for name in ('SourceCreate','SourceReview','SourceRevoke','FrozenIdentity','ParentBinding')}
print(json.dumps(models,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const allowed = new Set(["$defs", "$ref", "additionalProperties", "anyOf", "const", "discriminator", "enum", "items", "maxItems", "minItems", "maxLength", "maximum", "minLength", "minimum", "oneOf", "pattern", "properties", "propertyNames", "required", "type"]);
const omitted = new Set(["title", "description", "default", "examples"]);
function compact(schema) {
  if (typeof schema === "boolean") return schema;
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) throw new Error("Expected an actual JSON schema object");
  const result = {};
  for (const [key, value] of Object.entries(schema)) {
    if (omitted.has(key)) continue;
    if (!allowed.has(key)) throw new Error(`Unsupported bed-source schema constraint: ${key}`);
    if (key === "$ref") { if (!/^#\/\$defs\/[A-Za-z][A-Za-z0-9_]*$/.test(value)) throw new Error("Only local named definitions are permitted"); result[key] = value; }
    else if (["$defs", "properties"].includes(key)) result[key] = Object.fromEntries(Object.entries(value).map(([name, definition]) => [name, compact(definition)]));
    else if (["items", "additionalProperties", "propertyNames"].includes(key)) result[key] = compact(value);
    else if (["anyOf", "oneOf"].includes(key)) result[key] = value.map(compact);
    else if (key === "discriminator") {
      if (Object.keys(value).sort().join(",") !== "mapping,propertyName" || typeof value.propertyName !== "string" || Object.values(value.mapping).some(ref => !/^#\/\$defs\/[A-Za-z][A-Za-z0-9_]*$/.test(ref))) throw new Error("Unsupported discriminator declaration");
      // oneOf already enforces the closed union; no independent constraint omitted.
    } else result[key] = value;
  }
  return result;
}
const root = path.resolve(__dirname, ".."), target = path.join(root, "src/api/bedSourceSchemas.json");
if (process.argv.slice(2).some(value => value !== "--check")) throw new Error("Only --check is supported");
const source = JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON || "/home/xusheng/miniconda3/bin/python", ["-c", script], { cwd: path.join(root, "../fastapi_be"), encoding: "utf8", maxBuffer: 1048576 }));
// Lossless static DAG storage shares identical JSON subtrees, while each model
// retains its original local $defs context. Same-name definitions with different
// constraints are never merged. No schema constraint or keyword is removed here.
const actual=Object.fromEntries(Object.entries(source).map(([name,schema])=>[name,compact(schema)]));
const nodes=[],seen=new Map();
function intern(value){
  const key=JSON.stringify(value);if(seen.has(key))return seen.get(key);
  const encode=item=>item!==null&&typeof item==="object"?[intern(item)]:item;
  const packed=Array.isArray(value)?value.map(encode):Object.fromEntries(Object.entries(value).map(([key,item])=>[key,encode(item)]));
  const index=nodes.length;nodes.push(packed);seen.set(key,index);return index;
}
const models=Object.fromEntries(Object.entries(actual).map(([name,schema])=>[name,intern(schema)]));
const restored=[];
for(const [index,node]of nodes.entries()){
  const decode=value=>{if(!Array.isArray(value))return value;if(value.length!==1||!Number.isSafeInteger(value[0])||value[0]<0||value[0]>=index)throw new Error("Invalid schema DAG reference");return restored[value[0]];};
  restored.push(Array.isArray(node)?node.map(decode):Object.fromEntries(Object.entries(node).map(([key,value])=>[key,decode(value)])));
}
const roundTrip=Object.fromEntries(Object.entries(models).map(([name,index])=>[name,restored[index]]));
if(JSON.stringify(roundTrip)!==JSON.stringify(actual))throw new Error("Packed schemas differ from the complete actual Pydantic constraints");
const output=JSON.stringify({models,nodes})+"\n";
if (process.argv.includes("--check")) {
  if (fs.readFileSync(target, "utf8") !== output) throw new Error("bed-source browser schemas differ from actual backend models; regenerate them");
  process.stdout.write(`Verified ${Object.keys(source).length} actual bed-source model schemas (${Buffer.byteLength(output)} bytes)\n`);
} else { fs.writeFileSync(target, output); process.stdout.write(`Generated ${Object.keys(source).length} actual bed-source model schemas (${Buffer.byteLength(output)} bytes)\n`); }
