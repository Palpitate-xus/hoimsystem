const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { rspack } = require('@rspack/core');
const { VueLoaderPlugin } = require('vue-loader');

// Isolated browser harness: real Vue, ElementPlus, Vuex, request client and source
// components. Only HTTP responses are intercepted by the companion UI helper.
// No source guard, HMAC projection, backend authorization or proof is replaced.
async function startSurgeryNativeHarness({ resultsOnly = false } = {}) {
  const root = path.resolve(__dirname, '../..');
  const dependencies = path.dirname(path.dirname(require.resolve('vue/package.json')));
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hoim-surgery-native-ui-'));
  const unhandled = [];
  let compiler, server;
  try {
    await fs.writeFile(path.join(directory, 'store.js'), `import {createStore} from 'vuex';export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:'synthetic-surgery-session',username:'synthetic-surgery-author',permissions:['admin']}),getters:{permissions:s=>s.permissions},mutations:{permissions(s,v){s.permissions=v;},token(s,v){s.accessToken=v;},username(s,v){s.username=v;}},actions:{resetAccessToken({state}){state.accessToken='';state.permissions=[];}}}}});`);
    await fs.writeFile(path.join(directory, 'router.js'), `export default {push(){return Promise.resolve();}};`);
    await fs.writeFile(path.join(directory, 'entry.js'), `
import {createApp,h,reactive,KeepAlive} from 'vue';
import ElementPlus from 'element-plus';import 'element-plus/dist/index.css';import store from '@/store';
${resultsOnly ? 'const Assistant=null,Input=null;' : `import Assistant from ${JSON.stringify(path.join(root, 'src/components/AIAssistant/index.vue'))};import Input from ${JSON.stringify(path.join(root, 'src/components/AISurgeryInput.vue'))};`}
import Findings from ${JSON.stringify(path.join(root, 'src/components/AISurgeryFindings.vue'))};
import Trace from ${JSON.stringify(path.join(root, 'src/components/AIRunHistory/index.vue'))};
import * as api from ${JSON.stringify(path.join(root, 'src/api/ai/surgeryScenarios.js'))};
import {supportCanonical,supportDigest} from ${JSON.stringify(path.join(root, 'src/api/inpatientSupport.js'))};
const scope=reactive({mode:'assistant',initialInput:{},ready:false,mounted:true,destroyed:false,active:true,departmentId:null,poolId:null,applicationIds:null,references:null,run:null,context:null,features:[]}),events=[];
const probe={scope,store,events,api,supportCanonical,supportDigest};window.__surgeryNativeProbe=probe;
const capture=name=>value=>{if(value)probe[name]=value;};
const render=()=>scope.mode==='trace'?h(Trace,{ref:capture('trace'),features:scope.features,active:scope.active}):scope.mode==='findings'?h(Findings,{ref:capture('findings'),run:scope.run,context:scope.context,expectedDepartmentId:scope.departmentId,expectedPoolId:scope.poolId,references:scope.references,active:scope.active,onInspect:value=>events.push({type:'inspect',value})}):scope.mode==='input'?h(Input,{ref:capture('input'),departmentId:scope.departmentId,poolId:scope.poolId,applicationIds:scope.applicationIds,initialReferences:scope.references,active:scope.active,onSelection:value=>events.push({type:'selection',value}),onAvailability:value=>events.push({type:'availability',value}),onInvalidate:()=>events.push({type:'invalidate'}),onDepartmentChange:value=>{events.push({type:'department',value});scope.departmentId=value;},onPoolChange:value=>{events.push({type:'pool',value});scope.poolId=value;}}):h(Assistant,{ref:capture('assistant'),featureKeys:['surgery_scheduling'],initialInput:scope.initialInput});
createApp({render:()=>!scope.ready?h('p','隔离手术排程集成'):scope.destroyed?h('p','已卸载'):h(KeepAlive,null,{default:()=>!scope.mounted?h('p','已暂离'):render()})}).use(store).use(ElementPlus).mount('#app');
`);
    compiler = rspack({
      context: root, mode: 'development', target: 'web', devtool: false,
      entry: path.join(directory, 'entry.js'), output: { path: directory, filename: 'probe.js' },
      resolve: { modules: [path.join(root, 'node_modules'), dependencies, 'node_modules'], alias: { '@/store$': path.join(directory, 'store.js'), '@/router$': path.join(directory, 'router.js'), '@': path.join(root, 'src') } },
      module: { rules: [{ test: /\.vue$/, loader: require.resolve('vue-loader') }, { test: /\.s[ac]ss$/, use: [require.resolve('style-loader'), require.resolve('css-loader'), require.resolve('sass-loader')] }, { test: /\.css$/, use: [require.resolve('style-loader'), require.resolve('css-loader')] }] },
      plugins: [new VueLoaderPlugin(), new rspack.DefinePlugin({ __VUE_OPTIONS_API__: 'true', __VUE_PROD_DEVTOOLS__: 'false', __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false' })],
      optimization: { minimize: false },
    });
    await new Promise((resolve, reject) => compiler.run((failure, stats) => failure ? reject(failure) : stats.hasErrors() ? reject(new Error(stats.toString({ all: false, errors: true }))) : resolve()));
    await new Promise((resolve, reject) => compiler.close(error => error ? reject(error) : resolve())); compiler = null;
    const emitted = new Map(await Promise.all((await fs.readdir(directory)).filter(name => name.endsWith('.js') && !['entry.js', 'store.js', 'router.js'].includes(name)).map(async name => ['/' + name, await fs.readFile(path.join(directory, name))])));
    server = http.createServer((request, response) => {
      if (request.url === '/') { response.writeHead(200, { 'Content-Type': 'text/html', 'Cache-Control': 'no-store' }); response.end('<!doctype html><meta charset="utf-8"><title>Synthetic surgery integration</title><div id="app"></div><script src="/probe.js"></script>'); }
      else if (emitted.has(request.url)) { response.writeHead(200, { 'Content-Type': 'text/javascript' }); response.end(emitted.get(request.url)); }
      else { if (request.url.startsWith('/api/')) unhandled.push({ method: request.method, path: request.url }); response.writeHead(404); response.end(); }
    });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    return { origin: `http://127.0.0.1:${server.address().port}`, unhandled, async close() { await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }); await fs.rm(directory, { recursive: true, force: true }); } };
  } catch (error) {
    if (compiler) await new Promise(resolve => compiler.close(resolve));
    if (server?.listening) await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
    await fs.rm(directory, { recursive: true, force: true });
    throw error;
  }
}
module.exports = { startSurgeryNativeHarness };
