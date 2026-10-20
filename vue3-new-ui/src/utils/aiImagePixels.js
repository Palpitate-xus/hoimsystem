// DICOM PS3.3 C.11.2.1.2 / C.11.2.1.3:
// https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.11.2.html
// The backend has already unpacked/sign-extended stored samples into i32le.
// Padding is masked in stored-value space, before rescale, VOI and inversion.
export const MAX_IMAGE_PIXELS = 16 * 1024 * 1024;
export const VOI_FUNCTIONS = ["LINEAR", "LINEAR_EXACT", "SIGMOID"];

const finite = value => typeof value === "number" && Number.isFinite(value);
const integer = value => Number.isSafeInteger(value);

export function validateImageMetadata(metadata) {
  const m = metadata;
  if (!m || m.format !== "dicom_i32le_v1" || m.frames !== 1 || !integer(m.rows) || !integer(m.columns) || m.rows < 1 || m.columns < 1 || m.rows > 16384 || m.columns > 16384 || m.rows * m.columns > MAX_IMAGE_PIXELS) throw new Error("影像须为受支持的单帧原始灰阶像素，尺寸超出范围或缺少明确参数");
  if (![8, 16].includes(m.bits_allocated) || !integer(m.bits_stored) || m.bits_stored < 1 || m.bits_stored > m.bits_allocated || m.high_bit !== m.bits_stored - 1 || ![0, 1].includes(m.pixel_representation)) throw new Error("原始像素位宽与符号说明不完整");
  if (!["MONOCHROME1", "MONOCHROME2"].includes(m.photometric_interpretation) || typeof m.invert_display !== "boolean" || !finite(m.rescale_slope) || m.rescale_slope === 0 || !finite(m.rescale_intercept) || !VOI_FUNCTIONS.includes(m.voi_lut_function)) throw new Error("原始灰阶、重标定或窗函数说明无效");
  const lower = m.pixel_representation ? -(2 ** (m.bits_stored - 1)) : 0;
  const upper = m.pixel_representation ? 2 ** (m.bits_stored - 1) - 1 : 2 ** m.bits_stored - 1;
  if (m.padding != null && (!integer(m.padding.value) || m.padding.value < lower || m.padding.value > upper || (m.padding.range_limit != null && (!integer(m.padding.range_limit) || m.padding.range_limit < lower || m.padding.range_limit > upper)))) throw new Error("原始填充值范围无效");
  if (!Array.isArray(m.window_presets) || m.window_presets.length > 16) throw new Error("原始窗预设结构无效");
  for (const preset of m.window_presets) validateWindow({ ...preset, function: m.voi_lut_function });
  return m;
}

export function isPadding(stored, padding) {
  if (padding == null) return false;
  const end = padding.range_limit ?? padding.value;
  return stored >= Math.min(padding.value, end) && stored <= Math.max(padding.value, end);
}

export function decodeImagePixels(buffer, metadata) {
  const m = validateImageMetadata(metadata), count = m.rows * m.columns;
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== count * 4) throw new Error("实际像素字节数与原始行列不符");
  const view = new DataView(buffer), pixels = new Int32Array(count);
  const lower = m.pixel_representation ? -(2 ** (m.bits_stored - 1)) : 0;
  const upper = m.pixel_representation ? 2 ** (m.bits_stored - 1) - 1 : 2 ** m.bits_stored - 1;
  let minimum = null, maximum = null, valid = 0;
  for (let i = 0; i < count; i++) {
    const value = view.getInt32(i * 4, true);
    if (value < lower || value > upper) throw new Error("实际像素超出已声明的原始位宽");
    pixels[i] = value;
    if (isPadding(value, m.padding)) continue;
    minimum = minimum == null ? value : Math.min(minimum, value);
    maximum = maximum == null ? value : Math.max(maximum, value);
    valid++;
  }
  if (!integer(m.valid_pixel_count) || m.valid_pixel_count !== valid || m.valid_min_stored !== minimum || m.valid_max_stored !== maximum) throw new Error("实际有效像素与所选来源的范围或填充说明不一致");
  return pixels;
}

export function validateWindow(window) {
  if (!window || !finite(window.center) || !finite(window.width) || !VOI_FUNCTIONS.includes(window.function) || (window.function === "LINEAR" ? window.width < 1 : window.width <= 0)) throw new Error("LINEAR窗宽须至少1；LINEAR_EXACT/SIGMOID窗宽须大于0，窗位与窗宽须有限");
  return window;
}

export function dicomWindowValue(value, window) {
  validateWindow(window);
  return windowValue(value, window);
}

function windowValue(value, window) {
  const { center: center, width: width, function: fn } = window;
  if (!finite(value)) throw new Error("重标定后的像素不是有限数值");
  if (fn === "SIGMOID") {
    const z = 4 * ((value - center) / width);
    // Stable on both tails, including otherwise overflowing exponentials.
    if (z >= 0) return 1 / (1 + Math.exp(-z));
    const e = Math.exp(z);
    return e / (1 + e);
  }
  const midpoint = fn === "LINEAR" ? center - 0.5 : center;
  const span = fn === "LINEAR" ? width - 1 : width;
  if (value <= midpoint - span / 2) return 0;
  if (value > midpoint + span / 2) return 1;
  return (value - midpoint) / span + 0.5;
}

export function automaticImageWindow(pixels, metadata) {
  const m = validateImageMetadata(metadata);
  let minimum = Infinity, maximum = -Infinity;
  for (const value of pixels) {
    if (isPadding(value, m.padding)) continue;
    const scaled = value * m.rescale_slope + m.rescale_intercept;
    if (!finite(scaled)) throw new Error("重标定数值超出可显示范围");
    minimum = Math.min(minimum, scaled); maximum = Math.max(maximum, scaled);
  }
  if (minimum === Infinity) return null;
  const center = minimum / 2 + maximum / 2, width = maximum - minimum || 1;
  return validateWindow({ center, width, function: "LINEAR_EXACT", source: "auto_minmax_display_only" });
}

export function renderImagePixels(pixels, metadata, window) {
  const m = validateImageMetadata(metadata);
  validateWindow(window);
  if (!(pixels instanceof Int32Array) || pixels.length !== m.rows * m.columns) throw new Error("像素数组与原始尺寸不匹配");
  const rgba = new Uint8ClampedArray(pixels.length * 4);
  for (let i = 0; i < pixels.length; i++) {
    let gray = 0;
    if (!isPadding(pixels[i], m.padding)) {
      const scaled = pixels[i] * m.rescale_slope + m.rescale_intercept;
      const value = windowValue(scaled, window);
      // invert_display already resolves MONOCHROME1/PresentationLUTShape.
      // Never invert a second time based on Photometric Interpretation.
      gray = Math.round((m.invert_display ? 1 - value : value) * 255);
    }
    const offset = i * 4;
    rgba[offset] = rgba[offset + 1] = rgba[offset + 2] = gray;
    rgba[offset + 3] = 255;
  }
  return rgba;
}

export async function verifyImagePixelHash(buffer, expected, cryptoProvider = globalThis.crypto) {
  if (!/^[a-f0-9]{64}$/.test(expected || "") || !cryptoProvider?.subtle) throw new Error("缺少可核对的像素摘要，或浏览器不支持安全摘要核对");
  const digest = await cryptoProvider.subtle.digest("SHA-256", buffer);
  const actual = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, "0")).join("");
  if (actual !== expected) throw new Error("读取像素与所选冻结来源摘要不符，已停止显示");
  return actual;
}
