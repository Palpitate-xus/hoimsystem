// Parse retained original bytes without JSON.parse's duplicate-key overwrite.
// Hash callers retain the raw string; floats are never reconstructed from JS.
const encoder=new TextEncoder(),forbidden=new Set(['__proto__','prototype','constructor']);
const scalar=text=>typeof text==='string'&&!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(text);
export function scalarJsonValue(value,depth=0){
 if(depth>64)return false;
 if(typeof value==='string')return scalar(value);
 if(typeof value==='number')return Number.isFinite(value)&&(!Number.isInteger(value)||Number.isSafeInteger(value));
 if(value===null||typeof value==='boolean')return true;
 if(Array.isArray(value))return value.every(item=>scalarJsonValue(item,depth+1));
 return value!==null&&typeof value==='object'&&[null,Object.prototype].includes(Object.getPrototypeOf(value))&&Object.entries(value).every(([key,item])=>scalar(key)&&!forbidden.has(key)&&scalarJsonValue(item,depth+1));
}
export function parseOriginalJson(raw,maxBytes=65535){
 if(!scalar(raw)||!raw.length||encoder.encode(raw).length>maxBytes)throw new Error('Original JSON text exceeds its exact UTF8 budget');
 let index=0;
 const fail=()=>{throw new Error('Original JSON has duplicate keys, invalid scalars or invalid syntax');};
 const space=()=>{while(/[\x20\t\r\n]/.test(raw[index]||'\0'))index++;};
 const string=()=>{const start=index;if(raw[index++]!=='"')return fail();while(index<raw.length){const char=raw[index++];if(char==='"'){const value=JSON.parse(raw.slice(start,index));if(!scalar(value))return fail();return value;}if(char==='\\'){if(index>=raw.length)return fail();index++;}}return fail();};
 function value(depth){
  if(depth>64)return fail();space();const char=raw[index];
  if(char==='"')return string();
  if(char==='{'){
   index++;space();const result=Object.create(null),seen=new Set();if(raw[index]==='}'){index++;return result;}
   while(index<raw.length){space();if(raw[index]!=='"')return fail();const key=string();if(seen.has(key)||forbidden.has(key))return fail();seen.add(key);space();if(raw[index++]!==':')return fail();result[key]=value(depth+1);space();const next=raw[index++];if(next==='}')return result;if(next!==',')return fail();}return fail();
  }
  if(char==='['){index++;space();const result=[];if(raw[index]===']'){index++;return result;}while(index<raw.length){result.push(value(depth+1));space();const next=raw[index++];if(next===']')return result;if(next!==',')return fail();}return fail();}
  for(const [token,item]of [['true',true],['false',false],['null',null]])if(raw.startsWith(token,index)){index+=token.length;return item;}
  const match=/-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;match.lastIndex=index;const found=match.exec(raw);if(!found)return fail();index=match.lastIndex;const result=Number(found[0]);if(!Number.isFinite(result)||Number.isInteger(result)&&!Number.isSafeInteger(result))return fail();return result;
 }
 const result=value(0);space();if(index!==raw.length||!scalarJsonValue(result))return fail();return result;
}
