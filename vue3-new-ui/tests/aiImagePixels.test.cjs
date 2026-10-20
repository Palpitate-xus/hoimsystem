const test = require("node:test");
const assert = require("node:assert/strict");
const { readFile } = require("node:fs/promises");
const { createHash, webcrypto } = require("node:crypto");
const { join } = require("node:path");

// Import the repository's browser-native ES module without changing package
// mode or introducing a separate test runner into the application.
const modulePromise = readFile(join(__dirname, "../src/utils/aiImagePixels.js"), "utf8").then(source => import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`));
function metadata(extra = {}) {
  return { format: "dicom_i32le_v1", rows: 1, columns: 3, frames: 1, bits_allocated: 16, bits_stored: 12, high_bit: 11, pixel_representation: 1, photometric_interpretation: "MONOCHROME2", invert_display: false, rescale_slope: 1, rescale_intercept: 0, window_presets: [], voi_lut_function: "LINEAR", padding: null, valid_min_stored: -2, valid_max_stored: 2, valid_pixel_count: 3, ...extra };
}
function bytes(values) { const buffer = new ArrayBuffer(values.length * 4), view = new DataView(buffer); values.forEach((value, index) => view.setInt32(index * 4, value, true)); return buffer; }
const gray = data => Array.from(data).filter((_, i) => i % 4 === 0);
const close = (actual, expected, tolerance = 1e-12) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);

test("DICOM LINEAR published endpoints and half-value offset, including threshold width one", async () => {
  const { dicomWindowValue } = await modulePromise;
  const window = { center: 0, width: 100, function: "LINEAR" };
  assert.equal(dicomWindowValue(-50, window), 0); assert.equal(dicomWindowValue(49, window), 1);
  close(dicomWindowValue(-0.5, window), 0.5); close(dicomWindowValue(0, window), 50 / 99);
  const threshold = { center: 0, width: 1, function: "LINEAR" };
  assert.equal(dicomWindowValue(-0.5, threshold), 0); assert.equal(dicomWindowValue(-0.499, threshold), 1);
  const identity = { center: 2048, width: 4096, function: "LINEAR" };
  for (const input of [0, 1, 2047, 4095]) close(dicomWindowValue(input, identity), input / 4095);
});

test("LINEAR_EXACT supports fractional positive widths and differs from LINEAR midpoint", async () => {
  const { dicomWindowValue } = await modulePromise;
  const window = { center: 10, width: 0.5, function: "LINEAR_EXACT" };
  assert.equal(dicomWindowValue(9.75, window), 0); assert.equal(dicomWindowValue(10.25, window), 1); assert.equal(dicomWindowValue(10, window), 0.5);
  close(dicomWindowValue(10.125, window), 0.75);
});

test("SIGMOID follows the four-over-width coefficient and stays finite on both tails", async () => {
  const { dicomWindowValue } = await modulePromise;
  const window = { center: 7, width: 2, function: "SIGMOID" };
  close(dicomWindowValue(7, window), 0.5); close(dicomWindowValue(8, window), 1 / (1 + Math.exp(-2)));
  close(dicomWindowValue(6, window), 1 / (1 + Math.exp(2)));
  assert.equal(dicomWindowValue(1e300, window), 1); assert.equal(dicomWindowValue(-1e300, window), 0);
});

test("rescale precedes windowing, the resolved inversion applies once, and padding remains black", async () => {
  const { renderImagePixels } = await modulePromise;
  const pixels = new Int32Array([-2, 0, 2]);
  const m = metadata({ rescale_slope: -2, rescale_intercept: 10, padding: { value: -2, range_limit: -1 }, photometric_interpretation: "MONOCHROME1", invert_display: true });
  const rgba = renderImagePixels(pixels, m, { center: 10, width: 8, function: "LINEAR_EXACT" });
  assert.deepEqual(gray(rgba), [0, 128, 255]);
  assert.deepEqual(Array.from(rgba).filter((_, i) => i % 4 === 3), [255, 255, 255]);
  // A resolved flag, rather than a second photometric branch, owns inversion.
  assert.deepEqual(gray(renderImagePixels(pixels, { ...m, photometric_interpretation: "MONOCHROME2" }, { center: 10, width: 8, function: "LINEAR_EXACT" })), [0, 128, 255]);
});

test("padding mask is inclusive and stays in stored space with reversed limits and negative slope", async () => {
  const { isPadding, automaticImageWindow } = await modulePromise;
  const m = metadata({ padding: { value: 2, range_limit: -2 }, rescale_slope: -3, rescale_intercept: 11 });
  for (const value of [-2, -1, 0, 1, 2]) assert.equal(isPadding(value, m.padding), true);
  assert.equal(isPadding(3, m.padding), false);
  assert.equal(automaticImageWindow(new Int32Array([-2, 0, 2]), m), null);
});

test("automatic minmax excludes padding and explicitly uses a display-only exact window", async () => {
  const { automaticImageWindow, renderImagePixels } = await modulePromise;
  const m = metadata({ rescale_slope: -2, rescale_intercept: 10, padding: { value: -2, range_limit: -2 } });
  const window = automaticImageWindow(new Int32Array([-2, 0, 2]), m);
  assert.deepEqual(window, { center: 8, width: 4, function: "LINEAR_EXACT", source: "auto_minmax_display_only" });
  assert.deepEqual(gray(renderImagePixels(new Int32Array([-2, 0, 2]), m, window)), [0, 255, 0]);
  const constant = automaticImageWindow(new Int32Array([4, 4, 4]), metadata());
  assert.equal(constant.width, 1); assert.equal(constant.center, 4);
});

test("i32le pixels decode without host endian assumptions and validate signed source bounds", async () => {
  const { decodeImagePixels } = await modulePromise;
  const decoded = decodeImagePixels(bytes([-2, 0, 2]), metadata());
  assert.ok(decoded instanceof Int32Array); assert.deepEqual([...decoded], [-2, 0, 2]);
  const unsigned = metadata({ bits_allocated: 8, bits_stored: 8, high_bit: 7, pixel_representation: 0, valid_min_stored: 0, valid_max_stored: 255 });
  assert.deepEqual([...decodeImagePixels(bytes([0, 128, 255]), unsigned)], [0, 128, 255]);
  assert.throws(() => decodeImagePixels(bytes([-1, 0, 255]), unsigned), /位宽/);
  assert.throws(() => decodeImagePixels(bytes([-2049, 0, 2]), metadata()), /位宽/);
  assert.throws(() => decodeImagePixels(bytes([-2, 0]), metadata()), /字节数/);
});

test("pixel statistics and all-padding records remain source-bound", async () => {
  const { decodeImagePixels } = await modulePromise;
  assert.throws(() => decodeImagePixels(bytes([-2, 0, 2]), metadata({ valid_max_stored: 3 })), /范围或填充/);
  assert.throws(() => decodeImagePixels(bytes([-2, 0, 2]), metadata({ valid_pixel_count: 2 })), /范围或填充/);
  const m = metadata({ padding: { value: 0 }, valid_pixel_count: 0, valid_min_stored: null, valid_max_stored: null });
  assert.deepEqual([...decodeImagePixels(bytes([0, 0, 0]), m)], [0, 0, 0]);
});

test("invalid dimensions, multiple frames, missing calibration and unsupported windows fail explicitly", async () => {
  const { validateImageMetadata, dicomWindowValue } = await modulePromise;
  for (const change of [{ rows: 0 }, { rows: 16385 }, { rows: 8192, columns: 8192 }, { frames: 2 }, { bits_stored: 13, high_bit: 12, bits_allocated: 8 }, { high_bit: 12 }, { photometric_interpretation: "RGB" }, { invert_display: undefined }, { rescale_slope: 0 }, { rescale_intercept: Infinity }, { voi_lut_function: "UNSUPPORTED" }]) assert.throws(() => validateImageMetadata(metadata(change)));
  for (const window of [{ center: 0, width: 0.99, function: "LINEAR" }, { center: 0, width: 0, function: "SIGMOID" }, { center: NaN, width: 1, function: "LINEAR_EXACT" }]) assert.throws(() => dicomWindowValue(0, window));
});

test("private pixel digest binds actual binary bytes to the frozen source", async () => {
  const { verifyImagePixelHash } = await modulePromise, buffer = bytes([-2, 0, 2]);
  const hash = createHash("sha256").update(Buffer.from(buffer)).digest("hex");
  assert.equal(await verifyImagePixelHash(buffer, hash, webcrypto), hash);
  await assert.rejects(verifyImagePixelHash(buffer, "0".repeat(64), webcrypto), /摘要不符/);
  await assert.rejects(verifyImagePixelHash(buffer, hash, {}), /安全摘要/);
});

test("actual grayscale mapping agrees with the independent pinned pydicom window oracle", async () => {
  const { dicomWindowValue, renderImagePixels } = await modulePromise;
  const oracle = JSON.parse(await readFile(join(__dirname, '../e2e/fixtures/dicom-window-oracle.json'), 'utf8'));
  assert.equal(oracle.synthetic_only, true);
  assert.ok(oracle.oracle.includes('pydicom3.0.2'));
  assert.equal(oracle.cases.length, 8);
  for (const fixture of oracle.cases) {
    const window = { center: fixture.center, width: fixture.width, function: fixture.function };
    assert.equal(fixture.stored.length, fixture.expected_normalized.length);
    const m = metadata({ columns: fixture.stored.length, rescale_slope: fixture.rescale_slope, rescale_intercept: fixture.rescale_intercept, voi_lut_function: fixture.function, invert_display: fixture.invert_display, photometric_interpretation: fixture.invert_display ? 'MONOCHROME1' : 'MONOCHROME2' });
    fixture.stored.forEach((value, index) => {
      const mapped = dicomWindowValue(value * fixture.rescale_slope + fixture.rescale_intercept, window);
      close(fixture.invert_display ? 1 - mapped : mapped, fixture.expected_normalized[index], 1e-12);
    });
    assert.deepEqual(gray(renderImagePixels(new Int32Array(fixture.stored), m, window)), fixture.expected_normalized.map(value => Math.round(value * 255)));
  }
});
