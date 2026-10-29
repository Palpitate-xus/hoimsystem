const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

test('the archive command packages complete nested Unicode files and excludes its own output', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hoim-archive-compatibility-'));
  try {
    await fs.mkdir(path.join(directory, 'dist', 'nested'), { recursive: true });
    await fs.writeFile(path.join(directory, 'dist', 'index.html'), '<!doctype html>医院😀\r\n');
    await fs.writeFile(path.join(directory, 'dist', 'nested', '说明.txt'), '\ufeff完整资源\r\n');
    await fs.writeFile(path.join(directory, 'dist', 'dist.zip'), 'previous output');
    execFileSync(process.execPath, [path.resolve(__dirname, '../build-zip.cjs')], { cwd: directory, timeout: 15000 });
    const actual = JSON.parse(execFileSync('python3', ['-c', 'import json,sys,zipfile;z=zipfile.ZipFile(sys.argv[1]);print(json.dumps({n:z.read(n).decode("utf-8") for n in z.namelist() if not n.endswith("/")},ensure_ascii=False))', path.join(directory, 'dist', 'dist.zip')], { encoding: 'utf8' }));
    assert.deepEqual(actual, { 'index.html': '<!doctype html>医院😀\r\n', 'nested/说明.txt': '\ufeff完整资源\r\n' });
  } finally { await fs.rm(directory, { recursive: true, force: true }); }
});

test('schema-utils resolves URI references and still rejects invalid nested configuration', () => {
  const { validate } = require('schema-utils');
  const schema = { type: 'object', required: ['item'], properties: { item: { $ref: '#/definitions/item' } }, definitions: { item: { type: 'object', required: ['limit'], properties: { limit: { type: 'integer', minimum: 1 } } } } };
  assert.doesNotThrow(() => validate(schema, { item: { limit: 2 } }, { name: 'DependencyCompatibility' }));
  assert.throws(() => validate(schema, { item: { limit: 0 } }, { name: 'DependencyCompatibility' }), /limit/);
  assert.throws(() => validate(schema, { item: {} }, { name: 'DependencyCompatibility' }), /limit/);
});

test('the installed watcher reports file creation, content changes and removal, then closes', { timeout: 15000 }, async () => {
  const { watch } = require('chokidar');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hoim-watcher-compatibility-'));
  const watcher = watch(directory, { ignoreInitial: true });
  const next = event => new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { watcher.off(event, receive); reject(new Error('Missing watcher event: ' + event)); }, 4000);
    function receive(file) { clearTimeout(timeout); resolve(file); }
    watcher.once(event, receive);
  });
  try {
    await next('ready');
    const file = path.join(directory, '样式.scss');
    const added = next('add'); await fs.writeFile(file, '$color: red;'); assert.equal(await added, file);
    const changed = next('change'); await fs.writeFile(file, '$color: blue;'); assert.equal(await changed, file);
    const removed = next('unlink'); await fs.unlink(file); assert.equal(await removed, file);
  } finally { await watcher.close(); await fs.rm(directory, { recursive: true, force: true }); }
});
