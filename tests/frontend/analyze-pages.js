/**
 * HIS-OP 前端页面代码级分析脚本
 *
 * 由于环境限制无法启动真实浏览器，本脚本通过静态代码分析检查：
 * - 英文错误提示（用户可见）
 * - 英文空状态文本
 * - 英文加载状态
 * - 英文按钮/标签文本
 * - console.log / alert / confirm 中的英文
 * - 缺少错误处理的 API 调用
 * - Element Plus 默认英文属性
 * - 用户可读性（占位符、提示文本）
 */

const fs = require('fs');
const path = require('path');

const VIEWS_DIR = path.join(__dirname, '..', '..', 'vue3-new-ui', 'src', 'views');
const COMPONENTS_DIR = path.join(__dirname, '..', '..', 'vue3-new-ui', 'src', 'components');
const LAYOUTS_DIR = path.join(__dirname, '..', '..', 'vue3-new-ui', 'src', 'layouts');

// 用户可见的英文模式（需要检查是否为中文）
const USER_VISIBLE_PATTERNS = [
  // alert/confirm/message 中的英文
  { regex: /(?:ElMessage|Message|this\.\$message|\$message)\.(?:error|success|warning|info)\s*\(\s*(['"`])((?:(?!\1).)+)\1/g, type: '消息提示', group: 2 },
  // alert/confirm
  { regex: /(?:alert|confirm|prompt)\s*\(\s*(['"`])((?:(?!\1).)+)\1/g, type: '弹窗提示', group: 2 },
  // placeholder 英文
  { regex: /placeholder\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '占位符', group: 2 },
  // label 英文
  { regex: /label\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '标签', group: 2 },
  // title 英文（在模板中）
  { regex: /title\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '标题', group: 2 },
  // empty-text
  { regex: /empty-text\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '空状态', group: 2 },
  // loading-text
  { regex: /loading-text\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '加载文本', group: 2 },
  // dialog title
  { regex: /:title\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '弹窗标题', group: 2 },
  // button text
  { regex: />el-button[^>]*>\s*([一-龥a-zA-Z0-9\s]+)\s*<\/el-button>/g, type: '按钮文本', group: 1 },
  // 表格列 label
  { regex: /:label\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '表格列标签', group: 2 },
  // option label
  { regex: /:label\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '选项标签', group: 2 },
  // 页面标题 VabPageHeader
  { regex: /VabPageHeader[^>]*title\s*=\s*(['"`])((?:(?!\1).)+)\1/g, type: '页面标题', group: 2 },
  // div/span 中的纯文本（简单匹配）
  { regex: />\s*([A-Z][a-zA-Z\s]{2,30})\s*<\//g, type: '页面文本', group: 1 },
];

// console 相关英文模式
const CONSOLE_PATTERNS = [
  { regex: /console\.(log|error|warn|info)\s*\(/g, type: 'console输出' },
];

// 需要警惕的英文错误关键词（用户可能看到）
const SUSPICIOUS_ENGLISH = [
  /\berror\b/i,
  /\bfailed\b/i,
  /\bsuccess\b/i,
  /\bloading\.{0,3}\b/i,
  /\bplease\b/i,
  /\bclick\b/i,
  /\bsubmit\b/i,
  /\bcancel\b/i,
  /\bdelete\b/i,
  /\bedit\b/i,
  /\badd\b/i,
  /\bsearch\b/i,
  /\breset\b/i,
  /\brefresh\b/i,
  /\bsave\b/i,
  /\bconfirm\b/i,
  /\bclose\b/i,
  /\bopen\b/i,
  /\bcreate\b/i,
  /\bupdate\b/i,
  /\bquery\b/i,
  /\blist\b/i,
  /\bdetail\b/i,
];

function findVueFiles(dir, files = []) {
  if (!fs.existsSync(dir)) return files;
  const items = fs.readdirSync(dir);
  for (const item of items) {
    const fullPath = path.join(dir, item);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      findVueFiles(fullPath, files);
    } else if (item.endsWith('.vue')) {
      files.push(fullPath);
    }
  }
  return files;
}

function isMostlyEnglish(str) {
  if (!str || str.trim().length === 0) return false;
  const clean = str.trim();
  // 如果包含中文，认为是中文
  if (/[一-龥]/.test(clean)) return false;
  // 如果是纯数字或特殊字符，忽略
  if (/^[\d\s\W]+$/.test(clean)) return false;
  // 如果是 Vue 表达式或变量名，忽略
  if (/^[a-zA-Z_][a-zA-Z0-9_.\[\]]*$/.test(clean)) return false;
  // 如果是模板语法，忽略
  if (/\{\{|\}\}|\$\{|\}/.test(clean)) return false;
  // 如果是短字符串（1-2个单词），可能是变量名
  if (clean.split(/\s+/).length <= 2 && /^[a-zA-Z\s]+$/.test(clean)) return true;
  // 其他包含英文的认为是英文
  return /[a-zA-Z]/.test(clean);
}

function analyzeFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const relativePath = filePath.replace(path.join(__dirname, '..', '..'), '');
  const result = {
    file: relativePath,
    messages: [],
    consoleStatements: [],
    suspiciousEnglish: [],
    emptyTextMissing: false,
    errorHandlingMissing: false,
  };

  // 检查用户可见的英文文本
  for (const pattern of USER_VISIBLE_PATTERNS) {
    let match;
    const regex = new RegExp(pattern.regex.source, 'g');
    while ((match = regex.exec(content)) !== null) {
      const text = match[pattern.group];
      if (text && isMostlyEnglish(text)) {
        result.messages.push({
          type: pattern.type,
          text: text.substring(0, 100),
          line: content.substring(0, match.index).split('\n').length,
        });
      }
    }
  }

  // 检查 console 语句
  for (const pattern of CONSOLE_PATTERNS) {
    let match;
    const regex = new RegExp(pattern.regex.source, 'g');
    while ((match = regex.exec(content)) !== null) {
      const line = content.substring(0, match.index).split('\n').length;
      const lineContent = content.split('\n')[line - 1].trim();
      result.consoleStatements.push({
        type: pattern.type,
        line,
        content: lineContent.substring(0, 150),
      });
    }
  }

  // 检查可疑英文关键词
  for (const pattern of SUSPICIOUS_ENGLISH) {
    let match;
    const regex = new RegExp(pattern.source, 'g');
    while ((match = regex.exec(content)) !== null) {
      const line = content.substring(0, match.index).split('\n').length;
      const lineContent = content.split('\n')[line - 1].trim();
      // 只记录用户可见的上下文（在模板中）
      if (lineContent.includes('>') || lineContent.includes('placeholder') ||
          lineContent.includes('label') || lineContent.includes('title')) {
        result.suspiciousEnglish.push({
          word: match[0],
          line,
          context: lineContent.substring(0, 150),
        });
      }
    }
  }

  // 检查是否有 el-table 但没有 empty-text
  if (content.includes('<el-table') && !content.includes('empty-text')) {
    result.emptyTextMissing = true;
  }

  // 检查 API 调用是否有错误处理
  const apiCalls = [...content.matchAll(/\.then\s*\(/g)];
  const catchBlocks = [...content.matchAll(/\.catch\s*\(/g)];
  if (apiCalls.length > catchBlocks.length * 1.5) {
    result.errorHandlingMissing = true;
  }

  return result;
}

function generateReport(results) {
  const now = new Date().toLocaleString('zh-CN');
  const totalFiles = results.length;
  const filesWithIssues = results.filter(r =>
    r.messages.length > 0 ||
    r.consoleStatements.length > 0 ||
    r.suspiciousEnglish.length > 0 ||
    r.emptyTextMissing ||
    r.errorHandlingMissing
  );

  let md = `# HIS-OP 前端页面代码审查报告\n\n`;
  md += `> **生成时间**：${now}\n`;
  md += `> **分析范围**：vue3-new-ui/src/views/ 下所有 .vue 文件\n`;
  md += `> **分析方法**：静态代码分析（正则匹配用户可见文本）\n\n`;
  md += `---\n\n`;

  md += `## 一、审查总览\n\n`;
  md += `- **分析文件总数**：${totalFiles}\n`;
  md += `- **有问题的文件**：${filesWithIssues.length}\n`;
  md += `- **英文提示问题**：${results.reduce((sum, r) => sum + r.messages.length, 0)} 处\n`;
  md += `- **console 语句**：${results.reduce((sum, r) => sum + r.consoleStatements.length, 0)} 处\n`;
  md += `- **可疑英文关键词**：${results.reduce((sum, r) => sum + r.suspiciousEnglish.length, 0)} 处\n`;
  md += `- **缺少 empty-text**：${results.filter(r => r.emptyTextMissing).length} 个文件\n`;
  md += `- **错误处理不足**：${results.filter(r => r.errorHandlingMissing).length} 个文件\n\n`;

  // 按问题类型统计
  const typeCount = {};
  for (const r of results) {
    for (const m of r.messages) {
      typeCount[m.type] = (typeCount[m.type] || 0) + 1;
    }
  }
  md += `### 问题类型分布\n\n`;
  md += `| 类型 | 数量 |\n`;
  md += `|:----|:----:|\n`;
  for (const [type, count] of Object.entries(typeCount).sort((a, b) => b[1] - a[1])) {
    md += `| ${type} | ${count} |\n`;
  }
  md += `\n`;

  // 详细问题列表
  md += `## 二、英文用户可见文本详情\n\n`;
  md += `> 以下是在页面中发现的英文文本，可能暴露给用户。建议全部改为中文。\n\n`;

  const msgResults = results.filter(r => r.messages.length > 0);
  if (msgResults.length === 0) {
    md += `✅ **未发现英文用户可见文本**\n\n`;
  } else {
    for (const r of msgResults) {
      md += `### ${r.file}\n\n`;
      md += `| 类型 | 文本 | 行号 |\n`;
      md += `|:----|:----|:----:|\n`;
      for (const m of r.messages) {
        md += `| ${m.type} | \`${m.text.replace(/\|/g, '\\|')}\` | ${m.line} |\n`;
      }
      md += `\n`;
    }
  }

  // console 语句
  md += `## 三、console 语句检查\n\n`;
  const consoleResults = results.filter(r => r.consoleStatements.length > 0);
  if (consoleResults.length === 0) {
    md += `✅ **未发现 console 语句**\n\n`;
  } else {
    md += `> ⚠️ 生产环境应移除所有 console 语句或使用日志框架\n\n`;
    for (const r of consoleResults.slice(0, 20)) {
      md += `### ${r.file} (${r.consoleStatements.length} 处)\n\n`;
      for (const c of r.consoleStatements.slice(0, 5)) {
        md += `- 第 ${c.line} 行：\`\`\`${c.content}\`\`\`\n`;
      }
      md += `\n`;
    }
  }

  // 缺少 empty-text
  md += `## 四、空状态检查\n\n`;
  const emptyMissing = results.filter(r => r.emptyTextMissing);
  if (emptyMissing.length === 0) {
    md += `✅ **所有表格都有 empty-text 属性**\n\n`;
  } else {
    md += `> ⚠️ 以下文件使用了 el-table 但未设置 empty-text，将显示 Element Plus 默认英文空状态\n\n`;
    md += `| 文件 | 建议 |\n`;
    md += `|:----|:----|\n`;
    for (const r of emptyMissing) {
      md += `| ${r.file} | 添加 empty-text="暂无数据" |\n`;
    }
    md += `\n`;
  }

  // 错误处理
  md += `## 五、错误处理检查\n\n`;
  const errorMissing = results.filter(r => r.errorHandlingMissing);
  if (errorMissing.length === 0) {
    md += `✅ **所有 API 调用都有适当的错误处理**\n\n`;
  } else {
    md += `> ⚠️ 以下文件的 API 调用缺少足够的 .catch 错误处理\n\n`;
    md += `| 文件 | 建议 |\n`;
    md += `|:----|:----|\n`;
    for (const r of errorMissing.slice(0, 20)) {
      md += `| ${r.file} | 为 API 调用添加 .catch 错误处理 |\n`;
    }
    md += `\n`;
  }

  // 可读性建议
  md += `## 六、可读性与用户体验建议\n\n`;
  md += `### 6.1 错误提示\n\n`;
  md += `- ✅ 所有错误提示应使用中文\n`;
  md += `- ✅ 避免将技术错误直接展示给用户\n`;
  md += `- ✅ 错误提示应包含操作建议，如「请稍后重试」「请联系管理员」\n\n`;
  md += `### 6.2 空状态\n\n`;
  md += `- ✅ 表格/列表为空时应显示中文提示「暂无数据」\n`;
  md += `- ✅ 空状态可配合图标和引导操作（如「点击新增」）\n\n`;
  md += `### 6.3 加载状态\n\n`;
  md += `- ✅ 加载中提示应为中文「加载中...」\n`;
  md += `- ✅ 长时间操作应显示进度或预计时间\n\n`;
  md += `### 6.4 表单占位符\n\n`;
  md += `- ✅ 输入框占位符应为中文，如「请输入患者姓名」\n`;
  md += `- ✅ 下拉框占位符应为中文，如「请选择科室」\n\n`;
  md += `### 6.5 按钮与操作\n\n`;
  md += `- ✅ 按钮文字应简洁明确，如「保存」「取消」「查询」「重置」\n`;
  md += `- ✅ 危险操作应有确认提示\n\n`;

  // 修复建议汇总
  md += `## 七、快速修复清单\n\n`;
  md += `按优先级排序：\n\n`;
  md += `1. **高优先级**：将用户可见的英文错误提示改为中文\n`;
  md += `2. **高优先级**：为所有 el-table 添加 empty-text="暂无数据"\n`;
  md += `3. **中优先级**：移除或替换生产环境中的 console 语句\n`;
  md += `4. **中优先级**：为 API 调用补充 .catch 错误处理\n`;
  md += `5. **低优先级**：统一检查表单占位符和按钮文本的中文表达\n\n`;

  md += `## 八、测试方法\n\n`;
  md += `\`\`\`bash\n`;
  md += `# 运行本分析脚本\n`;
  md += `node tests/frontend/analyze-pages.js\n`;
  md += `\`\`\`\n\n`;

  md += `## 九、相关文档\n\n`;
  md += `- [测试指南](testing.md)\n`;
  md += `- [API 测试报告](api-test-report.md)\n`;
  md += `- [用户操作手册](user-manual.md)\n`;

  fs.writeFileSync(path.join(__dirname, '..', '..', 'doc', 'frontend-test-report.md'), md, 'utf8');

  // JSON 输出
  fs.writeFileSync(path.join(__dirname, 'analysis-results.json'), JSON.stringify(results, null, 2), 'utf8');

  console.log(`\n========== 分析完成 ==========`);
  console.log(`文件总数: ${totalFiles}`);
  console.log(`问题文件: ${filesWithIssues.length}`);
  console.log(`英文提示: ${results.reduce((sum, r) => sum + r.messages.length, 0)}`);
  console.log(`console语句: ${results.reduce((sum, r) => sum + r.consoleStatements.length, 0)}`);
  console.log(`缺少empty-text: ${results.filter(r => r.emptyTextMissing).length}`);
  console.log(`报告: doc/frontend-test-report.md`);
  console.log(`JSON: tests/frontend/analysis-results.json`);
}

function main() {
  console.log('========== HIS-OP 前端页面代码分析开始 ==========');
  console.log(`视图目录: ${VIEWS_DIR}`);
  console.log('');

  const vueFiles = findVueFiles(VIEWS_DIR);
  console.log(`找到 ${vueFiles.length} 个 .vue 文件`);

  const results = [];
  for (const file of vueFiles) {
    const result = analyzeFile(file);
    results.push(result);
    if (result.messages.length > 0 || result.consoleStatements.length > 0) {
      console.log(`[WARN] ${path.basename(file)}: ${result.messages.length} 英文提示, ${result.consoleStatements.length} console语句`);
    }
  }

  generateReport(results);
}

main();
