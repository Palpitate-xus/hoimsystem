const fs=require('node:fs/promises'),http=require('node:http'),os=require('node:os'),path=require('node:path');
const{rspack}=require('@rspack/core'),{VueLoaderPlugin}=require('vue-loader');
async function startChargeAssistantHarness({}={}){
 const root=path.resolve(__dirname,'../..'),dependencies=path.dirname(path.dirname(require.resolve('vue/package.json'))),directory=await fs.mkdtemp(path.join(os.tmpdir(),'hoim-charge-assistant-ui-')),unhandled=[];let compiler,server;
 try{
  await fs.writeFile(path.join(directory,'store.js'),`import{createStore}from'vuex';export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:'synthetic-charge-token',username:'synthetic-charge-super',permissions:['super_admin']}),getters:{permissions:s=>s.permissions},mutations:{permissions(s,v){s.permissions=v;},token(s,v){s.accessToken=v;},username(s,v){s.username=v;}},actions:{resetAccessToken({state}){state.accessToken='';state.permissions=[];}}}}});`);
  await fs.writeFile(path.join(directory,'router.js'),`export default{push(){return Promise.resolve();}};`);
  await fs.writeFile(path.join(directory,'entry.js'),`
import{createApp,h,reactive,KeepAlive}from'vue';import ElementPlus from'element-plus';import'element-plus/dist/index.css';import store from'@/store';
import Findings from ${JSON.stringify(path.join(root,'src/components/ai/ChargeReconciliationAssistant.vue'))};
import * as api from ${JSON.stringify(path.join(root,'src/api/ai/chargeReconciliationTasks.js'))};
const scope=reactive({feature:null,featureKey:'charge_reconciliation',initialInput:{},patientId:null,encounterRef:'',active:true,mounted:true,destroyed:false}),events=[];
window.__chargeAssistantProbe={scope,events,store,api};
createApp({render:()=>scope.destroyed?h('p','已卸载'):h(KeepAlive,null,{default:()=>!scope.mounted?h('p','已暂离'):h(Findings,{...scope,onInspect:value=>events.push({type:'inspect',value}),onAvailability:value=>events.push({type:'availability',value}),onRunChange:value=>events.push({type:'run-change',value})})})}).use(store).use(ElementPlus).mount('#app');`);
  const babel=require(path.join(root,'rspack.config.js')).module.rules.find(r=>r.use?.loader==='babel-loader');
  compiler=rspack({context:root,mode:'development',target:'web',devtool:false,entry:path.join(directory,'entry.js'),output:{path:directory,filename:'probe.js'},resolve:{modules:[path.join(root,'node_modules'),dependencies,'node_modules'],alias:{'@/store$':path.join(directory,'store.js'),'@/router$':path.join(directory,'router.js'),'@':path.join(root,'src')}},resolveLoader:{modules:[dependencies,'node_modules']},module:{rules:[{...babel,use:{...babel.use,loader:require.resolve('babel-loader')}},{test:/\.vue$/,loader:require.resolve('vue-loader')},{test:/\.s[ac]ss$/,use:[require.resolve('style-loader'),require.resolve('css-loader'),require.resolve('sass-loader')]},{test:/\.css$/,use:[require.resolve('style-loader'),require.resolve('css-loader')]}]},plugins:[new VueLoaderPlugin(),new rspack.DefinePlugin({__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false'})],optimization:{minimize:false}});
  await new Promise((resolve,reject)=>compiler.run((e,s)=>e?reject(e):s.hasErrors()?reject(new Error(s.toString({all:false,errors:true}))):resolve()));await new Promise((resolve,reject)=>compiler.close(e=>e?reject(e):resolve()));compiler=null;
  const emitted=new Map(await Promise.all((await fs.readdir(directory)).filter(n=>n.endsWith('.js')&&!['entry.js','store.js','router.js'].includes(n)).map(async n=>['/'+n,await fs.readFile(path.join(directory,n))])));
  server=http.createServer((req,res)=>{if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});res.end('<!doctype html><meta charset="utf-8"><div id="app"></div><script src="/probe.js"></script>');}else if(emitted.has(req.url)){res.writeHead(200,{'Content-Type':'text/javascript'});res.end(emitted.get(req.url));}else{if(req.url.startsWith('/api/'))unhandled.push({method:req.method,path:req.url});res.writeHead(404);res.end();}});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return{origin:`http://127.0.0.1:${server.address().port}`,unhandled,async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});}};
 }catch(e){if(compiler)await new Promise(r=>compiler.close(r));if(server?.listening)await new Promise(r=>{server.close(r);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});throw e;}
}
module.exports={startChargeAssistantHarness};
