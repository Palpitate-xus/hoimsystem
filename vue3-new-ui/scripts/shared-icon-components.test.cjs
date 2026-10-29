const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const babel=require('@babel/core'),vue=require('vue'),original=require('@element-plus/icons-vue');
const {renderToString}=require('@vue/server-renderer');
const source=fs.readFileSync(path.resolve(__dirname,'../src/components/sharedIconComponents.js'),'utf8');
const compiled=babel.transformSync(source,{configFile:false,babelrc:false,presets:[[require.resolve('@babel/preset-env'),{targets:{node:'current'},modules:'commonjs'}]]}).code;
const moduleValue={exports:{}};
vm.runInNewContext(compiled,{module:moduleValue,exports:moduleValue.exports,require:name=>name==='vue'?vue:name==='@/assets/element-plus-icon-gallery.svg'?'':(()=>{throw Error('Unexpected dependency '+name)})()});
const actual=moduleValue.exports;
function attributes(svg){return Object.fromEntries(Array.from(svg.match(/^<svg ([^>]+)>/)[1].matchAll(/([\w:-]+)="([^"]*)"/g),m=>[m[1],m[2]]));}
test('all installed named exports preserve component identity, default SVG attributes and caller attributes exactly once',async()=>{
 assert.deepEqual(Object.keys(actual).sort(),Object.keys(original).sort());
 for(const name of Object.keys(original)){
  assert.equal(actual[name].name,original[name].name,name);
  const attrs={class:'external-class','aria-label':'原始可访问名称',style:{color:'rgb(1, 2, 3)'},viewBox:'0 0 1024 1024','data-verification':name};
  const a=await renderToString(vue.createSSRApp({render:()=>vue.h(actual[name],attrs)}));
  const b=await renderToString(vue.createSSRApp({render:()=>vue.h(original[name],attrs)}));
  assert.deepEqual(attributes(a),attributes(b),name);
  assert.equal(a.match(/external-class/g)?.length,1,name);
  assert(a.includes('href="#icon-'+name+'"'),name);
 }
});
