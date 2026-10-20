const fs=require('node:fs/promises'),http=require('node:http'),os=require('node:os'),path=require('node:path');
const {rspack}=require('@rspack/core'),{VueLoaderPlugin}=require('vue-loader');
// Real source components and request client on an isolated loopback origin.
// Dependencies can be resolved read-only from an existing installation in a
// separate worktree. No dist, database, model or dependency installation is used.
async function startBedSeriesHarness(){
 const root=path.resolve(__dirname,'../..'),dependencies=path.dirname(path.dirname(require.resolve('vue/package.json'))),directory=await fs.mkdtemp(path.join(os.tmpdir(),'hoim-bed-series-ui-')),unhandled=[];let compiler,server;
 try{
  await fs.writeFile(path.join(directory,'store.js'),`import {createStore} from 'vuex';export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:'synthetic-bed-session',username:'synthetic-bed-author',permissions:['admin']}),getters:{permissions:s=>s.permissions},mutations:{permissions(s,v){s.permissions=v;},token(s,v){s.accessToken=v;},username(s,v){s.username=v;}},actions:{resetAccessToken({state}){state.accessToken='';state.permissions=[];}}}}});`);
  await fs.writeFile(path.join(directory,'router.js'),`export default {push(){return Promise.resolve();}};`);
  await fs.writeFile(path.join(directory,'entry.js'),`
import {createApp,h,reactive,KeepAlive} from 'vue';import ElementPlus from 'element-plus';import 'element-plus/dist/index.css';import store from '@/store';
import Sources from ${JSON.stringify(path.join(root,'src/components/AIBedSources/index.vue'))};
import Form from ${JSON.stringify(path.join(root,'src/components/AIBedSources/SourceForm.vue'))};
import * as api from ${JSON.stringify(path.join(root,'src/api/bedSeries.js'))};
import {supportCanonical,supportDigest} from ${JSON.stringify(path.join(root,'src/api/inpatientSupport.js'))};
const scope=reactive({departmentId:null,wardId:null,governance:false,active:true,mounted:true,destroyed:false,mode:'api',kind:'census'}),events=[];window.__bedSeriesProbe={scope,store,api,events,supportCanonical,supportDigest};
createApp({render:()=>scope.destroyed?h('p','已卸载'):h(KeepAlive,null,{default:()=>!scope.mounted?h('p','已暂离'):scope.mode==='sources'?h(Sources,{ref:v=>window.__bedSeriesProbe.panel=v,departmentId:scope.departmentId,wardId:scope.wardId,governance:scope.governance,active:scope.active,onSourceChanged:value=>events.push(value)}):scope.mode==='form'?h(Form,{ref:v=>window.__bedSeriesProbe.form=v,kind:scope.kind,onValidity:value=>events.push({type:'validity',value})}):h('p','病区床位原来源契约核对')})}).use(store).use(ElementPlus).mount('#app');`);
  compiler=rspack({context:root,mode:'development',target:'web',devtool:false,entry:path.join(directory,'entry.js'),output:{path:directory,filename:'probe.js'},resolve:{modules:[path.join(root,'node_modules'),dependencies,'node_modules'],alias:{'@/store$':path.join(directory,'store.js'),'@/router$':path.join(directory,'router.js'),'@':path.join(root,'src')}},module:{rules:[{test:/\.vue$/,loader:require.resolve('vue-loader')},{test:/\.s[ac]ss$/,use:[require.resolve('style-loader'),require.resolve('css-loader'),require.resolve('sass-loader')]},{test:/\.css$/,use:[require.resolve('style-loader'),require.resolve('css-loader')]}]},plugins:[new VueLoaderPlugin(),new rspack.DefinePlugin({__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false'})],optimization:{minimize:false}});
  await new Promise((resolve,reject)=>compiler.run((failure,stats)=>failure?reject(failure):stats.hasErrors()?reject(new Error(stats.toString({all:false,errors:true}))):resolve()));await new Promise((resolve,reject)=>compiler.close(error=>error?reject(error):resolve()));compiler=null;
  const emitted=new Map(await Promise.all((await fs.readdir(directory)).filter(name=>name.endsWith('.js')&&!['entry.js','store.js','router.js'].includes(name)).map(async name=>['/'+name,await fs.readFile(path.join(directory,name))])));
  server=http.createServer((request,response)=>{if(request.url==='/'){response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});response.end('<!doctype html><meta charset="utf-8"><title>Synthetic bed originals</title><div id="app"></div><script src="/probe.js"></script>');}else if(emitted.has(request.url)){response.writeHead(200,{'Content-Type':'text/javascript'});response.end(emitted.get(request.url));}else{if(request.url.startsWith('/api/'))unhandled.push({method:request.method,path:request.url});response.writeHead(404);response.end();}});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});return{origin:`http://127.0.0.1:${server.address().port}`,unhandled,async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});}};
 }catch(error){if(compiler)await new Promise(resolve=>compiler.close(resolve));if(server?.listening)await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});await fs.rm(directory,{recursive:true,force:true});throw error;}
}
module.exports={startBedSeriesHarness};
