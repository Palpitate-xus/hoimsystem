/**
 * Isolated real-browser request fixture. Only UI/store/router effects are stubbed;
 * request.js, configuration, API functions, Axios, qs and lodash are repository
 * sources. Network traffic uses a real HTTP server bound to loopback only.
 */
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { rspack } = require("@rspack/core");

const root = path.resolve(__dirname, "..");
const digest = bytes => createHash("sha256").update(bytes).digest("hex");

async function bundleHarness(directory, requestSource) {
  await fs.writeFile(path.join(directory, "effects.js"), `export const effects={messages:[],dispatches:[],routes:[],loadingOpened:0,loadingClosed:0}; export const state={user:{accessToken:""}};`);
  await fs.writeFile(path.join(directory, "store.js"), `import {effects,state} from "./effects"; export default {state,dispatch(name){effects.dispatches.push(name);if(name==="user/resetAccessToken")state.user.accessToken="";return Promise.resolve();}};`);
  await fs.writeFile(path.join(directory, "router.js"), `import {effects} from "./effects"; export default {push(value){effects.routes.push(value);return Promise.resolve();}};`);
  await fs.writeFile(path.join(directory, "element.js"), `import {effects} from "./effects";export const ElMessage={error(message){effects.messages.push(String(message));}};export const ElLoading={service(){effects.loadingOpened++;return {close(){effects.loadingClosed++;}};}};`);
  const source = name => JSON.stringify(path.join(root, "src", name));
  await fs.writeFile(path.join(directory, "entry.js"), `
import axios from "axios";
import request from ${JSON.stringify(requestSource)};
import * as ai from ${source("api/ai.js")};
import * as nursing from ${source("api/nursing.js")};
import * as imports from ${source("api/dataImportExport.js")};
import * as config from "@/config";
import {effects,state} from "./effects";
window.__requestRegression={request,ai,nursing,imports,config,effects,state,axiosVersion:axios.VERSION,nativeAdapter:axios.getAdapter(request.defaults.adapter).adapterName};
`);
  const compiler = rspack({
    mode: "development", target: "web", devtool: false, context: root,
    entry: path.join(directory, "entry.js"),
    output: { path: directory, filename: "harness.js" },
    resolve: { modules: [path.join(root, "node_modules"), "node_modules"], alias: {
      "@/utils/request$": requestSource,
      "@/store$": path.join(directory, "store.js"),
      "@/router$": path.join(directory, "router.js"),
      "element-plus$": path.join(directory, "element.js"),
      "@": path.join(root, "src"),
    } },
    optimization: { minimize: false },
  });
  try {
    await new Promise((resolve, reject) => compiler.run((error, stats) => {
      if (error) return reject(error);
      if (stats.hasErrors()) return reject(new Error(stats.toString({ all: false, errors: true })));
      resolve();
    }));
  } finally {
    await new Promise((resolve, reject) => compiler.close(error => error ? reject(error) : resolve()));
  }
}

async function startRequestHarness({ requestSource = path.join(root, "src/utils/request.js") } = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hoim-request-regression-"));
  let server, sink;
  const requests = [], sinkRequests = [], counts = new Map(), timers = new Set();
  try {
    await bundleHarness(directory, requestSource);
    const script = await fs.readFile(path.join(directory, "harness.js"));
    server = http.createServer(async (request, response) => {
      const parsed = new URL(request.url, "http://127.0.0.1");
      if (parsed.pathname === "/") {
        response.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
        response.end('<!doctype html><title>Synthetic request regression</title><script src="/harness.js"></script>');
        return;
      }
      if (parsed.pathname === "/harness.js") {
        response.writeHead(200, { "Content-Type": "text/javascript", "Cache-Control": "no-store" }); response.end(script); return;
      }
      if (!parsed.pathname.startsWith("/api/")) { response.writeHead(404); response.end(); return; }
      const key = request.method + " " + parsed.pathname;
      counts.set(key, (counts.get(key) || 0) + 1);
      const record = { method: request.method, path: parsed.pathname, query: Object.fromEntries(parsed.searchParams), token: request.headers.accesstoken || null, contentType: request.headers["content-type"] || "", rawSize: 0, rawHash: null };
      requests.push(record);
      const chunks = [];
      try {
        let size = 0;
        for await (const chunk of request) {
          size += chunk.length;
          if (size > 1024 * 1024) { response.writeHead(413); response.end(); return; }
          chunks.push(chunk);
        }
        const bytes = Buffer.concat(chunks);
        record.rawSize = bytes.length; record.rawHash = digest(bytes);
        record.text = bytes.toString("utf8");
        if (record.contentType.startsWith("multipart/form-data")) {
          const form = await new Request("http://127.0.0.1/synthetic", { method: "POST", headers: { "Content-Type": record.contentType }, body: bytes }).formData();
          record.parts = [];
          for (const [name, part] of form.entries()) {
            if (typeof part === "string") record.parts.push({ name, value: part });
            else {
              const contents = Buffer.from(await part.arrayBuffer());
              record.parts.push({ name, filename: part.name, contentType: part.type, size: contents.length, sha256: digest(contents), base64: contents.toString("base64") });
            }
          }
        } else if (record.contentType.startsWith("application/json") && bytes.length) record.json = JSON.parse(record.text);
      } catch (error) {
        record.parseError = error.name;
        if (!response.destroyed) { response.writeHead(400); response.end(JSON.stringify({ code: 400, msg: "synthetic fixture rejected body" })); }
        return;
      }
      const send = (status, value, headers = {}) => {
        if (!response.destroyed) { response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers }); response.end(JSON.stringify(value)); }
      };
      if (parsed.pathname.includes("/network-retry") && counts.get(key) === 1) { request.socket.destroy(); return; }
      if (parsed.pathname.includes("/retry") && counts.get(key) <= Number(parsed.searchParams.get("failures") || 2)) {
        send(Number(parsed.searchParams.get("status") || 503), { code: 503, msg: "synthetic transient failure" }, { "Retry-After": parsed.searchParams.get("retry_after") || "0" }); return;
      }
      if (parsed.pathname.includes("/always-error")) { send(Number(parsed.searchParams.get("status") || 503), { code: 503, msg: "synthetic error" }, { "Retry-After": "0" }); return; }
      if (parsed.pathname.includes("/unauthorized")) { send(401, { code: 401, msg: "synthetic credential expired" }); return; }
      if (parsed.pathname.includes("/business-error")) { send(200, { code: 422, msg: "synthetic business rejection" }); return; }
      if (parsed.pathname.includes("/binary-json")) { send(200, { code: 422, msg: "HTTP-success bytes are opaque in binary mode" }); return; }
      if (parsed.pathname.includes("/content") || parsed.pathname.includes("/pixels") || parsed.pathname.includes("/export/") || parsed.pathname.includes("/template/")) {
        response.writeHead(200, { "Content-Type": "application/octet-stream", "Cache-Control": "no-store" }); response.end(Buffer.from([0, 255, 1, 128, 13, 10, 0, 42])); return;
      }
      if (parsed.pathname.includes("/native-abort") && counts.get(key) > 1) { send(200, { code: 200, msg: "synthetic retry after native abort", data: record }); return; }
      if (parsed.pathname.includes("/slow") || parsed.pathname.includes("/native-abort")) {
        const timer = setTimeout(() => { timers.delete(timer); send(200, { code: 200, msg: "synthetic delayed success", data: record }); }, 1500);
        timers.add(timer); timer.unref(); return;
      }
      send(200, { code: 200, msg: "synthetic success", data: record });
    });
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
    const origin = `http://127.0.0.1:${server.address().port}`;
    sink = http.createServer((request, response) => {
      const record = { method: request.method, path: request.url, token: request.headers.accesstoken || null };
      sinkRequests.push(record);
      response.writeHead(request.method === "OPTIONS" ? 204 : 200, {
        "Content-Type": "application/json", "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "accesstoken, content-type", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Cache-Control": "no-store",
      });
      response.end(request.method === "OPTIONS" ? undefined : JSON.stringify({ code: 200, msg: "synthetic second-origin sink", data: record }));
    });
    await new Promise((resolve, reject) => { sink.once("error", reject); sink.listen(0, "127.0.0.1", resolve); });
    return {
      origin,
      sinkOrigin: `http://127.0.0.1:${sink.address().port}`,
      requests, sinkRequests,
      count: (method, pathname) => counts.get(method.toUpperCase() + " " + pathname) || 0,
      clear: () => { requests.length = 0; sinkRequests.length = 0; counts.clear(); },
      installedAxios: require("axios/package.json").version,
      lockedAxios: JSON.parse(await fs.readFile(path.join(root, "package-lock.json"), "utf8")).packages["node_modules/axios"].version,
      async close() {
        for (const timer of timers) clearTimeout(timer);
        await Promise.all([server, sink].map(item => new Promise(resolve => { item.close(resolve); item.closeAllConnections(); })));
        await fs.rm(directory, { recursive: true, force: true });
      },
    };
  } catch (error) {
    for (const item of [server, sink]) if (item?.listening) await new Promise(resolve => { item.close(resolve); item.closeAllConnections(); });
    await fs.rm(directory, { recursive: true, force: true });
    throw error;
  }
}

module.exports = { startRequestHarness };
