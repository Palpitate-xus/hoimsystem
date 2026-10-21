const fs=require('node:fs/promises'),http=require('node:http'),os=require('node:os'),path=require('node:path');
const {rspack}=require('@rspack/core'),{VueLoaderPlugin}=require('vue-loader');
// Actual component/request client and canonical production Babel; browser API is isolated.
async function startInventoryProviderHarness(){
 const root=path.resolve(__dirname,'../..'),dependencies=path.dirname(path.dirname(require.resolve('vue/package.json'))),directory=await fs.mkdtemp(path.join(os.tmpdir(),'hoim-inventory-provider-ui-'));let compiler,server;
 try{
  await fs.writeFile(path.join(directory,'store.js'),`import {createStore} from 'vuex';export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:'synthetic-inventory-session',username:'synthetic-inventory-author',permissions:['admin']}),getters:{permissions:s=>s.permissions},mutations:{permissions(s,v){s.permissions=v;},token(s,v){s.accessToken=v;},username(s,v){s.username=v;}},actions:{resetAccessToken({state}){state.accessToken='';state.permissions=[];}}}}});`);
  await fs.writeFile(path.join(directory,'router.js'),`export default {push(){return Promise.resolve();}};`);
  await fs.writeFile(path.join(directory,'entry.js'),`
import {createApp,h,reactive,KeepAlive} from 'vue';import ElementPlus from 'element-plus';import 'element-plus/dist/index.css';import store from '@/store';
import Provider from ${JSON.stringify(path.join(root,'src/components/InventoryProviderCapabilityCheck.vue'))};
import * as provider from ${JSON.stringify(path.join(root,'src/api/ai/inventoryProvider.js'))};
const scope=reactive({target:null,providers:[],mounted:true,destroyed:false}),events=[];
window.__inventoryProviderProbe={scope,events,store,provider};
createApp({render:()=>scope.destroyed?h('p','已卸载'):h(KeepAlive,null,{default:()=>!scope.mounted?h('p','已暂离'):h(Provider,{target:scope.target,providers:scope.providers,onClose:()=>{scope.target=null;events.push({type:'close'});},onEditModel:value=>events.push({type:'edit-model',value})})})}).use(store).use(ElementPlus).mount('#app');`);
  const rule=require(path.join(root,'rspack.config.js')).module.rules.find(rule=>rule.use?.loader==='babel-loader');
  compiler=rspack({context:root,mode:'development',target:'web',devtool:false,entry:path.join(directory,'entry.js'),output:{path:directory,filename:'probe.js'},resolve:{modules:[path.join(root,'node_modules'),dependencies,'node_modules'],alias:{'@/store$':path.join(directory,'store.js'),'@/router$':path.join(directory,'router.js'),'@':path.join(root,'src')}},module:{rules:[{...rule,use:{...rule.use,loader:require.resolve('babel-loader')}},{test:/\.vue$/,loader:require.resolve('vue-loader')},{test:/\.css$/,use:[require.resolve('style-loader'),require.resolve('css-loader')]}]},plugins:[new VueLoaderPlugin(),new rspack.DefinePlugin({__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false'})],optimization:{minimize:false}});
  await new Promise((resolve,reject)=>compiler.run((error,stats)=>error?reject(error):stats.hasErrors()?reject(new Error(stats.toString({all:false,errors:true}))):resolve()));await new Promise((resolve,reject)=>compiler.close(error=>error?reject(error):resolve()));compiler=null;
  const emitted=new Map(await Promise.all((await fs.readdir(directory)).filter(name=>name.endsWith('.js')&&!['entry.js','store.js','router.js'].includes(name)).map(async name=>['/'+name,await fs.readFile(path.join(directory,name))])));
  server=http.createServer((req,res)=>{if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});res.end('<!doctype html><meta charset="utf-8"><div id="app"></div><script src="/probe.js"></script>');}else if(emitted.has(req.url)){res.writeHead(200,{'Content-Type':'text/javascript'});res.end(emitted.get(req.url));}else{res.writeHead(404);res.end();}});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return{origin:`http://127.0.0.1:${server.address().port}`,async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});}};
 }catch(error){if(compiler)await new Promise(resolve=>compiler.close(resolve));if(server?.listening)await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});throw error;}
}
module.exports={startInventoryProviderHarness};
