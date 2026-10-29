const assert = require("node:assert/strict");
const test = require("node:test");
const { noticeText, noticeList } = require("../src/utils/noticeText.cjs");

test("patient-specific risks, units and timestamps remain exact", () => {
  const text = "肌酐基线缺失；2026-10-29T08:12:00Z的血钾为6.8 mmol/L，请立即复核。";
  assert.equal(noticeText(text), text);
  assert.deepEqual(noticeList([text]), [text]);
});

test("repeated introductions are omitted while actual missing data stays visible", () => {
  const missing = "未取得过去7日的肌酐基线，倍率未知。";
  const intro = "技术发布和来源校验不代表编码员或医生已确认；直接标识最小化不保证匿名。";
  assert.deepEqual(noticeList([intro, missing, missing]), [missing]);
});

test("historical task notices use a direct statement of the missing fact", () => {
  assert.equal(
    noticeText("当前字典未提供发行版本；已记录分组缺少原历史规则依据，本地前缀规则包不等于官方DRG/DIP分组器。"),
    "字典发行版本和历史分组规则待补充。",
  );
});

test("presentation preserves the original frozen result and numeric states", () => {
  const result = Object.freeze({
    warnings: Object.freeze(["资料不足，当前无法判断。"]),
    missing_data: Object.freeze(["呼吸频率未测"]),
    score: 0,
    total: null,
    source_id: "source:original",
  });
  const original = JSON.stringify(result);
  noticeList(result.warnings);
  noticeList(result.missing_data);
  assert.equal(JSON.stringify(result), original);
  assert.equal(noticeText("原字段为null"), "原字段为null");
});

test("AKI summaries retain the observed stage when removing a stock suffix", () => {
  assert.equal(
    noticeText("所选资料符合至少一项KDIGO 2012规则，最低支持2期；仅供结合原资料与临床病程人工复核，不代表完整病程最高分期。"),
    "所选资料符合至少一项KDIGO 2012规则，最低支持2期。",
  );
});

test("frozen document disclaimers are omitted from notices while quoted text remains available", () => {
  const message = "逐字区间一致仅证明定位，不证明临床含义、疗效、安全性或适用条件正确。";
  const evidence = Object.freeze({ quote: message, start: 0, end: message.length });
  assert.deepEqual(noticeList([message, "原文缺少发布日期"]), ["原文缺少发布日期"]);
  assert.equal(evidence.quote, message);
});
