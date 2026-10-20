"""Read saved pathway counters without inventing an item list or clinical outcome."""


def pathway_progress(completed, total):
    if any(value is not None and (type(value) is not int or value < 0) for value in (completed, total)):
        return {"counter_state": "invalid", "completion_rate": None, "counter_note": "原完成计数存在无效值，待核对"}
    if completed is None or total is None or total == 0:
        return {"counter_state": "unknown", "completion_rate": None, "counter_note": "完成或总节点数未完整记录；总数0不作已核验分母"}
    if completed > total:
        return {"counter_state": "invalid", "completion_rate": None, "counter_note": "已完成数超过原总数，待核对，不截断成100%"}
    return {"counter_state": "known", "completion_rate": round(completed / total * 100, 1), "counter_note": "仅原节点计数比例，不证明具体措施执行、疗效或出院适宜性"}
