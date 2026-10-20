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
from app.ai import sofa_contract, sofa_sources
models={}
for module,names in ((sofa_contract,('SofaSource','SofaAnalysis','SofaChangeSource','SofaChangeAnalysis')),(sofa_sources,('PeriodRequest','AssessmentCreate','AssessmentRevoke'))):
 for name in names:
  model=getattr(module,name,None)
  if model is not None:models[name]=model.model_json_schema()
from importlib.util import find_spec
if find_spec('app.ai.sofa_change_sources') is not None:
 from app.ai import sofa_change_sources
 for name in ('ChangeCandidatesRequest','ChangeCreate','ChangeRevoke'):
  model=getattr(sofa_change_sources,name,None)
  if model is not None:models[name]=model.model_json_schema()
print(json.dumps(models,ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const allowed = new Set(["$defs", "$ref", "additionalProperties", "anyOf", "const", "discriminator", "enum", "items", "maxItems", "maxLength", "maximum", "minLength", "minimum", "oneOf", "pattern", "properties", "propertyNames", "required", "type"]);
const omitted = new Set(["title", "description", "default", "examples"]);
function compact(schema) {
  if (typeof schema === "boolean") return schema;
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) throw new Error("Expected an actual JSON schema object");
  const result = {};
  for (const [key, value] of Object.entries(schema)) {
    if (omitted.has(key)) continue;
    if (!allowed.has(key)) throw new Error(`Unsupported SOFA schema constraint: ${key}`);
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
const root = path.resolve(__dirname, ".."), target = path.join(root, "src/api/sofaSchemas.json");
if (process.argv.slice(2).some(value => value !== "--check")) throw new Error("Only --check is supported");
const source = JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON || "/home/xusheng/miniconda3/bin/python", ["-c", script], { cwd: path.join(root, "../fastapi_be"), encoding: "utf8", maxBuffer: 1048576 }));
const output = JSON.stringify(Object.fromEntries(Object.entries(source).map(([name, schema]) => [name, compact(schema)]))) + "\n";
if (process.argv.includes("--check")) {
  if (fs.readFileSync(target, "utf8") !== output) throw new Error("SOFA browser schemas differ from actual backend models; regenerate them");
  process.stdout.write(`Verified ${Object.keys(source).length} actual SOFA model schemas (${Buffer.byteLength(output)} bytes)\n`);
} else { fs.writeFileSync(target, output); process.stdout.write(`Generated ${Object.keys(source).length} actual SOFA model schemas (${Buffer.byteLength(output)} bytes)\n`); }
