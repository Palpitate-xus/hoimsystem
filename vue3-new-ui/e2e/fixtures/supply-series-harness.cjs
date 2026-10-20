const fs=require('node:fs/promises'),http=require('node:http'),os=require('node:os'),path=require('node:path');
const {rspack}=require('@rspack/core'),{VueLoaderPlugin}=require('vue-loader');
// Compiles only actual new source/metadata code with the real request client.
// Dependencies are resolved read-only; no application dist/backend is used.
async function startSupplySeriesHarness({mode='series'}={}){
 const root=path.resolve(__dirname,'../..'),dependencies=path.dirname(path.dirname(require.resolve('vue/package.json'))),directory=await fs.mkdtemp(path.join(os.tmpdir(),'hoim-supply-series-ui-')),unhandled=[];let compiler,server;
 try{
  await fs.writeFile(path.join(directory,'store.js'),`import {createStore} from 'vuex';export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:'synthetic-supply-series-session',username:'synthetic-supply-series-author',permissions:['admin']}),getters:{permissions:s=>s.permissions},mutations:{permissions(s,v){s.permissions=v;},token(s,v){s.accessToken=v;}},actions:{resetAccessToken({state}){state.accessToken='';state.permissions=[];}}}}});`);
  await fs.writeFile(path.join(directory,'router.js'),`export default {push(){return Promise.resolve();}};`);
  await fs.writeFile(path.join(directory,'entry.js'),`
import {createApp,h,reactive,KeepAlive} from 'vue';import ElementPlus from 'element-plus';import 'element-plus/dist/index.css';import store from '@/store';
import Panel from ${JSON.stringify(path.join(root,mode==='input'?'src/components/SupplyInput.vue':'src/components/SupplySeriesPanel.vue'))};
import * as api from ${JSON.stringify(path.join(root,'src/api/ai/supplySeries.js'))};
import {supportDigest,supportCanonical} from ${JSON.stringify(path.join(root,'src/api/inpatientSupport.js'))};
const scope=reactive({ready:false,mounted:true,destroyed:false,itemKind:null,itemId:null,active:true,governance:false,initialReferences:null}),events=[];
window.__supplySeriesProbe={scope,store,api,events,supportDigest,supportCanonical};
createApp({render:()=>!scope.ready?h('p','准备合成工程核对'):scope.destroyed?h('p','已卸载'):h(KeepAlive,null,{default:()=>!scope.mounted?h('p','已暂离'):h(Panel,{ref:v=>{if(v)window.__supplySeriesProbe.panel=v;},itemKind:scope.itemKind,itemId:scope.itemId,active:scope.active,governance:scope.governance,initialReferences:scope.initialReferences,onSelection:value=>events.push({type:'selection',value}),onAvailability:value=>events.push({type:'availability',value}),onScopeChange:value=>events.push({type:'scope-change',value}),onSelect:value=>events.push({type:'select',value}),onSeriesChanged:value=>events.push({type:'series-changed',value}),onInvalidate:()=>events.push({type:'invalidate'})})})}).use(store).use(ElementPlus).mount('#app');`);
  compiler=rspack({context:root,mode:'development',target:'web',devtool:false,entry:path.join(directory,'entry.js'),output:{path:directory,filename:'probe.js'},resolve:{modules:[path.join(root,'node_modules'),dependencies,'node_modules'],alias:{'@/store$':path.join(directory,'store.js'),'@/router$':path.join(directory,'router.js'),'@':path.join(root,'src')}},module:{rules:[{test:/\.vue$/,loader:require.resolve('vue-loader')},{test:/\.s[ac]ss$/,use:[require.resolve('style-loader'),require.resolve('css-loader'),require.resolve('sass-loader')]},{test:/\.css$/,use:[require.resolve('style-loader'),require.resolve('css-loader')]}]},plugins:[new VueLoaderPlugin(),new rspack.DefinePlugin({__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false'})],optimization:{minimize:false}});
  await new Promise((resolve,reject)=>compiler.run((error,stats)=>error?reject(error):stats.hasErrors()?reject(new Error(stats.toString({all:false,errors:true}))):resolve()));await new Promise((resolve,reject)=>compiler.close(error=>error?reject(error):resolve()));compiler=null;
  const emitted=new Map(await Promise.all((await fs.readdir(directory)).filter(name=>name.endsWith('.js')&&!['entry.js','store.js','router.js'].includes(name)).map(async name=>['/'+name,await fs.readFile(path.join(directory,name))])));
  server=http.createServer((req,res)=>{if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});res.end('<!doctype html><meta charset="utf-8"><div id="app"></div><script src="/probe.js"></script>');}else if(emitted.has(req.url)){res.writeHead(200,{'Content-Type':'text/javascript'});res.end(emitted.get(req.url));}else{if(req.url.startsWith('/api/'))unhandled.push({method:req.method,path:req.url});res.writeHead(404);res.end();}});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return{origin:`http://127.0.0.1:${server.address().port}`,unhandled,async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});}};
 }catch(error){if(compiler)await new Promise(resolve=>compiler.close(resolve));if(server?.listening)await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});throw error;}
}
module.exports={startSupplySeriesHarness};
