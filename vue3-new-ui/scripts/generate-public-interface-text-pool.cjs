/* Read public source literals without evaluating an application module. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const babel = require('@babel/core');
const sfc = require('@vue/compiler-sfc');
const FILES = Object.freeze(require('./public-interface-text-modules.json'));
const ROOT = path.resolve(__dirname, '..');
const OUTPUT = 'src/api/publicInterfaceTextPool.json';
const DEFAULT_GROUP=Object.freeze({files:FILES,list:'scripts/public-interface-text-modules.json',output:OUTPUT,reader:'src/api/publicInterfaceText.cjs'});
const EXTENSION_GROUP=Object.freeze({files:Object.freeze(require('./public-interface-extension-modules.json')),list:'scripts/public-interface-extension-modules.json',output:'src/api/publicInterfaceExtensionTextPool.json',reader:'src/api/publicInterfaceExtensionText.cjs'});
const GROUPS=Object.freeze([DEFAULT_GROUP,EXTENSION_GROUP]);
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const eligible = (value, filename = '') => Buffer.byteLength(value, 'utf8') >= 24 && /[\u3400-\u9fff]/.test(value) || filename.startsWith('src/api/') && Buffer.byteLength(value, 'utf8') >= 16;

function isValueLiteral(p, filename = '') {
  const t = babel.types, parent = p.parent;
  if (!eligible(p.node.value, filename)) return false;
  if (t.isImportDeclaration(parent) || t.isExportNamedDeclaration(parent) || t.isExportAllDeclaration(parent) || t.isImportSpecifier(parent) || t.isExportSpecifier(parent)) return false;
  if ((t.isObjectProperty(parent) || t.isObjectMethod(parent) || t.isClassMethod(parent) || t.isClassProperty(parent)) && p.key === 'key' && !parent.computed) return false;
  if ((t.isCallExpression(parent) || t.isNewExpression(parent)) && p.listKey === 'arguments' && p.key === 0 && (t.isImport(parent.callee) || t.isIdentifier(parent.callee, {name:'require'}) || t.isIdentifier(parent.callee, {name:'URL'}) || t.isMemberExpression(parent.callee) && (t.isIdentifier(parent.callee.object, {name:'require'}) || t.isMetaProperty(parent.callee.object)))) return false;
  return true;
}

function publicCode(text, filename) {
  if (!filename.endsWith('.vue')) return text;
  const parsed = sfc.parse(text, {filename});
  if (parsed.errors.length) throw new Error(`${filename}: invalid public interface SFC`);
  const d = parsed.descriptor;
  for (const block of [d.script, d.scriptSetup, d.template]) if (block?.src) throw new Error(`${filename}: external public interface blocks require review`);
  const script = d.script || d.scriptSetup ? sfc.compileScript(d, {id:'public-interface-text', inlineTemplate:true, isProd:true}).content : '';
  const template = !d.scriptSetup && d.template ? sfc.compileTemplate({source:d.template.content, filename, id:'public-interface-text', isProd:true, compilerOptions:{isCustomElement:tag=>tag.startsWith('ion-')}}).code : '';
  return script + '\n' + template;
}

function sourceBindings(root = ROOT, group = DEFAULT_GROUP) {
  return Object.fromEntries([...group.files, 'package-lock.json', group.list, 'scripts/generate-public-interface-text-pool.cjs'].sort().map(name => [name, hash(fs.readFileSync(path.join(root, name)))]));
}

function buildPool(root = ROOT, group = DEFAULT_GROUP) {
  const strings = new Set();
  for (const filename of group.files) {
    const code = publicCode(fs.readFileSync(path.join(root, filename), 'utf8'), filename);
    babel.transformSync(code, {configFile:false, babelrc:false, sourceType:'unambiguous', plugins:[()=>({visitor:{StringLiteral(p){if (isValueLiteral(p, filename)) strings.add(p.node.value);}}})]});
  }
  const pool = {schema_version:'hoim_public_interface_text_pool_v1', sources:sourceBindings(root,group), values:[...strings].sort()};
  if (Buffer.byteLength(JSON.stringify(pool), 'utf8') > 262144) throw new Error('Complete public interface pool exceeds the existing static record limit');
  return pool;
}

function checkBindings(pool, root = ROOT, group = DEFAULT_GROUP) {
  if (!pool || pool.schema_version !== 'hoim_public_interface_text_pool_v1' || JSON.stringify(Object.keys(pool).sort()) !== JSON.stringify(['schema_version','sources','values']) || JSON.stringify(pool.sources) !== JSON.stringify(sourceBindings(root,group)) || !Array.isArray(pool.values) || pool.values.some(v=>typeof v !== 'string' || !eligible(v, 'src/api/')) || new Set(pool.values).size !== pool.values.length || JSON.stringify([...pool.values].sort()) !== JSON.stringify(pool.values)) throw new Error('Public interface pool is stale; regenerate its complete checked-in source data');
}

if (require.main === module) {
  for(const group of GROUPS){
    const output=path.join(ROOT,group.output),text=JSON.stringify(buildPool(ROOT,group))+'\n';
    if(process.argv.includes('--check')){
      if(fs.readFileSync(output,'utf8')!==text)throw new Error('Complete public interface text pool differs from public source');
    }else fs.writeFileSync(output,text);
    console.log(JSON.stringify({output:group.output,bytes:Buffer.byteLength(text),sha256:hash(text)}));
  }
}
module.exports = {FILES, OUTPUT, ROOT, DEFAULT_GROUP, EXTENSION_GROUP, GROUPS, isValueLiteral, buildPool, checkBindings};
