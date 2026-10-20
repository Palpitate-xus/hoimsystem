const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { rspack } = require("@rspack/core");
const { VueLoaderPlugin } = require("vue-loader");

// Only the new, unmounted source components are bundled. This fixture never
// builds dist or contacts a hospital service. Every /api request must be mocked
// by the browser test, and unhandled requests fail closed on this loopback host.
async function startSupportHandoverHarness() {
  const root = path.resolve(__dirname, "../..");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hoim-support-handover-ui-"));
  let compiler, server;
  const unhandled = [];
  try {
    await fs.writeFile(path.join(directory, "store.js"), `import {createStore} from "vuex"; export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:"synthetic-support-session",permissions:["doctor"]}),getters:{permissions:state=>state.permissions},mutations:{permissions(state,value){state.permissions=value;},token(state,value){state.accessToken=value;}},actions:{resetAccessToken({state}){state.accessToken="";state.permissions=[];}}}}});`);
    await fs.writeFile(path.join(directory, "router.js"), `export default {push(){return Promise.resolve();}};`);
    await fs.writeFile(path.join(directory, "entry.js"), `
import {createApp,h,reactive,KeepAlive} from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import store from "@/store";
import Assistant from ${JSON.stringify(path.join(root, "src/components/AIAssistant/index.vue"))};
import Findings from ${JSON.stringify(path.join(root, "src/components/AISupportFindings/index.vue"))};
import * as api from ${JSON.stringify(path.join(root, "src/api/aiSupportContext.js"))};
import * as sources from ${JSON.stringify(path.join(root, "src/api/inpatientSupport.js"))};
const scope=reactive({patientId:null,admissionId:"",initialInput:{},active:true,visible:true,mode:"assistant",findings:null,references:null});
const events=[];window.__handoverProbe={scope,store,events,api,sources};
createApp({render:()=>h(KeepAlive,null,{default:()=>scope.visible?(scope.mode==="findings"?h(Findings,{findings:scope.findings,expectedPatientId:scope.patientId,expectedAdmissionId:scope.admissionId,references:scope.references,active:scope.active,onInspect:value=>events.push(value)}):h(Assistant,{featureKeys:["handover_summary"],initialFeature:"handover_summary",patientId:scope.patientId,encounterRef:scope.admissionId,initialInput:scope.initialInput})):null})}).use(store).use(ElementPlus).mount("#app");
`);
    compiler = rspack({
      context: root, mode: "development", target: "web", devtool: false,
      entry: path.join(directory, "entry.js"), output: { path: directory, filename: "probe.js" },
      resolve: { modules: [path.join(root, "node_modules"), "node_modules"], alias: { "@/store$": path.join(directory, "store.js"), "@/router$": path.join(directory, "router.js"), "@": path.join(root, "src") } },
      module: { rules: [{ test: /\.vue$/, loader: require.resolve("vue-loader") }, { test: /\.css$/, use: [require.resolve("style-loader"), require.resolve("css-loader")] }] },
      plugins: [new VueLoaderPlugin(), new rspack.DefinePlugin({ __VUE_OPTIONS_API__: "true", __VUE_PROD_DEVTOOLS__: "false", __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false" })],
      optimization: { minimize: false },
    });
    await new Promise((resolve, reject) => compiler.run((failure, stats) => failure ? reject(failure) : stats.hasErrors() ? reject(new Error(stats.toString({ all: false, errors: true }))) : resolve()));
    await new Promise((resolve, reject) => compiler.close(failure => failure ? reject(failure) : resolve())); compiler = null;
    const script = await fs.readFile(path.join(directory, "probe.js"));
    const emitted = new Map(await Promise.all((await fs.readdir(directory)).filter(name => name.endsWith(".js") && !["entry.js", "store.js", "router.js"].includes(name)).map(async name => ["/" + name, await fs.readFile(path.join(directory, name))])));
    server = http.createServer((request, response) => {
      if (request.url === "/") { response.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" }); response.end('<!doctype html><meta charset="utf-8"><title>Synthetic organ support source components</title><div id="app"></div><script src="/probe.js"></script>'); }
      else if (request.url === "/probe.js") { response.writeHead(200, { "Content-Type": "text/javascript" }); response.end(script); }
      else if (emitted.has(request.url)) { response.writeHead(200, { "Content-Type": "text/javascript" }); response.end(emitted.get(request.url)); }
      else { if (request.url.startsWith("/api/")) unhandled.push({ method: request.method, path: request.url }); response.writeHead(404); response.end(); }
    });
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
    return { origin: `http://127.0.0.1:${server.address().port}`, unhandled, async close() { await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }); await fs.rm(directory, { recursive: true, force: true }); } };
  } catch (failure) {
    if (compiler) await new Promise(resolve => compiler.close(resolve));
    if (server?.listening) await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
    await fs.rm(directory, { recursive: true, force: true }); throw failure;
  }
}

module.exports = { startSupportHandoverHarness };
