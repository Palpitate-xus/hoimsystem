/* Complete trusted public vector data; strict DOM nodes, never executable markup. */
const {schemaDataHash}=require('../api/schemaDataHash.cjs');
const NS='http://www.w3.org/2000/svg',ID='hoim-element-plus-icon-sprite';
let registered;
function registerStaticIconSprite(value,sha256,count){
 if(!value||Array.isArray(value)||Object.keys(value).join(',')!=='svg'||typeof value.svg!=='string'||!/^[a-f0-9]{64}$/.test(sha256)||count!==293)throw Error('Invalid complete icon vector binding');
 const bytes=new TextEncoder().encode(value.svg);
 if(bytes.length>262144||schemaDataHash(bytes)!==sha256)throw Error('Original icon vector SHA differs');
 const previous=document.querySelectorAll('#'+ID);
 if(registered){if(registered!==sha256||previous.length!==1||previous[0].getAttribute('data-sha256')!==sha256)throw Error('Ambiguous registered icon vector');return '';}
 if(previous.length||!document.body)throw Error('Missing body or existing unverified icon vector');
 const parsed=new DOMParser().parseFromString(value.svg,'image/svg+xml');
 if(parsed.querySelector('parsererror'))throw Error('Malformed original icon vector');
 const root=parsed.documentElement;
 if(root.namespaceURI!==NS||root.localName!=='svg')throw Error('Invalid original icon vector root');
 const symbols=new Set();
 for(const node of [root,...root.querySelectorAll('*')]){
  if(node.namespaceURI!==NS||!['svg','symbol','path'].includes(node.localName))throw Error('Unexpected icon vector node');
  for(const attribute of node.attributes){
   if(!['xmlns','d','fill','id','viewBox','xml:space'].includes(attribute.name))throw Error('Unexpected icon vector attribute');
   if(attribute.name==='fill'&&!/^(?:currentColor|none)$/.test(attribute.value))throw Error('Unexpected icon fill');
  }
  if(node.localName==='symbol'){
   const id=node.getAttribute('id');
   if(!/^icon-[A-Za-z][A-Za-z0-9]*$/.test(id)||symbols.has(id)||document.getElementById(id))throw Error('Ambiguous original icon identity');
   symbols.add(id);
  }else if(node.hasAttribute('id'))throw Error('Unexpected icon identity');
 }
 if(symbols.size!==count)throw Error('Incomplete original icon set');
 const actual=document.importNode(root,true);
 actual.id=ID;actual.setAttribute('data-sha256',sha256);actual.setAttribute('aria-hidden','true');actual.setAttribute('focusable','false');
 actual.style.cssText='position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';
 document.body.prepend(actual);registered=sha256;return '';
}
module.exports={registerStaticIconSprite};
