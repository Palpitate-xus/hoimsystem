/* Preserve every installed Element Plus icon as a static SVG symbol. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createSSRApp, h } = require('vue');
const { renderToString } = require('@vue/server-renderer');
const icons = require('@element-plus/icons-vue');
const root = path.resolve(__dirname, '..');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
async function artifacts() {
  const packageFile = require.resolve('@element-plus/icons-vue/package.json');
  const dependency = JSON.parse(fs.readFileSync(packageFile, 'utf8'));
  const license = fs.readFileSync(path.join(path.dirname(packageFile), 'LICENSE'), 'utf8');
  if (license.includes('--')) throw new Error('License requires explicit XML comment encoding');
  const names = Object.keys(icons).sort();
  const symbols = [];
  for (const name of names) {
    if (!/^[A-Za-z][A-Za-z0-9]*$/.test(name)) throw new Error('Unexpected installed icon identity');
    const original = await renderToString(createSSRApp({ render: () => h(icons[name]) }));
    const match = /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"( (?:xml:space="preserve" )?viewBox="0 0 1024 1024")>([\s\S]*)<\/svg>$/.exec(original);
    if (!match) throw new Error('Unexpected installed SVG root: ' + name);
    symbols.push(`<symbol id="icon-${name}"${match[1]}>${match[2]}</symbol>`);
  }
  const sprite = `<svg xmlns="http://www.w3.org/2000/svg">\n<!-- Derived from ${dependency.name} ${dependency.version}.\n${license}\n-->\n${symbols.join('\n')}\n</svg>\n`;
  const manifest = { schema_version: 'element_plus_icon_gallery_v1', package: dependency.name, version: dependency.version, source_sha256: hash(fs.readFileSync(require.resolve('@element-plus/icons-vue'))), license_sha256: hash(license), sprite_sha256: hash(sprite), names };
  return { 'src/assets/element-plus-icon-gallery.svg': sprite, 'src/api/iconGallery.json': JSON.stringify(manifest, null, 2) + '\n' };
}
module.exports = { artifacts };
if (require.main === module) artifacts().then(values => {
  for (const [name, value] of Object.entries(values)) {
    const file = path.join(root, name);
    if (process.argv.includes('--check')) {
      if (!fs.existsSync(file) || fs.readFileSync(file, 'utf8') !== value) throw new Error('Regenerate complete icon gallery: ' + name);
    } else fs.writeFileSync(file, value);
  }
  console.log('Preserved all ' + Object.keys(icons).length + ' installed icons, original geometry and MIT license');
}).catch(error => { console.error(error); process.exitCode = 1; });
