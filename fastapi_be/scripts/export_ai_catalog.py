"""Export the exact default catalog and prompts for review without accessing a database."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.catalog import CATALOG_VERSION, COMMON_SYSTEM_PROMPT, FEATURES, describe_feature
from app.ai.document_extraction_prompt import system_prompt_for

CATEGORIES = {
    "cdss": "临床决策",
    "pharmacy": "用药与药事",
    "records": "病历文书",
    "diagnostics": "检验检查",
    "inpatient": "住院护理",
    "patient": "患者服务",
    "operations": "医院运营",
    "knowledge": "知识与科研",
}
ENGINES = {"llm": "文本网关", "speech": "语音适配器", "vision": "视觉适配器", "signal": "信号适配器", "prediction": "预测适配器", "optimizer": "优化适配器"}
SCOPES = {"patient": "授权患者与所选就诊", "input": "使用者提供资料", "hospital": "授权医院/科室汇总"}
ROLES = {
    "super_admin": "超级管理员",
    "admin": "管理员",
    "director": "科主任",
    "doctor": "医生",
    "nurse": "护士",
    "pharmacist": "药师",
    "patient": "患者",
    "guide": "导诊",
    "lab_technician": "检验技师",
    "cashier": "收费员",
}


def artifacts() -> dict[str, str]:
    payload = {
        "catalog_version": CATALOG_VERSION,
        "system_prompt": COMMON_SYSTEM_PROMPT,
        "system_prompt_overrides": {"drg_evidence_review": system_prompt_for({"coding_binding": None}), "guideline_ingestion": system_prompt_for({"document_binding": None})},
        "features": [{**describe_feature(spec), "task_prompt": spec.task_prompt} for spec in FEATURES],
    }
    lines = [
        "# AI 能力与默认 Prompt 清单",
        "",
        "此文件由 `fastapi_be/scripts/export_ai_catalog.py` 从代码生成；可用 `--check` 检查漂移。",
        "",
        "80 项能力均有独立任务 Prompt、配置、授权、任务和反馈入口。文本网关及专用适配器契约不等同于完成真实模型接入或临床验证；实际配置、验证和启用状态以超级管理员管理台为准。",
        "",
        "所有能力初始关闭。临床启用需要真实适用数据、审核知识和验证记录；专用能力还需要对应适配服务及验证报告。",
        "",
        "可直接审阅 [完整默认 Prompt JSON](ai-prompts.json)；管理台中的不可变 Prompt 版本可覆盖各任务默认文本，固定系统契约始终附加。",
        "JSON 的 system_prompt_overrides 列出编码证据和指南区间提取的实际独立系统契约；其余能力使用 system_prompt。每项 task_prompt 为独立默认任务文本。",
        "",
        "| 编号 | 能力 | 分类 | 优先级 | 运行接口 | 资料范围 | 审核知识要求 | 默认使用角色 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for spec in FEATURES:
        roles = "、".join(ROLES[role] for role in spec.default_roles)
        lines.append(
            f"| {spec.number:02d} | {spec.name} | {CATEGORIES[spec.category]} | {spec.priority} | {ENGINES[spec.engine]} | {SCOPES[spec.scope]} | {'必须有适用发布版本' if spec.requires_knowledge else '依任务事实与规则'} | {roles} |"
        )
    lines.extend(["", "当前临床资料、确定性工具、迁移和配置说明见 [AI 平台指南](ai-guide.md)。", ""])
    return {"ai-capabilities.md": "\n".join(lines), "ai-prompts.json": json.dumps(payload, ensure_ascii=False, indent=2) + "\n"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Only check the committed generated artifacts")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[2] / "doc"
    drift = []
    for name, content in artifacts().items():
        path = directory / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                drift.append(name)
        else:
            path.write_text(content, encoding="utf-8")
    if drift:
        parser.exit(1, "AI catalog artifacts need regeneration: " + ", ".join(drift) + "\n")
    print(f"{'Checked' if args.check else 'Exported'} {len(FEATURES)} AI capabilities and default task prompts")


if __name__ == "__main__":
    main()
