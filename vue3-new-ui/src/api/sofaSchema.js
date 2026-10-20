import registry from "./sofaSchemas.json";

const own = (value, key) => Object.hasOwn(value, key);
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const forbidden = key => ["__proto__", "prototype", "constructor"].includes(key);
const allowed = new Set(["$defs", "$ref", "additionalProperties", "anyOf", "const", "enum", "exclusiveMinimum", "exclusiveMaximum", "items", "maxItems", "minItems", "maxProperties", "minProperties", "maxLength", "maximum", "minLength", "minimum", "oneOf", "pattern", "properties", "propertyNames", "required", "type"]);

// Expand generated lossless JSON nodes once. References can only point backward,
// so malformed/cyclic registries fail before any clinical input is accepted.
function unpackRegistry(value){
  if(!object(value)||Object.keys(value).sort().join(",")!=="models,nodes"||!object(value.models)||!Array.isArray(value.nodes))throw new Error("Invalid SOFA schema registry");
  const nodes=[];
  for(const [index,node]of value.nodes.entries()){
    if(!object(node)&&!Array.isArray(node))throw new Error("Invalid SOFA schema node");
    const decode=item=>{if(Array.isArray(item)){if(item.length!==1||!Number.isSafeInteger(item[0])||item[0]<0||item[0]>=index)throw new Error("Invalid SOFA schema reference");return nodes[item[0]];}if(item!==null&&typeof item==="object")throw new Error("Unpacked SOFA schema object");return item;};
    nodes.push(Array.isArray(node)?node.map(decode):Object.fromEntries(Object.entries(node).map(([key,item])=>{if(forbidden(key))throw new Error("Forbidden SOFA schema key");return[key,decode(item)];})));
  }
  return Object.fromEntries(Object.entries(value.models).map(([name,index])=>{if(forbidden(name)||!Number.isSafeInteger(index)||index<0||index>=nodes.length||!object(nodes[index]))throw new Error("Invalid SOFA schema model");return[name,JSON.parse(JSON.stringify(nodes[index]))];}));
}
const schemas=unpackRegistry(registry);

// A closed subset of the schemas generated from actual Pydantic models. Every
// unsupported constraint rejects; schema/model validators remain distinct.
function matches(schema, value, root, depth) {
  if (depth > 80 || schema === false) return false;
  if (schema === true) return true;
  if (!object(schema) || Object.keys(schema).some(key => !allowed.has(key))) return false;
  if (["exclusiveMinimum", "exclusiveMaximum"].some(key => own(schema,key) && (typeof schema[key] !== "number" || !Number.isFinite(schema[key]) || Number.isInteger(schema[key]) && !Number.isSafeInteger(schema[key])))) return false;
  if (schema.$ref) {
    const match = /^#\/\$defs\/([A-Za-z][A-Za-z0-9_]*)$/.exec(schema.$ref);
    if (!match || forbidden(match[1]) || !object(root.$defs) || !own(root.$defs, match[1]) || !matches(root.$defs[match[1]], value, root, depth + 1)) return false;
  }
  if (schema.anyOf && !schema.anyOf.some(branch => matches(branch, value, root, depth + 1))) return false;
  if (schema.oneOf && schema.oneOf.filter(branch => matches(branch, value, root, depth + 1)).length !== 1) return false;
  if (own(schema, "const") && value !== schema.const || schema.enum && !schema.enum.includes(value)) return false;
  if (schema.type === "null" && value !== null || schema.type === "string" && typeof value !== "string" || schema.type === "integer" && !Number.isSafeInteger(value) || schema.type === "number" && (typeof value !== "number" || !Number.isFinite(value)) || schema.type === "boolean" && typeof value !== "boolean" || schema.type === "object" && !object(value) || schema.type === "array" && !Array.isArray(value)) return false;
  if (schema.type && !["null", "string", "integer", "number", "boolean", "object", "array"].includes(schema.type)) return false;
  if (typeof value === "string") {
    const length = Array.from(value).length;
    if (schema.minLength !== undefined && length < schema.minLength || schema.maxLength !== undefined && length > schema.maxLength || schema.pattern && !new RegExp(schema.pattern, "u").test(value)) return false;
  }
  if (typeof value === "number" && (schema.minimum !== undefined && value < schema.minimum || schema.maximum !== undefined && value > schema.maximum || schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum || schema.exclusiveMaximum !== undefined && value >= schema.exclusiveMaximum)) return false;
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems || schema.maxItems !== undefined && value.length > schema.maxItems || schema.items && value.some(item => !matches(schema.items, item, root, depth + 1))) return false;
  }
  if (object(value)) {
    if (schema.minProperties !== undefined && Object.keys(value).length < schema.minProperties || schema.maxProperties !== undefined && Object.keys(value).length > schema.maxProperties) return false;
    if (Object.keys(value).some(forbidden) || schema.required?.some(key => !own(value, key))) return false;
    for (const [key, item] of Object.entries(value)) {
      if (schema.propertyNames && !matches(schema.propertyNames, key, root, depth + 1)) return false;
      if (schema.properties && own(schema.properties, key)) { if (!matches(schema.properties[key], item, root, depth + 1)) return false; }
      else if (schema.additionalProperties === false || object(schema.additionalProperties) && !matches(schema.additionalProperties, item, root, depth + 1)) return false;
    }
  }
  return true;
}

export function sofaSchemaMatches(name, value, definition = null) {
  try { const schema = sofaSchemaDefinition(name, definition); return !!schema && matches(schema, value, schemas[name], 0); } catch { return false; }
}

export function sofaSchemaDefinition(name, definition) {
  if (typeof name !== "string" || forbidden(name) || !own(schemas, name)) return null;
  const root = schemas[name];
  return root && (definition ? own(root.$defs || {}, definition) && !forbidden(definition) ? root.$defs[definition] : null : root);
}

export {unpackRegistry as decodeGeneratedSchemas};
export function generatedSchemaMatches(models,name,value,definition=null){try{if(typeof name!=="string"||forbidden(name)||!own(models,name))return false;const root=models[name],schema=definition?own(root.$defs||{},definition)&&!forbidden(definition)?root.$defs[definition]:null:root;return !!schema&&matches(schema,value,root,0);}catch{return false;}}
