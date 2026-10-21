const allowed = new Set(['$defs','$ref','additionalProperties','anyOf','const','discriminator','enum','exclusiveMinimum','exclusiveMaximum','items','maxItems','minItems','maxProperties','minProperties','maxLength','maximum','minLength','minimum','oneOf','pattern','properties','propertyNames','required','type']);
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

module.exports={compact,pack};
