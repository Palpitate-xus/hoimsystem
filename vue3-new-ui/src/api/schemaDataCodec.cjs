/* Lossless static schema data; original model validation runs after decoding. */
var MAX_SCHEMA_BYTES = 262144;

function decodeSchemaText(encoded, byteLength) {
  if (typeof encoded !== 'string' || !Number.isSafeInteger(byteLength) || byteLength < 1 || byteLength > MAX_SCHEMA_BYTES || encoded.length > Math.ceil(byteLength * 2 / 3) * 4 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw new Error('Invalid complete static schema data');
  }
  var raw = atob(encoded);
  if (!raw.length || btoa(raw) !== encoded) throw new Error('Invalid static schema code bytes');
  var output = new Uint8Array(byteLength);
  var position = 0;
  for (var cursor = 0; cursor < raw.length;) {
    var control = raw.charCodeAt(cursor++);
    var length = control < 128 ? control + 1 : control - 128 + 4;
    if (length > byteLength - position) throw new Error('Static schema exceeds its complete byte length');
    if (control < 128) {
      if (length > raw.length - cursor) throw new Error('Incomplete static schema literal');
      for (var offset = 0; offset < length; offset++) output[position++] = raw.charCodeAt(cursor++);
    } else {
      if (raw.length - cursor < 2) throw new Error('Incomplete static schema reference');
      var distance = raw.charCodeAt(cursor++) | raw.charCodeAt(cursor++) << 8;
      if (!distance || distance > position) throw new Error('Invalid static schema backward reference');
      for (var count = 0; count < length; count++) {
        output[position] = output[position - distance];
        position++;
      }
    }
  }
  if (position !== byteLength) throw new Error('Incomplete static schema data');
  return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(output);
}

function decodeSchemaData(encoded, byteLength) {
  return JSON.parse(decodeSchemaText(encoded, byteLength));
}

module.exports = { MAX_SCHEMA_BYTES: MAX_SCHEMA_BYTES, decodeSchemaText: decodeSchemaText, decodeSchemaData: decodeSchemaData };
