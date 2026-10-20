const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
const babel = require("@babel/core");
const { parse } = require("@vue/compiler-sfc");

// Execute the actual SFC's quantity parser after the existing production Babel
// loader options. No dist build, service, patient data or package mutation.
const root = path.resolve(__dirname, "../..");
const filename = path.join(root, "src/components/AIAkiFindings/index.vue");
const source = fs.readFileSync(filename, "utf8");
const script = parse(source, { filename }).descriptor.scriptSetup.content;
const ast = babel.parseSync(script, { configFile: false, babelrc: false, sourceType: "module" });
const declaration = ast.program.body.flatMap(node => node.type === "VariableDeclaration" ? node.declarations : []).find(node => node.id.name === "decimalScale");
assert.ok(declaration, "actual SFC decimal parser must exist");
const originalArgument = process.argv[2]; process.argv[2] = "build";
let config;
try { config = require(path.join(root, "rspack.config.js")); }
finally { if (originalArgument === undefined) delete process.argv[2]; else process.argv[2] = originalArgument; }
assert.equal(config.mode, "production");
const rule = config.module.rules.find(value => value.use?.loader === "babel-loader");
assert.ok(rule?.use.options, "read actual production babel-loader options");
const options = { ...rule.use.options, cwd: root, filename: `${filename}.js`, sourceType: "script" };
const input = `const ${script.slice(declaration.start, declaration.end)}; module.exports = decimalScale;`;
const compiled = babel.transformSync(input, options).code;
assert.equal(/\bMath\.pow\s*\(/.test(compiled), false, "fixed parser must not call floating-point exponentiation");
const context = { module: { exports: null } }; vm.runInNewContext(compiled, context);
const actual = context.module.exports;
const cases = [
  ["0", 0n], ["0.00000000", 0n], ["1.23000000", 123000000n],
  ["9999999999999999.12345678", 999999999999999912345678n],
  [null, null], ["-1", null], ["1.000000001", null], ["1e2", null], ["01", null], [1.2, null],
];
for (const [value, expected] of cases) assert.equal(actual(value), expected);
// A genuine decline is a valid signed *difference*, not a negative raw amount.
assert.equal(actual("-0.30000000", true), -30000000n);
assert.equal(actual("-0.300000001", true), null);
const oldCompiled = babel.transformSync("module.exports = 10n ** 2n;", options).code;
let oldBehavior;
try { const original = { module: { exports: null } }; vm.runInNewContext(oldCompiled, original); assert.equal(original.module.exports, 100n); oldBehavior = "native_supported"; }
catch (error) { assert.equal(error.name, "TypeError"); assert.ok(oldCompiled.includes("Math.pow")); oldBehavior = "actual_preset_lowers_bigint_to_invalid_math_pow"; }
const sha = value => crypto.createHash("sha256").update(value).digest("hex");
const report = { scope: "Actual SFC decimal expression through unchanged production Babel loader options; no full app or clinical calculation", cases_passed: cases.length + 2, babel_version: babel.version, source_sha256: sha(source), parser_sha256: sha(input), compiled_sha256: sha(compiled), fixed_math_pow: false, original_exponentiation_behavior: oldBehavior };
fs.writeFileSync("/tmp/hoim-aki-decimal-compiled.json", JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report));
