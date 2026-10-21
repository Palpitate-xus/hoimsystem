/* Store unchanged public UI strings as inert build data, after Babel compilation. */
const path = require('node:path');
const babel = require('@babel/core');
const {encodeStaticJson, emitStaticJson} = require('./public-static-data.cjs');
const {FILES, isValueLiteral, checkBindings} = require('./generate-public-interface-text-pool.cjs');
const ROOT = path.resolve(__dirname, '..');
let sharedPool;
function transformPublicText(source, context, pool = null) {
  const relative = path.relative(ROOT, context.resourcePath).replace(/\\/g,'/');
  if (!FILES.includes(relative)) throw new Error('Public interface text module is not allowlisted');
  const values=[], index=new Map(pool ? pool.values.map((value, i)=>[value,i]) : []);
  const t=babel.types;
  let binding;
  const result=babel.transformSync(source,{configFile:false,babelrc:false,sourceType:'unambiguous',compact:false,plugins:[()=>({visitor:{
    Program:{enter(p){binding=p.scope.generateUidIdentifier('publicInterfaceText');},exit(p){
      if (!values.length) return;
      const argument=p.scope.generateUidIdentifier('textIndex');
      const reader=context.utils.contextify(context.context,path.resolve(__dirname,'../src/api/publicInterfaceText.cjs'));
      const expression=pool ? `require(${JSON.stringify(reader)})` : emitStaticJson(context,encodeStaticJson(JSON.stringify(values))).replace(/^module\.exports = /,'').replace(/;$/,'');
      const lookup=babel.parseSync(expression,{configFile:false,babelrc:false}).program.body[0].expression;
      const result=pool ? t.callExpression(lookup,[t.cloneNode(argument)]) : t.memberExpression(lookup,t.cloneNode(argument),true);
      p.unshiftContainer('body',t.functionDeclaration(binding,[argument],t.blockStatement([t.returnStatement(result)])));
    }},
    StringLiteral(p){
      const value=p.node.value;
      if (!isValueLiteral(p)) return;
      let i=index.get(value);
      // Vue may combine static HTML differently under its scoped compiler.
      // An unpooled literal retains its original executable-source value.
      if (pool && i===undefined) return;
      if (i===undefined){i=values.length;index.set(value,i);}
      if (!values.includes(value)) values.push(value);
      p.replaceWith(t.callExpression(t.cloneNode(binding),[t.numericLiteral(i)]));
    }
  }})]});
  return {code:result.code,values};
}
function publicInterfaceTextLoader(source){
  this.cacheable();const relative=path.relative(ROOT,this.resourcePath).replace(/\\/g,'/');
  if (!FILES.includes(relative)) return source;
  if (!sharedPool) {sharedPool=require('../src/api/publicInterfaceTextPool.json');checkBindings(sharedPool);}
  for (const name of Object.keys(sharedPool.sources)) this.addDependency?.(path.resolve(ROOT,name));
  return transformPublicText(source,this,sharedPool).code;
}
module.exports=publicInterfaceTextLoader;
module.exports.transformPublicText=transformPublicText;
module.exports.FILES=FILES;
