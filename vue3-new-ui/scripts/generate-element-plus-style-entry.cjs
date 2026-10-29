/* Static usage audit. No application module is evaluated and no CSS rule is edited. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const babel = require('@babel/parser');
const sfc = require('@vue/compiler-sfc');
const dom = require('@vue/compiler-dom');
// Same installed resolver uses the package's ESM import conditions; require.resolve
// incorrectly rejects Element Plus's import-only es/* exports. No module executes.
const resolveImport = require('enhanced-resolve').create.sync({ conditionNames: ['import', 'module', 'default'], extensions: ['.mjs', '.js', '.json', '.css'] });
const ROOT = path.resolve(__dirname, '..');
const OUTPUT = 'src/elementPlusUsedStyles.js';
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
// Current dynamic application selectors were read individually. Their complete
// script bytes and expression are pinned; a changed/new selector needs review.
// These return app menu components or SVG icons, never arbitrary Element Plus widgets.
const AUDITED_DYNAMIC = /* AUDITED_DYNAMIC */ {
  "src/layouts/components/VabFullScreen/index.vue|template|isFullscreen ? 'FullScreen' : 'FullScreen'": "ab1f6276222c5d18d7f0d198fecf866aba8fb8613568e50672739258313a13b9",
  "src/layouts/components/VabNav/index.vue|template|collapse ? 'DArrowRight' : 'DArrowLeft'": "f410326470f15a90386efd1084e826742e6d7c92c41ee6d3c264f71bae910bc7",
  "src/layouts/components/VabSide/components/VabMenuItem.vue|template|getIconComponent(routeChildren.meta.icon)": "b34d50edc8414d99d8a96e1016bb8a5d49c1c5419847a5f97a0e68366f445788",
  "src/layouts/components/VabSide/components/VabSideItem.vue|template|menuComponent": "783e4d710e0324a3a0ce7cd0ace917134a78901d15ee39cdb857bd84530e877a",
  "src/layouts/components/VabSide/components/VabSubmenu.vue|template|getIconComponent(item.meta.icon)": "cd03d090402bd4a2686a7cefbf2a712a07af365e0172471dd276da9e82f49d10",
  "src/layouts/components/VabTabs/index.vue|template|getTabIcon(item)": "ef553196e10f13edf3c1406e083c125fd65fb39cc63627f4e689716ee29b8560",
  "src/plugins/index.js|render|iconComponent": "289c05adbf45c6c350642daec629dc24a3cf41254b01c45a68cfb43a1574d091",
  "src/views/index/index.vue|template|item.icon": "d015ee8ee7c58e1fcdef921b5bae3f6043e7a001309d27fafa8d3623b375a9b6",
  "src/views/vab/campaign.vue|template|getCampaignIcon(row.type)": "14269ba7e23cfc7deff4d04e16b35baad0d25bee18c1b3e5b14007124ec52bca",
  "src/views/vab/campaign.vue|template|getCampaignIcon(detailCampaign.type)": "14269ba7e23cfc7deff4d04e16b35baad0d25bee18c1b3e5b14007124ec52bca",
  "src/views/vab/knowledge.vue|template|data.icon": "d09dccddc68ade0332dcbe0d1aae13072dff4f29022a1a9580fb7e40ec48fa33"
};
const AUDITED_HELPERS = /* AUDITED_HELPERS */ {
  "src/utils/vab.js": "196079db00d6631e13c947f4675ec0df598d2a839eb9ba323fd24baa171ae616"
};

function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  visit(node);
  for (const [key, value] of Object.entries(node)) {
    if (key === 'loc' || key === 'extra' || key === 'tokens' || key === 'comments') continue;
    if (Array.isArray(value)) value.forEach(child => walk(child, visit));
    else if (value && typeof value === 'object') walk(value, visit);
  }
}
function parseScript(text, filename) {
  try { return babel.parse(text, { sourceType: 'unambiguous', plugins: ['typescript', 'jsx', 'decorators-legacy'] }); }
  catch (error) { throw new Error(`${filename}: ${error.message}`); }
}
function componentName(name) {
  if (!/^el-[a-z][a-z0-9-]*$/.test(name) && !/^El[A-Z][A-Za-z0-9]*$/.test(name)) return null;
  return name.replace(/^El/, '').replace(/^el-/, '').replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
}
function sourceFiles(root = ROOT) {
  const result = [];
  function recurse(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) recurse(full);
      else if (/\.(?:vue|[cm]?js|jsx|ts|tsx)$/.test(entry.name) && path.relative(root, full).replaceAll(path.sep, '/') !== OUTPUT) result.push(full);
    }
  }
  for (const name of ['src', 'layouts']) if (fs.existsSync(path.join(root, name))) recurse(path.join(root, name));
  return result.sort();
}
function analyzeFile(filename, text, { dynamicAudits = AUDITED_DYNAMIC } = {}) {
  const requirements = new Set(), explicitStyles = new Set(), dynamics = [];
  const add = name => { const key = componentName(name); if (key) requirements.add(key); };
  const pieces = [], templates = [];
  if (filename.endsWith('.vue')) {
    const parsed = sfc.parse(text, { filename });
    if (parsed.errors.length) throw new Error(`${filename}: invalid SFC: ${parsed.errors[0]}`);
    for (const block of [parsed.descriptor.script, parsed.descriptor.scriptSetup]) if (block) {
      if (block.src || ![undefined, 'js', 'jsx', 'ts', 'tsx'].includes(block.lang)) throw new Error(`${filename}: external/non-JavaScript script requires an explicit style audit`);
      pieces.push(block.content);
    }
    if (parsed.descriptor.template) {
      if (parsed.descriptor.template.src || !['html', undefined].includes(parsed.descriptor.template.lang)) throw new Error(`${filename}: external/non-HTML template requires an explicit style audit`);
      templates.push(parsed.descriptor.template.content);
    }
  } else pieces.push(text);
  const script = pieces.join('\n');
  function dynamic(kind, expression) {
    const key = `${filename}|${kind}|${expression}`;
    if (dynamicAudits[key] !== hash(script)) throw new Error(`${filename}: unreviewed dynamic component ${kind}: ${expression}`);
    dynamics.push(key);
  }
  for (const template of templates) {
    walk(dom.parse(template), node => {
      if (node.type !== 1) return;
      add(node.tag);
      for (const prop of node.props || []) {
        if (prop.type === 7 && prop.name === 'loading') add('ElLoading');
        if (node.tag === 'component' && prop.type === 6 && prop.name === 'is' && prop.value) add(prop.value.content);
        if (node.tag === 'component' && prop.type === 7 && prop.name === 'bind' && prop.arg?.type === 4 && prop.arg.content === 'is') {
          const expression = prop.exp?.content;
          if (!expression) throw new Error(`${filename}: dynamic component without a value`);
          // Literal tags are exact usage. Other expressions are reviewed with
          // their entire source script, not guessed from variable names.
          const parsed = babel.parseExpression(expression, { plugins: ['typescript'] });
          if (parsed.type === 'StringLiteral') add(parsed.value);
          else dynamic('template', expression);
        }
      }
    });
  }
  for (const piece of pieces) {
    const ast = parseScript(piece, filename), renderNames = new Set(['h', 'resolveComponent', 'resolveDynamicComponent', 'createVNode']), importedComponents = new Set();
    walk(ast, node => {
      if (node.type === 'ImportDeclaration' && node.source.value === 'element-plus') for (const spec of node.specifiers) {
        if (componentName(spec.imported?.name || '')) importedComponents.add(spec.local.name);
      }
      if (node.type === 'ImportDeclaration' && node.source.value === 'vue') for (const spec of node.specifiers) {
        if (['h', 'resolveComponent', 'resolveDynamicComponent', 'createVNode'].includes(spec.imported?.name)) renderNames.add(spec.local.name);
      }
    });
    walk(ast, node => {
      if (node.type === 'ImportDeclaration' || node.type === 'ExportNamedDeclaration' || node.type === 'ExportAllDeclaration') {
        const name = node.source?.value;
        if (name === 'element-plus') {
          if (node.type === 'ExportAllDeclaration' || node.specifiers.some(spec => spec.type === 'ImportNamespaceSpecifier' || spec.type === 'ImportDefaultSpecifier')) throw new Error(`${filename}: whole Element Plus namespace/default import needs an explicit full-library policy`);
          for (const spec of node.specifiers) add(spec.imported?.name || spec.local?.name || '');
        }
        if (typeof name === 'string' && name.startsWith('element-plus/')) {
          const deep = name.match(/^element-plus\/(?:es|lib)\/components\/([^/]+)(?:\/|$)/);
          if (deep) requirements.add(deep[1]);
          if (/\/(?:style\/css(?:\.mjs)?|[^/]+\.css)$/.test(name)) explicitStyles.add(name);
          if (/\.s[ac]ss$/.test(name)) throw new Error(`${filename}: direct Sass library import requires a separate audit`);
          if (!deep && !/\.css$/.test(name) && !/^element-plus\/(?:es|lib|dist)\/locale\//.test(name)) throw new Error(`${filename}: unclassified Element Plus entry ${name}`);
        }
      }
      if (node.type === 'CallExpression' && node.callee.type === 'Identifier' && renderNames.has(node.callee.name) && node.arguments.length) {
        const first = node.arguments[0];
        if (first.type === 'StringLiteral') add(first.value);
        else if (first.type === 'Identifier' && importedComponents.has(first.name)) { /* Named component import already included. */ }
        else dynamic('render', piece.slice(first.start, first.end));
      }
      if (node.type === 'CallExpression' && node.callee.type === 'Identifier' && node.callee.name === 'require' && node.arguments[0]?.value?.startsWith('element-plus')) throw new Error(`${filename}: CommonJS Element Plus require needs an explicit named-use audit`);
      if (node.type === 'JSXOpeningElement' && node.name.type === 'JSXIdentifier') add(node.name.name);
      if ((node.type === 'ImportExpression' && typeof node.source?.value === 'string' && node.source.value.startsWith('element-plus')) || (node.type === 'CallExpression' && node.callee.type === 'Import' && node.arguments[0]?.value?.startsWith('element-plus'))) throw new Error(`${filename}: lazy Element Plus import cannot satisfy one global style entry`);
    });
  }
  return { filename, requirements: [...requirements].sort(), explicitStyles: [...explicitStyles].sort(), dynamics: dynamics.sort() };
}
function styleClosure(requirements, explicitStyles = [], root = ROOT) {
  const packageFile = require.resolve('element-plus/package.json', { paths: [root] });
  const library = path.dirname(packageFile), modules = new Map(), css = new Map(), active = new Set();
  function resolve(name, from) {
    const absolute = name.startsWith('.') ? path.resolve(path.dirname(from), name) : resolveImport(root, name);
    if (!absolute.startsWith(library + path.sep)) throw new Error(`Library style escaped Element Plus: ${name}`);
    return absolute;
  }
  function visit(file) {
    if (css.has(file) || modules.has(file)) return;
    if (active.has(file)) throw new Error(`Cyclic style import: ${file}`);
    if (file.endsWith('.css')) { css.set(file, hash(fs.readFileSync(file))); return; }
    active.add(file);
    const raw = fs.readFileSync(file, 'utf8'), ast = parseScript(raw, file);
    for (const node of ast.program.body) {
      if (node.type !== 'ImportDeclaration' || node.specifiers.length) throw new Error(`Unexpected executable library style module: ${file}`);
      visit(resolve(node.source.value, file));
    }
    active.delete(file); modules.set(file, hash(raw));
  }
  const entries = ['base', ...requirements.filter(name => name !== 'base').sort()];
  for (const name of entries) {
    if (!/^[a-z][a-z0-9-]*$/.test(name)) throw new Error(`Invalid component style name: ${name}`);
    const file = path.join(library, 'es/components', name, 'style/css.mjs');
    if (!fs.existsSync(file)) throw new Error(`No actual installed style contract for Element Plus ${name}`);
    visit(file);
  }
  for (const name of explicitStyles) visit(resolve(name, packageFile));
  const relative = absolute => 'element-plus/' + path.relative(library, absolute).split(path.sep).join('/');
  const fullCssBytes = fs.statSync(path.join(library, 'dist/index.css')).size;
  return { version: JSON.parse(fs.readFileSync(packageFile, 'utf8')).version, entryImports: entries.map(name => `element-plus/es/components/${name}/style/css`), explicitStyles,
    styleModules: Object.fromEntries([...modules].map(([file, sha]) => [relative(file), sha])), css: Object.fromEntries([...css].map(([file, sha]) => [relative(file), sha])),
    cssBytes: [...css.keys()].reduce((sum, file) => sum + fs.statSync(file).size, 0), fullCssBytes };
}
function generate(root = ROOT) {
  for (const [name, expected] of Object.entries(AUDITED_HELPERS)) if (hash(fs.readFileSync(path.join(root, name))) !== expected) throw new Error(`${name}: reviewed dynamic icon helper changed`);
  const analysis = sourceFiles(root).map(file => analyzeFile(path.relative(root, file).split(path.sep).join('/'), fs.readFileSync(file, 'utf8')));
  const requirements = [...new Set(analysis.flatMap(value => value.requirements))].sort();
  const explicitStyles = [...new Set(analysis.flatMap(value => value.explicitStyles))].sort();
  const closure = styleClosure(requirements, explicitStyles, root);
  const fingerprint = hash(JSON.stringify({ analysis, closure }));
  const entry = `/* Generated by scripts/generate-element-plus-style-entry.cjs.\n * Element Plus ${closure.version}; ${requirements.length} direct requirements; ${Object.keys(closure.css).length} complete CSS files.\n * Audit fingerprint: ${fingerprint}\n * One global library entry must precede application themes; no lazy style injection.\n */\n` + [...closure.entryImports, ...explicitStyles].map(name => `import ${JSON.stringify(name)};`).join('\n') + '\n';
  return { entry, analysis, requirements, closure, fingerprint, rawCssSavings: closure.fullCssBytes - closure.cssBytes };
}
if (require.main === module) {
  const result = generate(), file = path.join(ROOT, OUTPUT), check = process.argv.includes('--check');
  if (check) {
    if (!fs.existsSync(file) || fs.readFileSync(file, 'utf8') !== result.entry) throw new Error('Element Plus single style entry is stale');
  } else fs.writeFileSync(file, result.entry);
  console.log(JSON.stringify({ check, scannedFiles: result.analysis.length, directRequirements: result.requirements.length, styleModules: Object.keys(result.closure.styleModules).length, cssFiles: Object.keys(result.closure.css).length, cssBytes: result.closure.cssBytes, fullCssBytes: result.closure.fullCssBytes, rawCssSavings: result.rawCssSavings, fingerprint: result.fingerprint }));
}
module.exports = { analyzeFile, sourceFiles, componentName, styleClosure, generate, resolveImport, OUTPUT };
