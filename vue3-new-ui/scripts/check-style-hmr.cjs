/* Real project SCSS loaders and a disposable loopback-only HMR application. */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const net = require("node:net");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const reportPath = "/tmp/hoim-deps-style-hmr.json";
const started = performance.now();
const report = {
  scope: "Actual project Rspack/style-loader/css-loader/sass-loader SCSS variable injection, file watching and browser HMR; not Sass CLI or every chokidar mode",
  application_data_used: false,
  product_sources_modified: false,
  external_network_allowed: false,
  proxy_enabled: false,
  full_product_build_performed: false,
  passed: false,
};
const blockedConnections = [];
const originalConnect = net.Socket.prototype.connect;
// Guard Node's actual outbound sockets before loading the project config or
// dev-server. Listening remains separate and explicitly bound to 127.0.0.1.
net.Socket.prototype.connect = function (...args) {
  // net.createConnection can pass Node's already-normalized [options, cb]
  // tuple to Socket.connect; inspect its actual options as well.
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  const options = first && typeof first === "object" ? first : null;
  const localPipe = typeof first === "string" || Boolean(options?.path);
  const host = options ? options.host || options.hostname || "localhost" : typeof args[1] === "string" ? args[1] : "localhost";
  if (!localPipe && host !== "127.0.0.1") {
    blockedConnections.push({ source: "node", host });
    throw new Error("Style probe refuses outbound sockets outside 127.0.0.1");
  }
  return originalConnect.apply(this, args);
};

const hash = value => crypto.createHash("sha256").update(value).digest("hex");
const bounded = (promise, label, milliseconds = 30000) => {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out`)), milliseconds); }),
  ]).finally(() => clearTimeout(timer));
};

async function version(name, from = __filename) {
  const { createRequire } = require("node:module");
  const resolve = createRequire(from).resolve;
  let directory;
  try { return JSON.parse(await fs.readFile(resolve(`${name}/package.json`), "utf8")).version; }
  catch { directory = path.dirname(resolve(name)); }
  while (directory !== path.dirname(directory)) {
    try {
      const value = JSON.parse(await fs.readFile(path.join(directory, "package.json"), "utf8"));
      if (value.name === name) return value.version;
    } catch { /* Continue to the package root when exports hide package.json. */ }
    directory = path.dirname(directory);
  }
  throw new Error(`Cannot determine installed version of ${name}`);
}

function rgb(hex) {
  return `rgb(${[1, 3, 5].map(index => Number.parseInt(hex.slice(index, index + 2), 16)).join(", ")})`;
}

async function main() {
  let temporaryRoot, browser, server, compiler;
  const cleanupErrors = [];
  const protectedPaths = ["rspack.config.js", "src/styles/variables.scss", "package.json", "package-lock.json"];
  const originalHashes = {};
  try {
    for (const name of protectedPaths) originalHashes[name] = hash(await fs.readFile(path.join(projectRoot, name)));
    const { rspack } = require("@rspack/core");
    const { RspackDevServer } = require("@rspack/dev-server");
    const { chromium } = require("@playwright/test");
    const projectConfig = require(path.join(projectRoot, "rspack.config.js"));
    const scssRule = projectConfig.module.rules.find(rule => rule.test instanceof RegExp && rule.test.test("probe.scss"));
    const sassLoader = scssRule?.use?.find(loader => typeof loader === "object" && loader.loader === "sass-loader");
    assert.equal(typeof sassLoader?.options?.additionalData, "function", "Use the actual project variable injector");
    const variables = await fs.readFile(path.join(projectRoot, "src/styles/variables.scss"), "utf8");
    const defaultHex = variables.match(/\$base-color-default:\s*(#[\da-f]{6})\s*;/i)?.[1];
    const greenHex = variables.match(/\$base-color-green:\s*(#[\da-f]{6})\s*;/i)?.[1];
    assert.ok(defaultHex && greenHex, "Read actual original SCSS theme variables");
    report.versions = Object.fromEntries(await Promise.all(["@rspack/core", "@rspack/dev-server", "sass", "sass-loader", "style-loader", "css-loader", "@playwright/test"].map(async name => [name, await version(name)])));
    report.versions.node = process.version;
    report.versions.sass_private_chokidar = await version("chokidar", require.resolve("sass"));
    report.project_config_sha256 = originalHashes["rspack.config.js"];
    report.original_variables_sha256 = originalHashes["src/styles/variables.scss"];
    report.additional_data_sha256 = hash(sassLoader.options.additionalData.toString());
    temporaryRoot = await fs.mkdtemp("/tmp/hoim-style-hmr-");
    const entry = path.join(temporaryRoot, "entry.js");
    const stylesheet = path.join(temporaryRoot, "probe.scss");
    const output = path.join(temporaryRoot, "output");
    const scss = (color, border) => `#style-probe { color: ${color}; background-color: $base-menu-background; padding: $base-padding; border: ${border}px solid $base-color-green; }\n`;
    await fs.writeFile(stylesheet, scss("$base-color-default", 3));
    await fs.writeFile(entry, `import "./probe.scss";
      window.__hoimStyleProbe = { boot: crypto.randomUUID(), timeOrigin: performance.timeOrigin, statuses: [], hmr: !!module.hot };
      if (module.hot) module.hot.addStatusHandler(status => window.__hoimStyleProbe.statuses.push(status));
    `);
    const compilations = [];
    report.compilations = compilations;
    let initialResolve, initialReject;
    const initial = new Promise((resolve, reject) => { initialResolve = resolve; initialReject = reject; });
    initial.catch(() => {}); // Retain failures for await after server startup.
    compiler = rspack({
      mode: "development",
      context: projectConfig.context,
      ...(projectConfig.target ? { target: projectConfig.target } : {}),
      entry: { probe: entry },
      output: { path: output, publicPath: "/", filename: "probe.js" },
      module: projectConfig.module,
      resolve: projectConfig.resolve,
      ...(projectConfig.resolveLoader ? { resolveLoader: projectConfig.resolveLoader } : {}),
      // Product plugins/HTML/main entry are not required to exercise its exact
      // module rules. No product output, cache, proxy or mock server is started.
      plugins: [],
      cache: false,
      devtool: false,
      optimization: { minimize: false, splitChunks: false, runtimeChunk: false },
      infrastructureLogging: { level: "error" },
      stats: "errors-only",
    });
    compiler.hooks.failed.tap("HoimStyleProbe", error => initialReject(error));
    compiler.hooks.done.tap("HoimStyleProbe", stats => {
      const details = stats.toJson({ all: false, errors: true, warnings: true });
      const item = {
        hash: stats.hash,
        errors: details.errors?.length || 0,
        warnings: details.warnings?.length || 0,
        original_variables_dependency: [...stats.compilation.fileDependencies].includes(path.join(projectRoot, "src/styles/variables.scss")),
      };
      compilations.push(item);
      if (stats.hasErrors()) initialReject(new Error(details.errors.map(error => error.message).join("\n")));
      else initialResolve();
    });
    server = new RspackDevServer({
      host: "127.0.0.1",
      port: 0,
      allowedHosts: ["127.0.0.1"],
      hot: true,
      liveReload: true,
      open: false,
      bonjour: false,
      static: false,
      historyApiFallback: false,
      proxy: [],
      client: { overlay: false, logging: "none", reconnect: false },
      devMiddleware: { publicPath: "/", writeToDisk: true },
      setupMiddlewares: middlewares => {
        middlewares.unshift({
          name: "isolated-style-probe-html",
          middleware: (request, response, next) => {
            if (request.method !== "GET" || request.url !== "/") return next();
            response.setHeader("Content-Type", "text/html; charset=utf-8");
            response.end("<!doctype html><html><head><meta charset='utf-8'><link rel='icon' href='data:,'></head><body><div id='style-probe'>isolated SCSS variable/HMR probe</div><script defer src='/probe.js'></script></body></html>");
          },
        });
        return middlewares;
      },
    }, compiler);
    await bounded(server.start(), "Loopback dev server startup");
    await bounded(initial, "Initial real SCSS compilation", 45000);
    const address = server.server.address();
    assert.equal(address.address, "127.0.0.1");
    assert.ok(address.port > 0);
    const origin = `http://127.0.0.1:${address.port}`;
    report.loopback_address = origin;
    report.hot_only = false;
    report.live_reload_enabled = true;
    browser = await chromium.launch({ headless: true, args: ["--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--no-first-run", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"] });
    const context = await browser.newContext({ serviceWorkers: "block" });
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin === origin) return route.continue();
      blockedConnections.push({ source: "browser_http", url: route.request().url() });
      return route.abort("blockedbyclient");
    });
    await context.routeWebSocket("**/*", socket => {
      const url = new URL(socket.url());
      if (url.protocol === "ws:" && url.hostname === "127.0.0.1" && url.port === String(address.port)) socket.connectToServer();
      else {
        blockedConnections.push({ source: "browser_websocket", url: socket.url() });
        socket.close({ code: 1008, reason: "Loopback-only probe" });
      }
    });
    const page = await context.newPage();
    const pageErrors = [], websocketMessages = [];
    let navigations = 0;
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("framenavigated", frame => { if (frame === page.mainFrame()) navigations += 1; });
    page.on("websocket", socket => socket.on("framereceived", frame => {
      try { websocketMessages.push(JSON.parse(String(frame.payload)).type); } catch { /* Ignore non-JSON frames. */ }
    }));
    await page.goto(origin, { waitUntil: "load", timeout: 30000 });
    const read = () => page.evaluate(() => {
      const style = getComputedStyle(document.querySelector("#style-probe"));
      return { color: style.color, background: style.backgroundColor, padding: style.paddingTop, border: style.borderLeftWidth, boot: window.__hoimStyleProbe?.boot, timeOrigin: window.__hoimStyleProbe?.timeOrigin, hmr: window.__hoimStyleProbe?.hmr, statuses: [...(window.__hoimStyleProbe?.statuses || [])], sentinel: window.__hoimStyleSentinel };
    });
    await page.waitForFunction(color => getComputedStyle(document.querySelector("#style-probe")).color === color && window.__hoimStyleProbe?.hmr === true, rgb(defaultHex), { timeout: 30000 });
    const websocketDeadline = Date.now() + 30000;
    while (!websocketMessages.some(type => type === "ok" || type === "still-ok")) {
      if (Date.now() >= websocketDeadline) throw new Error("Actual HMR WebSocket readiness timed out");
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    const sentinel = crypto.randomUUID();
    await page.evaluate(value => { window.__hoimStyleSentinel = value; }, sentinel);
    const before = await read();
    assert.equal(before.padding, "20px");
    assert.equal(before.border, "3px");
    const initialNavigations = navigations;
    const updates = [];
    for (const [variable, expectedColor, border] of [["$base-color-green", rgb(greenHex), 7], ["$base-color-default", rgb(defaultHex), 11]]) {
      const compilationCount = compilations.length;
      // The real filesystem write must trigger the watcher: no manual
      // invalidate, compiler.run or reload calls are used after startup.
      await fs.writeFile(stylesheet, scss(variable, border));
      await page.waitForFunction(({ color, width }) => {
        const style = getComputedStyle(document.querySelector("#style-probe"));
        return style.color === color && style.borderLeftWidth === width;
      }, { color: expectedColor, width: `${border}px` }, { timeout: 30000 });
      const after = await read();
      assert.ok(compilations.length > compilationCount, "Filesystem watching triggered a real rebuild");
      assert.equal(after.boot, before.boot, "Entry did not restart");
      assert.equal(after.timeOrigin, before.timeOrigin, "Document did not reload");
      assert.equal(after.sentinel, sentinel, "Window state survived actual CSS HMR");
      assert.equal(after.padding, before.padding);
      assert.equal(after.background, before.background);
      assert.ok(after.statuses.includes("apply"), "Actual HMR apply lifecycle was observed");
      assert.equal(navigations, initialNavigations);
      updates.push(after);
    }
    assert.deepEqual(pageErrors, []);
    assert.deepEqual(blockedConnections, []);
    assert.ok(compilations.every(item => item.errors === 0));
    assert.ok(compilations.every(item => item.original_variables_dependency), "The original variables file participates in the real loader dependency graph");
    report.initial_css = before;
    report.hot_updates = updates;
    report.compilations = compilations;
    report.document_navigations = navigations;
    report.actual_hmr_without_full_reload = true;
    report.actual_variable_injection = true;
    report.filesystem_updates_detected_without_manual_invalidation = true;
    report.passed = true;
  } catch (error) {
    report.error = { name: error.name, message: error.message };
  } finally {
    for (const [label, close] of [
      ["browser", () => browser?.close()],
      ["dev_server", () => server?.stop()],
      ["compiler", () => compiler && new Promise((resolve, reject) => compiler.close(error => error ? reject(error) : resolve()))],
    ]) {
      try { await bounded(Promise.resolve().then(close), `${label} cleanup`, 10000); }
      catch (error) { cleanupErrors.push(`${label}: ${error.message}`); }
    }
    net.Socket.prototype.connect = originalConnect;
    if (temporaryRoot) {
      try { await fs.rm(temporaryRoot, { recursive: true, force: true }); }
      catch (error) { cleanupErrors.push(`temporary files: ${error.message}`); }
    }
    let preserved = true;
    for (const [name, expected] of Object.entries(originalHashes)) {
      try { if (hash(await fs.readFile(path.join(projectRoot, name))) !== expected) preserved = false; }
      catch { preserved = false; }
    }
    report.product_configuration_variables_and_lock_preserved = preserved;
    report.blocked_network_attempts = blockedConnections;
    report.cleanup_errors = cleanupErrors;
    report.temporary_directory_removed = !temporaryRoot || await fs.stat(temporaryRoot).then(() => false, () => true);
    report.cleanup_verified = cleanupErrors.length === 0 && report.temporary_directory_removed;
    report.passed = report.passed && preserved && report.cleanup_verified;
    report.seconds = Number(((performance.now() - started) / 1000).toFixed(3));
    await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    console.log(JSON.stringify({ passed: report.passed, versions: report.versions, cleanup_verified: report.cleanup_verified, seconds: report.seconds, report: reportPath, error: report.error }));
    process.exitCode = report.passed ? 0 : 1;
  }
}

main().catch(error => { net.Socket.prototype.connect = originalConnect; console.error(error.message); process.exitCode = 1; });
