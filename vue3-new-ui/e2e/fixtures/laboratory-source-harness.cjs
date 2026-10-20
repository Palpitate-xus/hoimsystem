const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { rspack } = require("@rspack/core");
const { VueLoaderPlugin } = require("vue-loader");

// Only the new, unmounted source components are bundled. This fixture never
// builds dist or contacts a hospital service. Every /api request must be mocked
// by the browser test, and unhandled requests fail closed on this loopback host.
async function startLaboratoryHarness() {
  const root = path.resolve(__dirname, "../..");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hoim-laboratory-ui-"));
  let compiler, server;
  const unhandled = [];
  try {
    await fs.writeFile(path.join(directory, "store.js"), `import {createStore} from "vuex"; export default createStore({modules:{user:{namespaced:true,state:()=>({accessToken:"synthetic-laboratory-session",permissions:["doctor"]}),getters:{permissions:state=>state.permissions},mutations:{permissions(state,value){state.permissions=value;},token(state,value){state.accessToken=value;}},actions:{resetAccessToken({state}){state.accessToken="";state.permissions=[];}}}}});`);
    await fs.writeFile(path.join(directory, "router.js"), `export default {push(){return Promise.resolve();}};`);
    await fs.writeFile(path.join(directory, "entry.js"), `
import {createApp,h,reactive} from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import store from "@/store";
import Panel from ${JSON.stringify(path.join(root, "src/components/InpatientLabSourcePanel/index.vue"))};
import Management from ${JSON.stringify(path.join(root, "src/views/system/AILabMappingManagement.vue"))};
import * as api from ${JSON.stringify(path.join(root, "src/api/inpatientLaboratory.js"))};
const scope=reactive({patientId:11,admissionId:"obs-admission-a",active:true,mode:"panel"});
const events=[]; window.__laboratoryProbe={scope,store,events,api};
createApp({render:()=>scope.mode==="management"?h(Management):h(Panel,{patientId:scope.patientId,admissionId:scope.admissionId,active:scope.active,onSourceCreated:value=>events.push({type:"created",value}),onSourceRevoked:value=>events.push({type:"revoked",value})})}).use(store).use(ElementPlus).mount("#app");
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
    server = http.createServer((request, response) => {
      if (request.url === "/") { response.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" }); response.end('<!doctype html><meta charset="utf-8"><title>Synthetic laboratory source components</title><div id="app"></div><script src="/probe.js"></script>'); }
      else if (request.url === "/probe.js") { response.writeHead(200, { "Content-Type": "text/javascript" }); response.end(script); }
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

module.exports = { startLaboratoryHarness };
