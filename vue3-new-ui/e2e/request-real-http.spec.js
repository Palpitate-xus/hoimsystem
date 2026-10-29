const { test, expect } = require("@playwright/test");
const { createHash } = require("node:crypto");
const { startRequestHarness } = require("../scripts/request-regression-harness.cjs");

// This suite owns its ephemeral HTTP server and browser bundle. No application
// backend, credentials, adapter mocks, production build or npm install is used.
test.describe.configure({ mode: "default" });
let harness;
const token = "synthetic-request-regression-token-no-real-credential";
const binary = [0, 255, 1, 128, 13, 10, 0, 42];
const sha256 = value => createHash("sha256").update(value).digest("hex");

test.beforeAll(async () => { harness = await startRequestHarness(); });
test.afterAll(async () => { await harness?.close(); });
test.beforeEach(async ({ page }) => {
  harness.clear();
  await page.context().route("**/*", route => {
    if (![harness.origin, harness.sinkOrigin].includes(new URL(route.request().url()).origin)) return route.abort("blockedbyclient");
    return route.continue();
  });
  await page.goto(harness.origin);
  await page.waitForFunction(() => !!window.__requestRegression);
  await page.evaluate(value => { window.__requestRegression.state.user.accessToken = value; }, token);
});

test("uses the installed locked Axios browser XHR with original request and API sources", async ({ page }) => {
  const actual = await page.evaluate(() => ({ version: window.__requestRegression.axiosVersion, adapter: window.__requestRegression.nativeAdapter, baseURL: window.__requestRegression.request.defaults.baseURL, tokenName: window.__requestRegression.config.tokenName }));
  expect(actual).toEqual({ version: harness.lockedAxios, adapter: "xhr", baseURL: "/api", tokenName: "accesstoken" });
  expect(harness.installedAxios).toBe(harness.lockedAxios);
});

test("authenticates real HTTP and preserves form zero/false/empty while dropping only top-level null/undefined", async ({ page }) => {
  const response = await page.evaluate(() => window.__requestRegression.request({ url: "/echo", method: "post", headers: { accesstoken: "synthetic-stale-caller-token" }, data: { zero: 0, off: false, empty: "", absent: null, omitted: undefined, nested: { missing: null, off: false } }, params: { zero: 0, off: false, empty: "" } }));
  expect(response.code).toBe(200);
  expect(response.data.token).toBe(token);
  expect(response.data.json).toEqual({ zero: 0, off: false, empty: "", nested: { missing: null, off: false } });
  expect(response.data.query).toEqual({ zero: "0", off: "false", empty: "" });
  expect(response.data.contentType).toContain("application/json");
  expect(harness.count("POST", "/api/echo")).toBe(1);
});

test("original explicit JSON nursing API preserves unknown nulls and exact aware timestamps", async ({ page }) => {
  const response = await page.evaluate(() => window.__requestRegression.nursing.createNursingAssessment({ patient_id: 1, admission_id: "synthetic-admission", pain_score: 0, falls_score: null, skin_problem: false, assessed_at: "2026-10-20T01:02:03.123456+08:00" }));
  expect(response.data.path).toBe("/api/nursingAssessment/create");
  expect(response.data.json).toEqual({ patient_id: 1, admission_id: "synthetic-admission", pain_score: 0, falls_score: null, skin_problem: false, assessed_at: "2026-10-20T01:02:03.123456+08:00" });
  expect(response.data.contentType).toBe("application/json");
});

test("original URL-encoded mode preserves zero/false and encodes the real HTTP body", async ({ page }) => {
  const response = await page.evaluate(() => window.__requestRegression.request({ url: "echo-form", method: "post", headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }, data: { zero: 0, off: false, empty: "", missing: null, text: "合成 & =" } }));
  expect(Object.fromEntries(new URLSearchParams(response.data.text))).toEqual({ zero: "0", off: "false", empty: "", text: "合成 & =" });
  expect(response.data.contentType).toContain("application/x-www-form-urlencoded");
});

for (const kind of ["audio", "ecg", "image"]) {
  test(`original ${kind} upload sends actual multipart bytes with browser boundary and synthetic fields`, async ({ page }) => {
    const files = kind === "audio"
      ? [{ field: "file", name: "synthetic.wav", type: "audio/wav", bytes: [...Buffer.from("RIFF"), 0, 255, 1, 128, ...Buffer.from("WAVE")] }]
      : kind === "ecg"
        ? [{ field: "header", name: "synthetic.hea", type: "text/plain", bytes: [...Buffer.from("synthetic 1 100 4\nsynthetic.dat 16 1000/mV 16 0 0 0 0 I\n")] }, { field: "signal", name: "synthetic.dat", type: "application/octet-stream", bytes: [0, 0, 255, 127, 0, 128, 42, 0] }]
        : [{ field: "image", name: "synthetic.dcm", type: "application/dicom", bytes: [...Buffer.alloc(128), ...Buffer.from("DICM"), 0, 255, 1, 128] }];
    const response = await page.evaluate(async ({ kind, files }) => {
      const form = new FormData();
      form.append("patient_id", "1"); form.append("authorization_confirmed", "true"); form.append("authorization_note", "synthetic fixture only; no actual patient");
      if (kind === "image") form.append("imaging_order_id", "synthetic-image-order");
      for (const file of files) form.append(file.field, new File([new Uint8Array(file.bytes)], file.name, { type: file.type }));
      const api = window.__requestRegression.ai;
      return (kind === "audio" ? api.uploadAIAudio : kind === "ecg" ? api.uploadAIEcg : api.uploadAIImage)(form);
    }, { kind, files });
    expect(response.data.contentType).toMatch(/^multipart\/form-data; boundary=/);
    expect(response.data.token).toBe(token);
    expect(response.data.parts.find(item => item.name === "patient_id").value).toBe("1");
    for (const file of files) {
      const part = response.data.parts.find(item => item.name === file.field);
      expect(part).toMatchObject({ filename: file.name, contentType: file.type, size: file.bytes.length, sha256: sha256(Buffer.from(file.bytes)), base64: Buffer.from(file.bytes).toString("base64") });
    }
    expect(harness.count("POST", `/api/ai/${kind === "audio" ? "audio" : kind === "ecg" ? "ecg" : "image"}-assets`)).toBe(1);
  });
}

test("legacy explicit multipart import uses the actual browser-generated boundary", async ({ page }) => {
  const response = await page.evaluate(() => window.__requestRegression.imports.importData("synthetic", new File([new Uint8Array([0, 255, 10, 42])], "synthetic.csv", { type: "text/csv" })));
  expect(response.data.contentType).toMatch(/^multipart\/form-data; boundary=/);
  expect(response.data.parts[0]).toMatchObject({ name: "file", filename: "synthetic.csv", base64: "AP8KKg==" });
});

test("original binary APIs return real Blob and ArrayBuffer without corrupting zero or non-UTF8 bytes", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { ai, imports } = window.__requestRegression;
    const blobs = await Promise.all([ai.getAIAudioContent("synthetic"), ai.getAIEcgContent("synthetic", "signal"), ai.getAIImageContent("synthetic"), imports.downloadData("synthetic")]);
    const pixels = await ai.getAIImagePixels("synthetic");
    return { blobs: await Promise.all(blobs.map(async blob => ({ type: blob instanceof Blob, bytes: Array.from(new Uint8Array(await blob.arrayBuffer())) }))), pixels: { type: pixels instanceof ArrayBuffer, bytes: Array.from(new Uint8Array(pixels)) } };
  });
  expect(result.blobs).toEqual(Array(4).fill({ type: true, bytes: binary }));
  expect(result.pixels).toEqual({ type: true, bytes: binary });
  expect(harness.requests.every(item => item.token === token)).toBe(true);
  expect(harness.requests.find(item => item.path.includes("/ecg-assets/")).query).toEqual({ part: "signal" });
});

test("binary mode respects actual HTTP errors and leaves successful response bytes opaque", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { request } = window.__requestRegression;
    const failures = [];
    for (const responseType of ["blob", "arraybuffer"]) {
      try { await request({ url: "/always-error-binary", params: { status: 422 }, responseType }); }
      catch (error) { failures.push({ status: error.response?.status, code: error.code, binary: responseType === "blob" ? error.response.data instanceof Blob : error.response.data instanceof ArrayBuffer }); }
    }
    const blob = await request({ url: "/binary-json", responseType: "blob" });
    return { failures, opaque: JSON.parse(await blob.text()) };
  });
  expect(result.failures).toEqual(Array(2).fill({ status: 422, code: "ERR_BAD_REQUEST", binary: true }));
  expect(result.opaque.code).toBe(422);
  expect(harness.count("GET", "/api/always-error-binary")).toBe(2);
});

test("GET retries transient HTTP and connection failure using actual repeated network requests", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { request } = window.__requestRegression;
    const transient = await request({ url: "/retry-get", params: { failures: 2 }, retryDelay: 1 });
    const network = await request({ url: "/network-retry", retryDelay: 1 });
    let exhausted;
    try { await request({ url: "/always-error-get", retryDelay: 1 }); }
    catch (error) { exhausted = { status: error.response?.status, retryCount: error.config.__retryCount }; }
    return { transient: transient.code, network: network.code, exhausted };
  });
  expect(result).toEqual({ transient: 200, network: 200, exhausted: { status: 503, retryCount: 3 } });
  expect(harness.count("GET", "/api/retry-get")).toBe(3);
  expect(harness.count("GET", "/api/network-retry")).toBe(2);
  expect(harness.count("GET", "/api/always-error-get")).toBe(4);
});

test("GET 404 and unkeyed POST failures never repeat writes", async ({ page }) => {
  const failures = await page.evaluate(async () => {
    const { request } = window.__requestRegression;
    const failures = [];
    for (const config of [{ method: "get", url: "/always-error-missing", params: { status: 404 } }, { method: "post", url: "/always-error-write", data: { zero: 0, off: false } }]) {
      try { await request(config); } catch (error) { failures.push(error.response?.status); }
    }
    return failures;
  });
  expect(failures).toEqual([404, 503]);
  expect(harness.count("GET", "/api/always-error-missing")).toBe(1);
  expect(harness.count("POST", "/api/always-error-write")).toBe(1);
});

test("real HTTP 401 resets only synthetic auth state and JSON business errors reject", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { request, effects, state } = window.__requestRegression;
    let authStatus, businessError;
    try { await request({ url: "/unauthorized" }); } catch (error) { authStatus = error.response?.status; }
    try { await request({ url: "/business-error", method: "post" }); } catch (error) { businessError = String(error); }
    return { authStatus, businessError, effects, token: state.user.accessToken };
  });
  expect(result.authStatus).toBe(401);
  expect(result.effects.dispatches).toEqual(["user/resetAccessToken"]);
  expect(result.effects.routes).toEqual([{ path: "/login" }]);
  expect(result.token).toBe("");
  expect(result.businessError).toContain("synthetic business rejection");
  expect(harness.requests[0].token).toBe(token);
  expect(harness.requests[1].token).toBeNull();
});

test("AbortController cancellation stays ERR_CANCELED and does not retry", async ({ page }) => {
  await page.evaluate(() => {
    const controller = new AbortController(); window.__controller = controller;
    window.__pendingAbort = window.__requestRegression.request({ url: "/slow-controller", signal: controller.signal, retryDelay: 1 }).then(() => ({ resolved: true }), error => ({ resolved: false, code: error.code }));
  });
  await expect.poll(() => harness.count("GET", "/api/slow-controller")).toBe(1);
  await page.evaluate(() => window.__controller.abort());
  expect(await page.evaluate(() => window.__pendingAbort)).toEqual({ resolved: false, code: "ERR_CANCELED" });
  await page.waitForTimeout(250);
  expect(harness.count("GET", "/api/slow-controller")).toBe(1);
});

test("AbortController cancellation during real retry backoff sends no second HTTP request", async ({ page }) => {
  await page.evaluate(() => {
    const controller = new AbortController(); window.__backoffController = controller;
    window.__backoffResult = window.__requestRegression.request({ url: "/retry-backoff", params: { failures: 2, retry_after: 0.25 }, signal: controller.signal, retryDelay: 1 }).then(() => ({ resolved: true }), error => ({ resolved: false, code: error.code }));
  });
  await expect.poll(() => harness.count("GET", "/api/retry-backoff")).toBe(1);
  await page.evaluate(() => window.__backoffController.abort());
  expect(await page.evaluate(() => window.__backoffResult)).toEqual({ resolved: false, code: "ERR_CANCELED" });
  expect(harness.count("GET", "/api/retry-backoff")).toBe(1);
});

test("native XMLHttpRequest abort preserves ECONNABORTED and never resends a cancelled GET", async ({ page }) => {
  await page.evaluate(() => {
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (...args) {
      window.__nativeXHR = this; XMLHttpRequest.prototype.send = send;
      return send.apply(this, args);
    };
    window.__nativeAbortResult = window.__requestRegression.request({ url: "/native-abort", retryDelay: 1 }).then(() => ({ resolved: true }), error => ({ resolved: false, code: error.code, message: error.message }));
  });
  await expect.poll(() => harness.count("GET", "/api/native-abort")).toBe(1);
  await page.evaluate(() => window.__nativeXHR.abort());
  expect(await page.evaluate(() => window.__nativeAbortResult)).toMatchObject({ resolved: false, code: "ECONNABORTED", message: "Request aborted" });
  expect(harness.count("GET", "/api/native-abort")).toBe(1);
});

test("actual XHR timeouts remain retryable for GET but never duplicate a POST", async ({ page }) => {
  const results = await page.evaluate(async () => {
    const results = [];
    for (const method of ["get", "post"]) {
      try { await window.__requestRegression.request({ url: `/slow-timeout-${method}`, method, data: method === "post" ? { zero: 0 } : undefined, timeout: 40, retry: 1, retryDelay: 1 }); }
      catch (error) { results.push({ method, code: error.code, message: error.message, retries: error.config.__retryCount || 0 }); }
    }
    return results;
  });
  expect(results).toHaveLength(2);
  expect(results[0]).toMatchObject({ method: "get", code: "ETIMEDOUT", retries: 1 });
  expect(results[1]).toMatchObject({ method: "post", code: "ETIMEDOUT", retries: 0 });
  expect(results.every(item => item.message.includes("timeout"))).toBe(true);
  expect(harness.count("GET", "/api/slow-timeout-get")).toBe(2);
  expect(harness.count("POST", "/api/slow-timeout-post")).toBe(1);
});

test("cross-origin URL forms are blocked before credentials, payload or any HTTP preflight leaves the page", async ({ page }) => {
  const results = await page.evaluate(async sinkOrigin => {
    const { request } = window.__requestRegression;
    const host = new URL(sinkOrigin).host, slash = String.fromCharCode(92);
    const attempts = [
      { url: sinkOrigin + "/api/echo" },
      { url: "//" + host + "/api/echo" },
      { baseURL: sinkOrigin, url: "/api/echo" },
      { baseURL: "", url: slash.repeat(2) + host + slash + "api" + slash + "echo" },
      { baseURL: "", url: "http:" + slash.repeat(2) + host + slash + "api" + slash + "echo" },
    ];
    const results = [];
    for (const options of attempts) {
      try { await request({ ...options, method: "post", data: { syntheticSecret: "must-never-leave-origin", zero: 0 }, retryDelay: 1 }); results.push({ resolved: true }); }
      catch (error) { results.push({ resolved: false, code: error.code, retainedConfig: !!error.config }); }
    }
    return results;
  }, harness.sinkOrigin);
  expect(results).toEqual(Array(5).fill({ resolved: false, code: "ERR_BLOCKED_ORIGIN", retainedConfig: false }));
  expect(harness.sinkRequests).toEqual([]);
});

test("same-origin absolute API URLs still carry current authentication", async ({ page }) => {
  const result = await page.evaluate(url => window.__requestRegression.request({ url }), harness.origin + "/api/echo");
  expect(result.code).toBe(200);
  expect(result.data.token).toBe(token);
  expect(harness.count("GET", "/api/echo")).toBe(1);
  expect(harness.sinkRequests).toEqual([]);
});

test("a changed document base cannot redirect relative authenticated API traffic", async ({ page }) => {
  const result = await page.evaluate(async sinkOrigin => {
    const base = document.createElement("base"); base.href = sinkOrigin + "/"; document.head.prepend(base);
    try {
      await window.__requestRegression.request({ url: "echo-base-tag", retryDelay: 1 });
      return { resolved: true };
    } catch (error) { return { resolved: false, code: error.code }; }
    finally { base.remove(); }
  }, harness.sinkOrigin);
  expect(result).toEqual({ resolved: false, code: "ERR_BLOCKED_ORIGIN" });
  expect(harness.sinkRequests).toEqual([]);
});

test("non-HTTP targets and URL userinfo are rejected before creating a native request", async ({ page }) => {
  const results = await page.evaluate(async origin => {
    const results = [];
    for (const url of ["data:application/json,%7B%22code%22%3A200%7D", origin.replace("http://", "http://synthetic:password@") + "/api/echo"]) {
      try { await window.__requestRegression.request({ url, baseURL: "", retryDelay: 1 }); results.push({ resolved: true }); }
      catch (error) { results.push({ resolved: false, code: error.code }); }
    }
    return results;
  }, harness.origin);
  expect(results).toEqual(Array(2).fill({ resolved: false, code: "ERR_BLOCKED_ORIGIN" }));
  expect(harness.requests).toEqual([]);
  expect(harness.sinkRequests).toEqual([]);
});

test('real HTTP 403 preserves authentication and rejects once without retrying or replaying the denied write', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { request, effects, state } = window.__requestRegression;
    const statuses = [];
    for (const method of ['get', 'post']) {
      try { await request({ url: '/always-error-forbidden', method, params: { status: 403 }, data: { patient_id: 1 } }); }
      catch (error) { statuses.push(error.response?.status); }
    }
    const echo = await request({ url: '/echo' });
    return { statuses, dispatches: effects.dispatches, routes: effects.routes, token: state.user.accessToken, nextToken: echo.data.token };
  });
  expect(result).toEqual({ statuses: [403, 403], dispatches: [], routes: [], token, nextToken: token });
  expect(harness.count('GET', '/api/always-error-forbidden')).toBe(1);
  expect(harness.count('POST', '/api/always-error-forbidden')).toBe(1);
});
