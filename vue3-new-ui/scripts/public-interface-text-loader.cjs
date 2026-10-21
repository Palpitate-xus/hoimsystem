/* Store unchanged public UI strings as inert build data, after Babel compilation. */
const path = require('node:path');
const babel = require('@babel/core');
const {encodeStaticJson, emitStaticJson} = require('./public-static-data.cjs');
const ROOT = path.resolve(__dirname, '..');
const FILES = Object.freeze(['src/components/AIAssistant/index.vue','src/views/system/aiManagement.vue','src/components/ai/DocumentEvidencePanel.vue','src/components/ai/SatisfactionSourcePanel.vue']);
function transformPublicText(source, context) {
  const relative = path.relative(ROOT, context.resourcePath).replace(/\\/g,'/');
  if (!FILES.includes(relative)) throw new Error('Public interface text module is not allowlisted');
  const values=[], index=new Map();
  const t=babel.types;
  let binding;
  const result=babel.transformSync(source,{configFile:false,babelrc:false,sourceType:'unambiguous',compact:false,plugins:[()=>({visitor:{
    Program:{enter(p){binding=p.scope.generateUidIdentifier('publicInterfaceText');},exit(p){
      if (!values.length) return;
      const expression=emitStaticJson(context,encodeStaticJson(JSON.stringify(values))).replace(/^module\.exports = /,'').replace(/;$/,'');
      p.unshiftContainer('body',t.variableDeclaration('const',[t.variableDeclarator(binding,babel.parseSync(expression,{configFile:false,babelrc:false}).program.body[0].expression)]));
    }},
    StringLiteral(p){
      const value=p.node.value,parent=p.parent;
      if (Buffer.byteLength(value,'utf8')<24 || !/[\u3400-\u9fff]/.test(value)) return;
      if (t.isImportDeclaration(parent)||t.isExportNamedDeclaration(parent)||t.isExportAllDeclaration(parent)) return;
      if ((t.isObjectProperty(parent)||t.isObjectMethod(parent)||t.isClassMethod(parent))&&p.key==='key'&&!parent.computed) return;
      let i=index.get(value);if (i===undefined){i=values.length;values.push(value);index.set(value,i);}
      p.replaceWith(t.memberExpression(t.cloneNode(binding),t.numericLiteral(i),true));
    }
  }})]});
  return {code:result.code,values};
}
function publicInterfaceTextLoader(source){this.cacheable();const relative=path.relative(ROOT,this.resourcePath).replace(/\\/g,'/');return FILES.includes(relative)?transformPublicText(source,this).code:source;}
module.exports=publicInterfaceTextLoader;
module.exports.transformPublicText=transformPublicText;
module.exports.FILES=FILES;
