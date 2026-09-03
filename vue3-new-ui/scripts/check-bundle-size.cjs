const fs = require("node:fs");
const path = require("node:path");

const outputDirectory = path.resolve(__dirname, "..", "dist");
const limits = {
  largestJavaScript: 700_000,
  totalJavaScript: 6_000_000,
  totalAssets: 7_000_000,
};

const files = [];
const visit = (directory) => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) visit(target);
    else files.push({ target, size: fs.statSync(target).size });
  }
};

if (!fs.existsSync(outputDirectory)) {
  throw new Error("dist 不存在，请先执行 npm run build");
}
visit(outputDirectory);

const javascript = files.filter(({ target }) => target.endsWith(".js"));
const totalJavaScript = javascript.reduce((total, file) => total + file.size, 0);
const totalAssets = files.reduce((total, file) => total + file.size, 0);
const largestJavaScript = javascript.reduce((largest, file) => (file.size > largest.size ? file : largest), {
  target: "",
  size: 0,
});

const failures = [];
if (largestJavaScript.size > limits.largestJavaScript) failures.push(`最大 JS ${largestJavaScript.size} > ${limits.largestJavaScript}`);
if (totalJavaScript > limits.totalJavaScript) failures.push(`JS 总量 ${totalJavaScript} > ${limits.totalJavaScript}`);
if (totalAssets > limits.totalAssets) failures.push(`资源总量 ${totalAssets} > ${limits.totalAssets}`);

console.log(JSON.stringify({
  largestJavaScript: { file: path.basename(largestJavaScript.target), bytes: largestJavaScript.size },
  totalJavaScript,
  totalAssets,
  limits,
}, null, 2));

if (failures.length) {
  throw new Error(`bundle 预算超限：${failures.join("；")}`);
}
