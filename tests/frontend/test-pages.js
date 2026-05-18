/**
 * HIS-OP 前端页面全量测试脚本
 *
 * 测试内容：
 * - 遍历所有前端路由页面
 * - 捕获控制台错误（JS 报错）
 * - 捕获网络请求错误（4xx/5xx）
 * - 检查错误提示是否为中文
 * - 检查空状态、加载状态的可读性
 * - 截图留存
 *
 * 运行方式：
 *   npx playwright test tests/frontend/test-pages.js --reporter=list
 * 或：
 *   node tests/frontend/test-pages.js
 */

const { chromium } = require('/home/xusheng/workspace/hoimsystem/vue3-new-ui/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:8091';
const ADMIN_USER = 'admin';
const ADMIN_PASS = 'admin123';
const SCREENSHOT_DIR = path.join(__dirname, 'screenshots');

// 所有需要测试的路由（基于 router/index.js 提取）
// 排除重复和特殊路由
const ROUTES = [
  // 公开页面
  { path: '/login', name: '登录页', needAuth: false },
  { path: '/register', name: '注册页', needAuth: false },
  { path: '/401', name: '401 错误页', needAuth: false },
  { path: '/404', name: '404 错误页', needAuth: false },

  // 首页
  { path: '/#/index', name: '首页', needAuth: true },

  // 管理员模块
  { path: '/#/admin/doctorManagement', name: '医生管理', needAuth: true },
  { path: '/#/admin/patientManagement', name: '病人管理', needAuth: true },
  { path: '/#/admin/departmentManagement', name: '科室管理', needAuth: true },
  { path: '/#/admin/noticeManagement', name: '通知公告', needAuth: true },
  { path: '/#/admin/chargeRecords', name: '收费记录查询', needAuth: true },
  { path: '/#/admin/slotPool', name: '号源池管理', needAuth: true },

  // 患者服务
  { path: '/#/patient/triage', name: '智能导诊', needAuth: true },
  { path: '/#/patient/appointment', name: '预约挂号', needAuth: true },
  { path: '/#/patient/registration', name: '现场挂号', needAuth: true },
  { path: '/#/patient/charge', name: '缴费管理', needAuth: true },
  { path: '/#/patient/medicalRecord', name: '病历查询', needAuth: true },
  { path: '/#/patient/prescription', name: '处方查询', needAuth: true },
  { path: '/#/patient/healthRecord', name: '健康档案', needAuth: true },
  { path: '/#/patient/review', name: '就诊评价', needAuth: true },
  { path: '/#/patient/prepaid', name: '预交金管理', needAuth: true },
  { path: '/#/patient/referral', name: '双向转诊', needAuth: true },

  // 医生工作站
  { path: '/#/doctor/schedule', name: '医生排班', needAuth: true },
  { path: '/#/doctor/medicalRecord', name: '病历管理', needAuth: true },
  { path: '/#/doctor/prescription', name: '处方管理', needAuth: true },
  { path: '/#/doctor/labOrder', name: '检查检验申请', needAuth: true },
  { path: '/#/doctor/attendance', name: '考勤管理', needAuth: true },
  { path: '/#/doctor/mdt', name: '多学科会诊', needAuth: true },
  { path: '/#/doctor/clinicalPathway', name: '临床路径', needAuth: true },

  // 药房管理
  { path: '/#/pharmacy/pharmaceutical', name: '药品管理', needAuth: true },
  { path: '/#/pharmacy/dispense', name: '发药管理', needAuth: true },
  { path: '/#/pharmacy/stockAlert', name: '库存预警', needAuth: true },
  { path: '/#/pharmacy/stockCheck', name: '库存盘点', needAuth: true },
  { path: '/#/pharmacy/prescriptionReview', name: '处方点评', needAuth: true },
  { path: '/#/pharmacy/consumable', name: '耗材管理', needAuth: true },
  { path: '/#/pharmacy/purchase', name: '采购管理', needAuth: true },
  { path: '/#/pharmacy/adverseReaction', name: '不良反应', needAuth: true },

  // 收费管理
  { path: '/#/charge/chargeList', name: '收费列表', needAuth: true },
  { path: '/#/charge/invoice', name: '发票管理', needAuth: true },
  { path: '/#/charge/windowRegistration', name: '窗口挂号', needAuth: true },
  { path: '/#/charge/dailySettlement', name: '日结报表', needAuth: true },

  // 排队叫号
  { path: '/#/queue/triageDesk', name: '分诊台', needAuth: true },
  { path: '/#/queue/queueList', name: '候诊队列', needAuth: true },
  { path: '/#/queue/patrolRecord', name: '巡视记录', needAuth: true },

  // 签到违约
  { path: '/#/checkin/checkIn', name: '患者签到', needAuth: true },
  { path: '/#/checkin/breachRecord', name: '违约记录', needAuth: true },

  // 生命体征
  { path: '/#/vitalsign/vitalSign', name: '生命体征', needAuth: true },

  // 检验检查
  { path: '/#/lab/labResult', name: '检验结果', needAuth: true },

  // 随访管理
  { path: '/#/followup/followUp', name: '随访管理', needAuth: true },

  // 报表统计
  { path: '/#/report/reports', name: '报表统计', needAuth: true },

  // 系统管理
  { path: '/#/system/logs', name: '操作日志', needAuth: true },
  { path: '/#/system/dict', name: '数据字典', needAuth: true },
  { path: '/#/system/config', name: '系统配置', needAuth: true },
  { path: '/#/system/messageCenter', name: '消息中心', needAuth: true },
  { path: '/#/system/backup', name: '数据备份', needAuth: true },
  { path: '/#/system/permission', name: '权限管理', needAuth: true },
  { path: '/#/system/adverseEvent', name: '不良事件', needAuth: true },
  { path: '/#/system/digitalSignature', name: '数字签名', needAuth: true },

  // 住院管理
  { path: '/#/inpatient/wardManagement', name: '病区管理', needAuth: true },
  { path: '/#/inpatient/admission', name: '入院管理', needAuth: true },
  { path: '/#/inpatient/inpatientOrder', name: '医嘱管理', needAuth: true },
  { path: '/#/inpatient/nursingStation', name: '护理工作站', needAuth: true },
  { path: '/#/inpatient/inpatientCharge', name: '住院费用', needAuth: true },
  { path: '/#/inpatient/discharge', name: '出院管理', needAuth: true },
  { path: '/#/inpatient/emr', name: '电子病历', needAuth: true },
  { path: '/#/inpatient/surgery', name: '手术管理', needAuth: true },

  // 体检管理
  { path: '/#/exam/examManagement', name: '体检管理', needAuth: true },
];

// 英文错误关键词（用于检测非中文错误）
const ENGLISH_ERROR_PATTERNS = [
  /\berror\b/i,
  /\bfail\b/i,
  /\bexception\b/i,
  /\bundefined\b/i,
  /\bnull\b/i,
  /\bcannot\b/i,
  /\bunable\b/i,
  /\bsomething went wrong\b/i,
  /\bloading\.{3}\b/i,
  /\bnetwork error\b/i,
  /\brequest failed\b/i,
  /\btimeout\b/i,
  /\bnot found\b/i,
  /\bunauthorized\b/i,
  /\bforbidden\b/i,
];

async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function login(page) {
  console.log('[INFO] 正在登录...');
  await page.goto(`${BASE_URL}/#/login`, { waitUntil: 'networkidle' });
  await delay(2000);

  // 输入用户名密码
  await page.fill('input[placeholder="请输入账号"], input[placeholder*="账号"], input[type="text"]', ADMIN_USER);
  await page.fill('input[placeholder="请输入密码"], input[placeholder*="密码"], input[type="password"]', ADMIN_PASS);

  // 点击登录按钮
  const loginBtn = await page.locator('button:has-text("登录"), button:has-text("登 录")').first();
  if (loginBtn) {
    await loginBtn.click();
  }

  // 等待登录成功（跳转首页或出现菜单）
  await page.waitForURL(/\/#\/index/, { timeout: 15000 }).catch(() => {
    console.log('[WARN] 登录后未跳转到首页，继续测试...');
  });
  await delay(2000);
  console.log('[INFO] 登录完成');
}

async function testPage(browser, route, index, total) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();

  const result = {
    name: route.name,
    path: route.path,
    needAuth: route.needAuth,
    consoleErrors: [],
    networkErrors: [],
    nonChineseMessages: [],
    screenshot: '',
    pageError: null,
    emptyStateText: '',
    errorStateText: '',
    hasEmptyBlock: false,
    hasLoadingText: false,
    status: 'PASS',
  };

  // 监听控制台错误
  page.on('console', msg => {
    const type = msg.type();
    const text = msg.text();
    if (type === 'error') {
      result.consoleErrors.push(text);
    }
  });

  // 监听页面错误
  page.on('pageerror', error => {
    result.pageError = error.message;
  });

  // 监听网络请求错误
  page.on('response', response => {
    const status = response.status();
    const url = response.url();
    if (status >= 400 && url.includes('/api/')) {
      result.networkErrors.push({ url: url.replace(BASE_URL, ''), status });
    }
  });

  try {
    const url = `${BASE_URL}${route.path}`;
    console.log(`[${index + 1}/${total}] 测试: ${route.name} (${route.path})`);

    if (route.needAuth) {
      // 需要先登录
      await login(page);
      // 登录后跳转到目标页面
      await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 });
    } else {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 });
    }

    // 等待页面稳定
    await delay(3000);

    // 检查是否有英文错误提示
    const pageText = await page.locator('body').textContent();
    for (const pattern of ENGLISH_ERROR_PATTERNS) {
      if (pattern.test(pageText)) {
        const matches = pageText.match(new RegExp(pattern.source, 'gi'));
        if (matches) {
          result.nonChineseMessages.push(...matches);
        }
      }
    }

    // 检查空状态文本
    const emptyBlocks = await page.locator('.el-table__empty-text, .el-empty__description, .empty-text, [class*="empty"]').all();
    if (emptyBlocks.length > 0) {
      result.hasEmptyBlock = true;
      for (const block of emptyBlocks.slice(0, 3)) {
        const text = await block.textContent().catch(() => '');
        if (text) result.emptyStateText += text + '; ';
      }
    }

    // 检查加载状态
    const loadingTexts = await page.locator('.el-loading-text, .el-loading-spinner .el-loading-text, [class*="loading"]').all();
    if (loadingTexts.length > 0) {
      result.hasLoadingText = true;
    }

    // 检查错误状态
    const errorTexts = await page.locator('.el-result__subtitle, .el-result__title, [class*="error"]').all();
    if (errorTexts.length > 0) {
      for (const el of errorTexts.slice(0, 3)) {
        const text = await el.textContent().catch(() => '');
        if (text) result.errorStateText += text + '; ';
      }
    }

    // 截图
    const screenshotPath = path.join(SCREENSHOT_DIR, `${String(index + 1).padStart(3, '0')}_${route.name.replace(/[^一-龥a-zA-Z0-9]/g, '_')}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    result.screenshot = screenshotPath;

    // 判定状态
    if (result.consoleErrors.length > 0 || result.pageError || result.networkErrors.length > 0) {
      result.status = 'FAIL';
    } else if (result.nonChineseMessages.length > 0) {
      result.status = 'WARN';
    }

  } catch (e) {
    result.status = 'ERROR';
    result.pageError = e.message;
    // 错误时也截图
    const screenshotPath = path.join(SCREENSHOT_DIR, `${String(index + 1).padStart(3, '0')}_${route.name.replace(/[^一-龥a-zA-Z0-9]/g, '_')}_ERROR.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    result.screenshot = screenshotPath;
  }

  await context.close();
  return result;
}

async function generateReport(results) {
  const total = results.length;
  const passed = results.filter(r => r.status === 'PASS').length;
  const warned = results.filter(r => r.status === 'WARN').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const errored = results.filter(r => r.status === 'ERROR').length;

  const now = new Date().toLocaleString('zh-CN');

  let md = `# HIS-OP 前端页面测试报告\n\n`;
  md += `> **生成时间**：${now}\n`;
  md += `> **测试环境**：${BASE_URL}\n`;
  md += `> **测试账号**：${ADMIN_USER}\n`;
  md += `> **浏览器**：Chromium (Playwright)\n\n`;
  md += `---\n\n`;

  md += `## 一、测试总览\n\n`;
  md += `- **测试页面总数**：${total}\n`;
  md += `- **通过**：${passed} (${((passed / total) * 100).toFixed(1)}%)\n`;
  md += `- **警告**：${warned} (${((warned / total) * 100).toFixed(1)}%)\n`;
  md += `- **失败**：${failed} (${((failed / total) * 100).toFixed(1)}%)\n`;
  md += `- **错误**：${errored} (${((errored / total) * 100).toFixed(1)}%)\n\n`;

  md += `## 二、分模块统计\n\n`;
  md += `| 页面名称 | 路径 | 状态 | 控制台错误 | 网络错误 | 英文提示 | 空状态 | 截图 |\n`;
  md += `|:----|:----|:----:|:----:|:----:|:----:|:----:|:----:|\n`;
  for (const r of results) {
    const statusEmoji = r.status === 'PASS' ? '✅' : (r.status === 'WARN' ? '⚠️' : '❌');
    const ce = r.consoleErrors.length;
    const ne = r.networkErrors.length;
    const nc = r.nonChineseMessages.length;
    const es = r.hasEmptyBlock ? '有' : '-';
    md += `| ${r.name} | \`${r.path}\` | ${statusEmoji} ${r.status} | ${ce} | ${ne} | ${nc} | ${es} | [截图](${r.screenshot.replace(__dirname + '/', '')}) |\n`;
  }
  md += `\n`;

  // 失败详情
  const problems = results.filter(r => r.status !== 'PASS');
  if (problems.length > 0) {
    md += `## 三、问题详情\n\n`;
    for (const r of problems) {
      md += `### ${r.name} (${r.path})\n\n`;
      md += `- **状态**：${r.status}\n`;
      if (r.pageError) {
        md += `- **页面错误**：\`\`\`${r.pageError}\`\`\`\n`;
      }
      if (r.consoleErrors.length > 0) {
        md += `- **控制台错误**：\n`;
        for (const err of r.consoleErrors.slice(0, 5)) {
          md += `  - \`\`\`${err.substring(0, 200)}\`\`\`\n`;
        }
      }
      if (r.networkErrors.length > 0) {
        md += `- **网络错误**：\n`;
        for (const err of r.networkErrors.slice(0, 5)) {
          md += `  - HTTP ${err.status}: \`${err.url}\`\n`;
        }
      }
      if (r.nonChineseMessages.length > 0) {
        md += `- **英文提示**：\n`;
        for (const msg of [...new Set(r.nonChineseMessages)].slice(0, 5)) {
          md += `  - \`${msg}\`\n`;
        }
      }
      if (r.emptyStateText) {
        md += `- **空状态文本**：\`${r.emptyStateText.substring(0, 100)}\`\n`;
      }
      if (r.errorStateText) {
        md += `- **错误状态文本**：\`${r.errorStateText.substring(0, 100)}\`\n`;
      }
      md += `- **截图**：${r.screenshot}\n\n`;
    }
  }

  // 空状态检查
  const emptyPages = results.filter(r => r.hasEmptyBlock);
  md += `## 四、空状态检查\n\n`;
  md += `共 **${emptyPages.length}** 个页面检测到空状态（表格/列表无数据时的提示）：\n\n`;
  md += `| 页面 | 空状态文本 | 是否为中文 |\n`;
  md += `|:----|:----|:----:|\n`;
  for (const r of emptyPages) {
    const isChinese = r.emptyStateText && /[一-龥]/.test(r.emptyStateText);
    md += `| ${r.name} | ${r.emptyStateText.substring(0, 50) || '（无文本）'} | ${isChinese ? '✅' : '⚠️'} |\n`;
  }
  md += `\n`;

  // 可读性建议
  md += `## 五、可读性与用户体验建议\n\n`;
  md += `### 5.1 错误处理\n\n`;
  md += `- 所有错误提示应使用中文，避免英文技术术语直接暴露给用户\n`;
  md += `- 空状态应提供友好的引导文案，如「暂无数据，点击新增」\n`;
  md += `- 加载状态应显示中文提示，如「加载中...」而非「Loading...」\n\n`;
  md += `### 5.2 页面标题与导航\n\n`;
  md += `- 所有页面标题应为中文，与菜单保持一致\n`;
  md += `- 面包屑导航应清晰反映当前位置\n\n`;
  md += `### 5.3 表单与操作\n\n`;
  md += `- 输入框占位符应为中文\n`;
  md += `- 按钮文字应简洁明确\n`;
  md += `- 操作成功/失败提示应为中文\n\n`;

  md += `## 六、测试方法\n\n`;
  md += `\`\`\`bash\n`;
  md += `# 启动前端开发服务器\n`;
  md += `cd vue3-new-ui && npm run serve:rspack\n\n`;
  md += `# 运行前端页面测试\n`;
  md += `node tests/frontend/test-pages.js\n`;
  md += `\`\`\`\n\n`;

  md += `## 七、相关文档\n\n`;
  md += `- [测试指南](testing.md)\n`;
  md += `- [API 测试报告](api-test-report.md)\n`;
  md += `- [用户操作手册](user-manual.md)\n`;

  fs.writeFileSync(path.join(__dirname, '..', '..', 'doc', 'frontend-test-report.md'), md, 'utf8');

  // 同时输出 JSON
  fs.writeFileSync(path.join(__dirname, 'test-results.json'), JSON.stringify(results, null, 2), 'utf8');

  console.log(`\n========== 测试完成 ==========`);
  console.log(`总计: ${total}`);
  console.log(`通过: ${passed}`);
  console.log(`警告: ${warned}`);
  console.log(`失败: ${failed}`);
  console.log(`错误: ${errored}`);
  console.log(`报告: doc/frontend-test-report.md`);
  console.log(`JSON: tests/frontend/test-results.json`);
}

async function main() {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }

  console.log('========== HIS-OP 前端页面测试开始 ==========');
  console.log(`目标: ${ROUTES.length} 个页面`);
  console.log(`前端地址: ${BASE_URL}`);
  console.log('');

  const browser = await chromium.launch({ headless: true });
  const results = [];

  for (let i = 0; i < ROUTES.length; i++) {
    const route = ROUTES[i];
    const result = await testPage(browser, route, i, ROUTES.length);
    results.push(result);

    // 每页之间稍作停顿，避免过载
    await delay(1000);
  }

  await browser.close();
  await generateReport(results);
}

main().catch(console.error);
