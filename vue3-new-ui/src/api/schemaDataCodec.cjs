/* Lossless static schema data; original model validation runs after decoding. */
var MAX_SCHEMA_BYTES = 262144;
// Fixed printable alphabet excludes quotes, backslash and HTML delimiters.
var STATIC_RADIX85 = '!#$%()*+,-./0123456789:;=?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_abcdefghijklmnopqrstuvwxyz{|';

function decodeStaticCodeBytes(encoded, maximumBytes) {
  if (typeof encoded !== 'string' || !encoded.length || !Number.isSafeInteger(maximumBytes) || maximumBytes < 1 || maximumBytes > MAX_SCHEMA_BYTES * 2) throw new Error('Invalid bounded static code bytes');
  if (encoded.charAt(0) === '~') {
    var padding = Number(encoded.charAt(2));
    if (encoded.slice(0, 2) !== '~1' || !/^[0-3]$/.test(encoded.charAt(2)) || encoded.length < 8 || (encoded.length - 3) % 5 || encoded.length > 3 + Math.ceil(maximumBytes / 4) * 5) throw new Error('Invalid static radix85 version or length');
    var length = (encoded.length - 3) / 5 * 4 - padding;
    if (length < 1 || length > maximumBytes) throw new Error('Static radix85 exceeds its complete byte bound');
    var bytes = new Uint8Array(length);
    for (var cursor = 3, offset = 0; cursor < encoded.length; cursor += 5, offset += 4) {
      var value = 0;
      for (var digit = 0; digit < 5; digit++) {
        var index = STATIC_RADIX85.indexOf(encoded.charAt(cursor + digit));
        if (index < 0) throw new Error('Invalid static radix85 digit');
        value = value * 85 + index;
      }
      if (value > 4294967295) throw new Error('Static radix85 word exceeds uint32');
      for (var position = 3; position >= 0; position--) {
        var byte = value % 256;
        if (offset + position < length) bytes[offset + position] = byte;
        else if (byte !== 0) throw new Error('Invalid canonical static radix85 padding');
        value = Math.floor(value / 256);
      }
    }
    var binary = '';
    for (var start = 0; start < length; start += 8192) binary += String.fromCharCode.apply(null, bytes.subarray(start, start + 8192));
    return binary;
  }
  if (encoded.length > Math.ceil(maximumBytes / 3) * 4 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new Error('Invalid complete static base64 data');
  var raw = atob(encoded);
  if (!raw.length || raw.length > maximumBytes || btoa(raw) !== encoded) throw new Error('Invalid static schema code bytes');
  return raw;
}

function decodeSchemaText(encoded, byteLength) {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 || byteLength > MAX_SCHEMA_BYTES) {
    throw new Error('Invalid complete static schema data');
  }
  var raw = decodeStaticCodeBytes(encoded, byteLength * 2);
  // The old codec forbids the zero-distance ff0000 prefix. It unambiguously
  // marks a bounded DEFLATE record; all original literal/reference records remain readable.
  if(raw.charCodeAt(0)===255&&raw.charCodeAt(1)===0&&raw.charCodeAt(2)===0){
    if(raw.length<5||raw.charCodeAt(3)!==1)throw new Error('Invalid static deflate record version');
    var compressed=Uint8Array.from(raw.slice(4),function(char){return char.charCodeAt(0);});
    var restored=require('./staticDeflate.cjs').inflateStatic(compressed,byteLength);
    return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(restored);
  }
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

module.exports = { MAX_SCHEMA_BYTES: MAX_SCHEMA_BYTES, decodeSchemaText: decodeSchemaText, decodeSchemaData: decodeSchemaData, decodeStaticCodeBytes: decodeStaticCodeBytes };
