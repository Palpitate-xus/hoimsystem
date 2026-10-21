const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const test = require('node:test');
const { createSSRApp, h } = require('vue');
const { renderToString } = require('@vue/server-renderer');
const icons = require('@element-plus/icons-vue');
const manifest = require('../src/api/iconGallery.json');
const sprite = fs.readFileSync(path.join(__dirname, '../src/assets/element-plus-icon-gallery.svg'), 'utf8');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
test('all installed icon names and each original SVG geometry survive the static gallery', async () => {
  assert.deepEqual(manifest.names, Object.keys(icons).sort());
  assert.equal(new Set(manifest.names).size, 293);
  const symbols = new Map(Array.from(sprite.matchAll(/<symbol id="icon-([A-Za-z0-9]+)"([^>]*)>([\s\S]*?)<\/symbol>/g), match => [match[1], [match[2], match[3]]]));
  assert.equal(symbols.size, manifest.names.length);
  for (const name of manifest.names) {
    const [attributes, children] = symbols.get(name);
    const original = await renderToString(createSSRApp({ render: () => h(icons[name]) }));
    assert.equal(`<svg xmlns="http://www.w3.org/2000/svg"${attributes}>${children}</svg>`, original, name);
  }
});
test('gallery retains the exact locked dependency identity, complete asset digest and MIT text', () => {
  const packageFile = require.resolve('@element-plus/icons-vue/package.json');
  const dependency = JSON.parse(fs.readFileSync(packageFile, 'utf8'));
  const license = fs.readFileSync(path.join(path.dirname(packageFile), 'LICENSE'), 'utf8');
  assert.equal(manifest.package, dependency.name);
  assert.equal(manifest.version, dependency.version);
  assert.equal(manifest.source_sha256, hash(fs.readFileSync(require.resolve('@element-plus/icons-vue'))));
  assert.equal(manifest.license_sha256, hash(license));
  assert.equal(manifest.sprite_sha256, hash(sprite));
  assert.ok(sprite.includes(license));
});
