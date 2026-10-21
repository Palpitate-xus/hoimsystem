const assert=require('node:assert/strict');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const {transformPublicText}=require('./public-interface-text-loader.cjs');
const codec=require('../src/api/schemaDataCodec.cjs');
const root=path.resolve(__dirname,'..');
const context={resourcePath:path.join(root,'src/components/AIAssistant/index.vue'),context:root,utils:{contextify:(_c,p)=>p}};
const literal='完整原文\ufeff\r\n患者😀中文文本必须保留全部 Unicode 字符';
test('compiled interface strings preserve runtime value, CRLF, BOM, supplementary characters and repeated identity',()=>{
 const input=`module.exports={value:${JSON.stringify(literal)},again:${JSON.stringify(literal)},'中文对象键保留原始类型不可改变':42,short:'短句'};`;
 const result=transformPublicText(input,context),module={exports:{}};
 vm.runInNewContext(result.code,{module,require:()=>codec});
 assert.equal(module.exports.value,literal);assert.equal(module.exports.again,literal);
 assert.equal(module.exports['中文对象键保留原始类型不可改变'],42);assert.equal(module.exports.short,'短句');
 assert.deepEqual(result.values,[literal]);assert(!result.code.includes(literal));
});
test('public strings are inert data, including HTML and code-like quotes',()=>{
 const value='原始界面文本 </script><script>globalThis.INJECTED=true</script> 必须原样保留';
 const module={exports:{}};const result=transformPublicText(`module.exports=${JSON.stringify(value)};`,context);
 const scope={module,require:()=>codec};vm.runInNewContext(result.code,scope);
 assert.equal(module.exports,value);assert.equal(scope.INJECTED,undefined);assert(!result.code.includes('</script>'));
});
test('import sources, export sources and object keys retain static grammar',()=>{
 const src='import x from "中文导入路径超过二十四字节但必须保留静态模块语法"; export {x} from "中文导出路径超过二十四字节但必须保留静态模块语法";';
 assert.deepEqual(transformPublicText(src,context).values,[]);
});
test('other source and clinical modules cannot use the interface loader',()=>{
 assert.throws(()=>transformPublicText('module.exports={};',{...context,resourcePath:path.join(root,'src/api/patient.js')}),/not allowlisted/);
});

test('canonical Babel loader remains directly discoverable by existing isolated harnesses',()=>{
 const config=require('../rspack.config.js');
 const rule=config.module.rules.find(rule=>rule.use?.loader==='babel-loader');
 assert(rule);assert.deepEqual(rule.options,undefined);
 assert.deepEqual(rule.use.options.presets,['@babel/preset-env']);
 const hook=require('./public-interface-babel.cjs')();
 const emitted=[];const ctx={...context,cacheable(){},emitFile:(...args)=>emitted.push(args)};
 const pool=require('../src/api/publicInterfaceTextPool.json');
 const changed=hook.result.call(ctx,{code:'module.exports='+JSON.stringify(pool.values[0])+';',map:null});
 assert.equal(emitted.length,0);assert(changed.code.includes('publicInterfaceText.cjs'));
 const original={code:'module.exports=1;',map:{unchanged:true}};
 assert.equal(hook.result.call({...ctx,resourcePath:path.join(root,'src/api/patient.js')},original),original);
});

test('shared text is callable before module initialization in a circular import',()=>{
 const values=[literal],input=`function read(){return ${JSON.stringify(literal)}};require('cycle')(read);module.exports=read;`;
 const result=transformPublicText(input,context,{values}),module={exports:{}},seen=[];
 vm.runInNewContext(result.code,{module,require:name=>name==='cycle'?read=>seen.push(read()):index=>values[index]});
 assert.deepEqual(seen,[literal]);assert.equal(module.exports(),literal);
});

test('a shared pool returns complete strings without coercion and leaves unknown compiled literals intact',()=>{
 const values=[literal],unknown='未收录的 Vue 静态 HTML 必须保持原本编译结果 </div>';
 const input=`module.exports={known:${JSON.stringify(literal)},unknown:${JSON.stringify(unknown)},key:{${JSON.stringify(literal)}:1}};`;
 const result=transformPublicText(input,context,{values}),module={exports:{}};
 vm.runInNewContext(result.code,{module,require:()=>index=>values[index]});
 assert.equal(module.exports.known,literal);assert.equal(module.exports.unknown,unknown);assert.equal(module.exports.key[literal],1);
 assert.deepEqual(result.values,[literal]);assert(result.code.includes(unknown));
});

test('module requests, URL assets and named module keys keep their static grammar',()=>{
 const code=`const x=require(${JSON.stringify(literal)});const y=import(${JSON.stringify(literal)});new URL(${JSON.stringify(literal)},import.meta.url);export {x as ${JSON.stringify(literal)}};`;
 assert.deepEqual(transformPublicText(code,context).values,[]);
});
