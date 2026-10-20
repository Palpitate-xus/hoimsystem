const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {test} = require('node:test');

// Execute the real build entry with a synthetic compiler, without compiling,
// installing packages, accessing hospital configuration, or writing dist.
for (const mode of ['stats_error', 'callback_error', 'success']) {
  test(`build process reports ${mode} through its exit status`, () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'hoim-build-exit-'));
    try {
      const preload = path.join(directory, 'compiler.cjs');
      fs.writeFileSync(preload, `
const Module = require('node:module'), original = Module._load;
Module._load = function(name, parent, isMain) {
  if (name === '@rspack/core') return {rspack: () => ({run(callback) {
    if (${JSON.stringify(mode)} === 'callback_error') return callback(new Error('synthetic compile callback error'));
    callback(null, {toJson: () => ({errors: ['synthetic compile stats error']}), hasErrors: () => ${JSON.stringify(mode)} === 'stats_error', hasWarnings: () => false, toString: () => 'synthetic compile finished'});
  }})};
  if (name === './layouts') return {donationConsole() {}};
  if (name.endsWith('/rspack.config.js')) return {optimization: {}};
  return original.apply(this, arguments);
};
`);
      const result = spawnSync(process.execPath, ['--require', preload, path.resolve(__dirname, '../rspack.js'), 'build'], {encoding: 'utf8', env: {}, timeout: 10000});
      assert.ifError(result.error);
      assert.equal(result.status, mode === 'success' ? 0 : 1, result.stdout + result.stderr);
      assert.equal(result.signal, null);
      assert.match(result.stdout + result.stderr, mode === 'callback_error' ? /synthetic compile callback error/ : /synthetic compile finished/);
    } finally {
      fs.rmSync(directory, {recursive: true, force: true});
    }
  });
}
