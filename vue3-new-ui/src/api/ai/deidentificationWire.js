import{deidentificationUtf8 as utf8,keys,same}from'./deidentificationCore';
// Retain the original number lexemes and subtree bytes. A Python FLOAT-bearing
// artifact is checked from this original HTTP substring, never JSON.stringify.
export function parseDeidentificationJson(text,{maxBytes=8388608,rawPaths=[]}={}){
 if(typeof text!=='string'||utf8(text).length>maxBytes)throw new Error('完整75 JSON超过字节预算');let at=0,nodes=0;const raw={},wanted=new Set(rawPaths.map(p=>JSON.stringify(p)));
 const ws=()=>{while(at<text.length&&/[\x20\x09\x0a\x0d]/u.test(text[at]))at++;};
 function string(){const start=at++;while(at<text.length){const ch=text[at++];if(ch==='"'){const v=JSON.parse(text.slice(start,at));utf8(v);return v;}if(ch==='\\')at++;}throw new Error('原JSON文字未闭合');}
 const number=/-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
 function read(depth,path){if(++nodes>1000000||depth>80)throw new Error('原JSON结构超限');ws();const start=at,ch=text[at];let value;
  if(ch==='"')value=string();
  else if(ch==='{'||ch==='['){const array=ch==='[',out=array?[]:Object.create(null),seen=new Set();at++;ws();if(text[at]===(array?']':'}'))at++;else while(at<text.length){let key=array?out.length:null;if(!array){if(text[at]!=='"')throw new Error('JSON键须文字');key=string();if(seen.has(key)||['__proto__','prototype','constructor'].includes(key))throw new Error('重复或原型JSON键');seen.add(key);ws();if(text[at++]!==':')throw new Error('JSON缺冒号');}const item=read(depth+1,[...path,key]);if(array)out.push(item);else out[key]=item;ws();if(text[at]===(array?']':'}')){at++;break;}if(text[at++]!==',')throw new Error('JSON缺分隔');ws();}if(text[at-1]!== (array?']':'}'))throw new Error('原JSON对象未闭合');value=out;}
  else{let literal=false;for(const[word,v]of [['true',true],['false',false],['null',null]])if(text.startsWith(word,at)){at+=word.length;value=v;literal=true;break;}if(!literal){number.lastIndex=at;const match=number.exec(text);if(!match)throw new Error('JSON原值无效');at=number.lastIndex;value=Number(match[0]);if(!Number.isFinite(value)||Number.isInteger(value)&&!Number.isSafeInteger(value))throw new Error('JSON数值超出精确范围');}}
  if(wanted.has(JSON.stringify(path)))raw[JSON.stringify(path)]=text.slice(start,at);return value;
 }
 const value=read(0,[]);ws();if(at!==text.length)throw new Error('JSON尾随内容');return{value,raw};
}
export function decodeDeidentificationWire(raw){const bytesValue=raw instanceof ArrayBuffer?new Uint8Array(raw):raw;if(!(bytesValue instanceof Uint8Array)||bytesValue.length>8388608)throw new Error('完整75回执须不超过8MiB');const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytesValue),parsed=parseDeidentificationJson(text).value;if(!keys(parsed,['code','msg','data'])||parsed.code!==200||parsed.msg!=='success')throw new Error('75回执不是成功闭集');return{data:parsed.data,raw_http_body:text};}
export function deidentificationWireValue(value){if(!keys(value,['data','raw_http_body'])||typeof value.raw_http_body!=='string')throw new Error('须保留原HTTP字节');const parsed=parseDeidentificationJson(value.raw_http_body,{rawPaths:[['data','source_artifact']]}),p=parsed.value;if(!keys(p,['code','msg','data'])||p.code!==200||p.msg!=='success'||!same(p.data,value.data))throw new Error('75回执类型不符');return{data:p.data,sourceRaw:parsed.raw[JSON.stringify(['data','source_artifact'])]??null};}
