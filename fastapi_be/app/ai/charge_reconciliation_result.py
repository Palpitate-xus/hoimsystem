"""Deterministic record counts around explicitly partial, unreviewed questions."""

from pydantic import ConfigDict

from app.ai.charge_reconciliation_draft import MAX_BYTES, ChargeReconciliationDraft, canonical_json, structural_counts, validate_draft
from app.ai.schemas import GenerationResult

WARNINGS = [
    "模型仅提出部分待人工核实问题；引文一致不证明关联、收费正确性、漏费、重复收费或责任，未提出问题也不表示全部记录正确。",
    "本件未提供实际收款、现金退款或押金交易流水；已记录结算、退款状态与押金汇总不能证明资金流动。",
    "本功能没有增加收费项目、修改数量或金额、执行退款或财务核销。",
]
MISSING = [
    "币种、历史价格和收费适用依据未知。",
    "仅有医嘱层级关联；逐收费行与逐医嘱项目、执行记录之间的实际分摊依据未提供。",
    "浮点数量的驱动值与MySQL存储见证均不是最初输入的精确十进制；既有日期的时区未知。",
    "已做已知直接标识最小化；模型可见显示字段不保证匿名，引用位置仅对应本次公开投影。",
]


class ChargeReconciliationResult(GenerationResult):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)
    charge_analysis: ChargeReconciliationDraft


def result_for_draft(source, draft, projection_hash):
    validate_draft(source, draft, projection_hash)
    counts = structural_counts(source)
    associations = counts["charge_order_association_counts"]
    result = ChargeReconciliationResult(
        summary=f"本次形成{len(draft.observations)}项待人工核实的收费记录问题，覆盖范围不完整，尚未确认财务结论。",
        sections=[
            {
                "title": "完整冻结记录数量",
                "content": (
                    f"本件保留收费记录{counts['charges_count']}条、医嘱{counts['orders_count']}条、医嘱项目{counts['order_items_count']}条、"
                    f"医嘱执行{counts['executions_count']}条、给药记录{counts['administrations_count']}条。记录条数不表示服务发生次数、应收费次数或资金笔数。"
                ),
                "source_ids": [source["source_id"]],
            },
            {
                "title": "原记录的医嘱关联状态",
                "content": (
                    f"收费字段未记录医嘱关联{associations['not_recorded']}条，记录指向本次同住院医嘱{associations['recorded_same_admission']}条，"
                    f"无法在本次住院范围解析{associations['unresolved_or_out_of_scope']}条。记录关联不证明收费适用性、逐项目执行分摊或应收应退。"
                ),
                "source_ids": [source["source_id"]],
            },
        ],
        warnings=list(WARNINGS),
        missing_data=list(MISSING),
        charge_analysis=draft,
    )
    if len(canonical_json(result.model_dump(mode="json")).encode("utf-8")) > MAX_BYTES:
        raise ValueError("The whole result exceeds its UTF8 storage budget")
    return result


def validate_result(value, source, projection_hash):
    checked = ChargeReconciliationResult.model_validate(value)
    expected = result_for_draft(source, checked.charge_analysis, projection_hash)
    if checked.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("The recorded structure, complete draft or fixed server explanation differs")
    return checked
