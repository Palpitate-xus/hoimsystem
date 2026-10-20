"""Selected patient-linked incident reports and recorded RCA, with explicit evidentiary status."""

from app.models import AdverseEventRca


def attach_incident_sources(db, selected, bundle, add):
    event = selected.get("adverse_event_id")
    bundle.data["scope_note"] = "仅明确所选的同患者不良事件及关联RCA；事件无就诊外键，不根据上报日期推断属于某次门诊或住院。原文为记录陈述，不等于经调查证实"
    if event is None:
        bundle.data["missing_data"].append("请明确选择本患者的不良事件标识；未自动读取其他事件或整份病史")
        return
    bundle.data["incident_source_scope"] = {"event_id": event.event_id, "encounter_assignment": "not_recorded", "root_cause_verification": "not_recorded"}
    bundle.data["incident_record"] = add(
        "adverse-event:" + str(event.event_id),
        "所选不良事件的原上报与处理记录",
        {
            "event_id": event.event_id,
            "recorded_event_type": event.event_type,
            "reported_description": event.description,
            "recorded_severity": event.severity,
            "report_time": event.report_time,
            "recorded_status": event.status,
            "recorded_handle_result": event.handle_result,
            "definition_note": "严重度1轻度、2中度、3重度；状态0待处理、1处理中、2已闭环，其他值保持未知。上报时间不等于发生时间，已闭环不等于根因和责任已获独立核实",
        },
        event.report_time,
    )
    rows = db.query(AdverseEventRca).filter_by(event_id=event.event_id).order_by(AdverseEventRca.update_time.desc(), AdverseEventRca.create_time.desc(), AdverseEventRca.rca_id).limit(7).all()
    bundle.data["incident_rca_records"] = [
        add(
            "incident-rca:" + str(row.rca_id),
            "所选事件的已保存RCA分析",
            {
                "rca_id": row.rca_id,
                "event_id": row.event_id,
                "recorded_summary": row.event_summary,
                "recorded_timeline_text": row.timeline,
                "recorded_root_cause_text": row.root_cause,
                "recorded_corrective_actions": row.corrective_actions,
                "recorded_pdca_stage": row.pdca_cycle,
                "recorded_responsible_department": row.responsible_dept,
                "due_date": row.due_date,
                "recorded_completed_date": row.completed_date,
                "recorded_effect_evaluation": row.effect_evaluation,
                "created_at": row.create_time,
                "updated_at": row.update_time,
                "verification_status": "not_recorded",
                "definition_note": "这些字段为分析人员已保存陈述；原表没有调查证据核验或根因审批状态。PDCA阶段、责任科室名称和完成日期不证明因果关系、个人责任或改进效果；原时间线为文本，不推导不存在的时间戳",
            },
            row.update_time or row.create_time,
        )
        for row in rows[:6]
    ]
    if len(rows) > 6:
        bundle.data["truncated_sources"].append({"source": "incident_rca_records", "limit": 6, "note": "其余关联RCA未纳入，不代表没有其他调查记录"})
    bundle.data["missing_data"].append("尚无独立的事件发生时刻、就诊归属、证据核验或根因审批状态；须把上报陈述、已保存分析、候选假设与已证实事实分别说明，不自动定责或写回整改结论")
    if not rows:
        bundle.data["missing_data"].append("所选事件尚无已保存RCA，不据此编造根因、调查经过或已实施整改")
