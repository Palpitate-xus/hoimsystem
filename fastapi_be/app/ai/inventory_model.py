"""Exact day-ledger comparison of declared indivisible purchase plans; no data access."""

import hashlib
from fractions import Fraction
from pathlib import Path

from app.ai.inventory_contract import (
    MAX_BYTES,
    MAX_INTEGER_BITS,
    MAX_WORK_UNITS,
    InventoryAnalysis,
    InventoryRuntime,
    InventorySource,
    SourceBinding,
    canonical_json,
    day_bounds,
    hash_content,
    input_policy_digest,
    rational,
    recipe_digest,
)

RUNTIME_FILES = ("inventory_contract", "inventory_model", "inventory_config", "inventory_server")
SCALE = 1000000


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest() for name in RUNTIME_FILES}


class Budget:
    """Bound integer operations and retained proof fragments before growing lists."""

    def __init__(self, max_work=MAX_WORK_UNITS, max_bytes=MAX_BYTES):
        self.work = self.bytes = 0
        self.max_work, self.max_bytes = max_work, max_bytes

    def tick(self, count=1):
        self.work += count
        if self.work > self.max_work:
            raise ValueError("Inventory comparison exceeds deterministic work budget; no partial proof")

    def integer(self, value):
        self.tick()
        if type(value) is not int or abs(value).bit_length() > MAX_INTEGER_BITS:
            raise ValueError("Exact inventory arithmetic exceeds integer bit budget")
        return value

    def add(self, a, b):
        return self.integer(a + b)

    def sub(self, a, b):
        return self.integer(a - b)

    def mul(self, a, b):
        if abs(a).bit_length() + abs(b).bit_length() > MAX_INTEGER_BITS:
            raise ValueError("Exact inventory multiplication exceeds intermediate bit budget")
        return self.integer(a * b)

    def sum(self, values):
        value = 0
        for item in values:
            value = self.add(value, item)
        return value

    def exact(self, value, scale=SCALE):
        self.integer(value)
        return rational(Fraction(value, scale))

    def record(self, value):
        encoded = canonical_json(value).encode()
        self.tick(1 + len(encoded) // 16)
        self.bytes += len(encoded) + 2
        if self.bytes > self.max_bytes:
            raise ValueError("Inventory proof fragments exceed UTF8 construction budget; no truncation")
        return value

    def digest_rows(self, rows):
        # Incremental canonical-array hash: never retain a whole repeated lot
        # state or allocate its full serialization merely to compute its SHA.
        digest, size, first = hashlib.sha256(), 2, True
        digest.update(b"[")
        for row in rows:
            encoded = canonical_json(row).encode()
            size += len(encoded) + (not first)
            self.tick(1 + len(encoded) // 16)
            if size > self.max_bytes:
                raise ValueError("Complete inventory state hash stream exceeds UTF8 bound")
            if not first:
                digest.update(b",")
            digest.update(encoded)
            first = False
        digest.update(b"]")
        return digest.hexdigest()


def validate_runtime(runtime):
    values = InventoryRuntime.model_validate(runtime.model_dump() if isinstance(runtime, InventoryRuntime) else runtime).model_dump()
    if values["core_sha256"] != implementation_hashes() or values["recipe_digest"] != recipe_digest() or values["input_policy_digest"] != input_policy_digest():
        raise ValueError("Inventory runtime implementation or fixed policy differs")
    identity = {key: value for key, value in values.items() if key not in {"runtime_digest", "model_version"}}
    digest = hash_content(identity)
    if values["runtime_digest"] != digest or values["model_version"] != "inventory:" + digest:
        raise ValueError("Registered inventory model and complete runtime descriptor differ")
    return values


def _atoms(amount, unit, dimension, reasons, budget):
    budget.tick()
    if amount.unit_review != "confirmed" or amount.unit_token is None:
        reasons.add(dimension + "_unit_unknown")
        return None
    if amount.unit_token != unit:
        reasons.add(dimension + "_unit_mismatch")
        return None
    if amount.value is None:
        reasons.add("unknown_cost" if dimension == "cost" else "unknown_quantity")
        return None
    value = amount.value
    negative = value.startswith("-")
    whole, _, fraction = value.lstrip("-").partition(".")
    result = budget.integer(int(whole) * SCALE + int(fraction.ljust(6, "0")))
    if negative:
        result = -result
    if result < 0:
        reasons.add("invalid_original_inventory_quantity")
        return None
    return result


def _review(review, reason, reasons):
    if review != "confirmed":
        reasons.add(reason)


def _lot_values(lot, source, reasons, budget):
    quantity = _atoms(lot.quantity, source.quantity_unit_token, "quantity", reasons, budget)
    frozen = _atoms(lot.frozen_quantity, source.quantity_unit_token, "quantity", reasons, budget)
    _review(lot.expiry_review, "expiry_review_not_confirmed", reasons)
    _review(lot.frozen_review, "frozen_review_not_confirmed", reasons)
    if frozen is None:
        reasons.add("unknown_frozen_quantity")
    if lot.valid_through.absent_reason == "unknown":
        reasons.add("unknown_expiry")
    if quantity is not None and frozen is not None and frozen > quantity:
        reasons.add("frozen_exceeds_quantity")
    return {"lot_id": lot.lot_id, "quantity": quantity, "frozen": frozen, "expiry": lot.valid_through.value}


def _opening(source, budget):
    observation, reasons = source.observation, set()
    if observation.method != "independent_count":
        reasons.add("opening_not_independently_observed")
    _review(observation.professional_review, "professional_review_not_confirmed", reasons)
    _review(observation.scope_review, "scope_not_confirmed", reasons)
    if observation.coverage != "attested_complete":
        reasons.add("coverage_incomplete" if observation.coverage == "incomplete" else "coverage_unknown")
    _review(observation.physical_reconciliation, "physical_reconciliation_unknown", reasons)
    legacy = observation.legacy_snapshot
    _review(legacy.reconciliation, "legacy_reconciliation_unknown", reasons)
    lots = [_lot_values(lot, source, reasons, budget) for lot in observation.lots]
    declared = _atoms(observation.declared_total_quantity, source.quantity_unit_token, "quantity", reasons, budget)
    catalog = _atoms(legacy.catalog_quantity, source.quantity_unit_token, "quantity", reasons, budget)
    totals = [declared, catalog]
    if legacy.batch_applicability == "applicable":
        totals.append(_atoms(legacy.batch_quantity_sum, source.quantity_unit_token, "quantity", reasons, budget))
    elif legacy.batch_applicability == "unknown":
        reasons.add("legacy_batch_applicability_unknown")
    if any(value is None for value in totals):
        reasons.add("legacy_quantity_unknown")
    if len({value for value in totals if value is not None}) > 1:
        reasons.add("initial_total_conflict")
    if all(lot["quantity"] is not None for lot in lots):
        actual = budget.sum(lot["quantity"] for lot in lots)
        if any(value is not None and value != actual for value in totals):
            reasons.add("initial_total_conflict")
    return lots, reasons


def _constraint(rule, source, dimension, reasons, budget):
    if rule.mode == "not_applicable":
        return None
    if rule.mode == "unknown":
        reasons.add("unknown_constraint")
        return None
    return _atoms(rule.amount, source.cost_unit_token if dimension == "cost" else source.quantity_unit_token, dimension, reasons, budget)


def _scenario(source, budget):
    scenario, reasons, rule_reasons, days = source.scenario, set(), set(), []
    _review(scenario.scope_review, "scope_not_confirmed", reasons)
    _review(scenario.policy.policy_review, "policy_not_confirmed", reasons)
    if scenario.coverage != "attested_complete":
        reasons.add("coverage_incomplete" if scenario.coverage == "incomplete" else "coverage_unknown")
    for name, reason in [
        ("opening_carry_forward", "opening_carry_forward_not_confirmed"),
        ("no_other_inventory_changes", "other_changes_not_confirmed"),
        ("frozen_quantities_unchanged", "frozen_continuation_not_confirmed"),
    ]:
        _review(getattr(scenario.assumptions, name), reason, reasons)
    for day in scenario.days:
        budget.tick()
        required = _atoms(day.required_quantity, source.quantity_unit_token, "quantity", reasons, budget)
        minimum = _constraint(day.minimum_end_usable, source, "quantity", rule_reasons, budget)
        maximum = _constraint(day.maximum_end_total, source, "quantity", rule_reasons, budget)
        days.append((day.date, required, minimum, maximum))
    return days, reasons, rule_reasons


def _plan(source, candidate, budget):
    operational, cost_reasons, lots, known_terms = set(), set(), [], []
    if candidate.completeness != "attested_complete":
        operational.add("candidate_incomplete")
        cost_reasons.add("candidate_incomplete")
    fee = _atoms(candidate.plan_fixed_fee, source.cost_unit_token, "cost", cost_reasons, budget)
    if fee is not None:
        known_terms.append(budget.mul(fee, SCALE))
    quantities = []
    for order in candidate.orders:
        budget.tick()
        fee = _atoms(order.order_fixed_fee, source.cost_unit_token, "cost", cost_reasons, budget)
        if fee is not None:
            known_terms.append(budget.mul(fee, SCALE))
        for line in order.lines:
            budget.tick()
            values = _lot_values(line, source, operational, budget)
            if line.arrival_date.value is None:
                operational.add("unknown_arrival")
            values["arrival"] = line.arrival_date.value
            lots.append(values)
            quantities.append(values["quantity"])
            # Pricing has its own quantity-unit check: it must remain unknown
            # even when inventory simulation is blocked by another raw fact.
            price = _atoms(line.unit_price, source.cost_unit_token, "cost", cost_reasons, budget)
            _review(line.price_basis_review, "price_basis_not_confirmed", cost_reasons)
            if values["quantity"] is None:
                cost_reasons.add("unknown_cost")
            if price is not None and values["quantity"] is not None and line.price_basis_review == "confirmed":
                known_terms.append(budget.mul(values["quantity"], price))
    subtotal = budget.sum(known_terms) if known_terms else None
    cost = subtotal if not cost_reasons else None
    ordered = budget.sum(quantities) if candidate.completeness == "attested_complete" and all(value is not None for value in quantities) else None
    return lots, operational, cost_reasons, cost, subtotal, ordered


def _violation(code, day, actual, limit, budget, cost=False):
    scale = SCALE * SCALE if cost else SCALE
    return budget.record({"code": code, "date": day, "actual": budget.exact(actual, scale), "limit": budget.exact(limit, scale)})


def _simulate(source, opening, receipts, days, budget):
    # Mutable balances belong only to this candidate. All original facts remain
    # unchanged, including zero stock, expired originals and frozen portions.
    balances = [{**row, "quantity": row["quantity"], "frozen": row["frozen"]} for row in opening]
    budget.tick(len(balances))
    arrivals = {}
    for row in receipts:
        budget.tick()
        arrivals.setdefault(row["arrival"], []).append(row)
    violations, daily = [], []
    received_total = fulfilled_total = unmet_total = expired_total = 0
    for day, required, minimum, maximum in days:
        budget.tick()
        start, end = day_bounds(day, source.timezone)
        opening_total = budget.sum(row["quantity"] for row in balances)
        expired_lots, allocations = [], []
        expired = 0
        for row in balances:
            budget.tick()
            if row["quantity"] and row["expiry"] is not None and row["expiry"] < day:
                expired = budget.add(expired, row["quantity"])
                expired_lots.append(budget.record({"lot_id": row["lot_id"], "quantity": budget.exact(row["quantity"])}))
                row["quantity"] = row["frozen"] = 0
        arrived = 0
        received_ids = []
        for original in arrivals.get(day, []):
            budget.tick()
            row = dict(original)
            arrived = budget.add(arrived, row["quantity"])
            received_ids.append(row["lot_id"])
            budget.record(row["lot_id"])
            if row["quantity"] and row["expiry"] is not None and row["expiry"] < day:
                expired = budget.add(expired, row["quantity"])
                expired_lots.append(budget.record({"lot_id": row["lot_id"], "quantity": budget.exact(row["quantity"])}))
                row["quantity"] = row["frozen"] = 0
            balances.append(row)
        # Explicit deterministic upper charge for a comparison sort of bounded
        # primitive expiry/UUID keys, in addition to each visited lot.
        budget.tick(len(balances) * (len(balances).bit_length() + 1))
        ordered = sorted(balances, key=lambda row: (row["expiry"] is None, row["expiry"] or "", row["lot_id"]))
        unmet = required
        for row in ordered:
            budget.tick()
            usable = budget.sub(row["quantity"], row["frozen"])
            taken = min(unmet, usable)
            if taken:
                row["quantity"] = budget.sub(row["quantity"], taken)
                unmet = budget.sub(unmet, taken)
                allocations.append(budget.record({"lot_id": row["lot_id"], "quantity": budget.exact(taken)}))
            if not unmet:
                break
        total = budget.sum(row["quantity"] for row in balances)
        frozen = budget.sum(row["frozen"] for row in balances)
        usable = budget.sub(total, frozen)
        allocated = budget.sub(required, unmet)
        if budget.add(opening_total, arrived) != budget.add(budget.add(allocated, expired), total) or total != budget.add(usable, frozen):
            raise ValueError("Exact inventory ledger conservation failed")
        if unmet:
            violations.append(_violation("unmet_scenario_quantity", day, unmet, 0, budget))
        if minimum is not None and usable < minimum:
            violations.append(_violation("minimum_usable_not_met", day, usable, minimum, budget))
        if maximum is not None and total > maximum:
            violations.append(_violation("maximum_total_exceeded", day, total, maximum, budget))
        received_total = budget.add(received_total, arrived)
        fulfilled_total = budget.add(fulfilled_total, allocated)
        unmet_total = budget.add(unmet_total, unmet)
        expired_total = budget.add(expired_total, expired)
        # Canonical state order is lot UUID, independent of FEFO or input order.
        budget.tick(len(balances) * (len(balances).bit_length() + 1))
        state_digest = budget.digest_rows(
            {"lot_id": row["lot_id"], "quantity": budget.exact(row["quantity"]), "frozen_quantity": budget.exact(row["frozen"])} for row in sorted(balances, key=lambda row: row["lot_id"])
        )
        scalar = {
            "date": day,
            "day_start_at": start,
            "day_end_at": end,
            "opening_total": budget.exact(opening_total),
            "arrived": budget.exact(arrived),
            "expired": budget.exact(expired),
            "allocated": budget.exact(allocated),
            "unmet": budget.exact(unmet),
            "closing_total": budget.exact(total),
            "closing_usable": budget.exact(usable),
            "closing_frozen": budget.exact(frozen),
            "lot_state_digest": state_digest,
        }
        budget.record(scalar)
        daily.append({**scalar, "allocations": allocations, "expired_lots": expired_lots, "received_lot_ids": received_ids})
    terminal = []
    for row in sorted(balances, key=lambda row: row["lot_id"]):
        terminal.append(budget.record({"lot_id": row["lot_id"], "quantity": budget.exact(row["quantity"]), "frozen_quantity": budget.exact(row["frozen"])}))
    totals = {
        "received": budget.exact(received_total),
        "fulfilled": budget.exact(fulfilled_total),
        "unmet": budget.exact(unmet_total),
        "expired": budget.exact(expired_total),
        "ending_total": daily[-1]["closing_total"],
        "ending_usable": daily[-1]["closing_usable"],
        "ending_frozen": daily[-1]["closing_frozen"],
    }
    return daily, terminal, violations, totals


def _candidate(source, candidate, opening, opening_reasons, days, scenario_reasons, rule_reasons, budget):
    receipts, operational, cost_reasons, cost, subtotal, ordered = _plan(source, candidate, budget)
    ledger_reasons = opening_reasons | scenario_reasons | operational
    violations, daily, terminal = [], None, None
    totals = {key: None for key in ("ordered", "received", "fulfilled", "unmet", "expired", "ending_total", "ending_usable", "ending_frozen")}
    totals["ordered"] = budget.exact(ordered) if ordered is not None else None
    if not ledger_reasons:
        daily, terminal, violations, ledger_totals = _simulate(source, opening, receipts, days, budget)
        totals.update(ledger_totals)
    inventory_status = "unknown" if ledger_reasons or rule_reasons else ("infeasible" if violations else "feasible")
    budget_reasons = set()
    limit = _constraint(source.scenario.budget, source, "cost", budget_reasons, budget)
    if source.scenario.budget.mode == "not_applicable":
        budget_status = "not_applicable"
    elif cost is None or budget_reasons:
        budget_status = "unknown"
    elif cost > budget.mul(limit, SCALE):
        budget_status = "violated"
        violations.append(_violation("budget_exceeded", None, cost, budget.mul(limit, SCALE), budget, True))
    else:
        budget_status = "satisfied"
    reasons = ledger_reasons | rule_reasons | cost_reasons | budget_reasons
    status = "unknown" if reasons or inventory_status == "unknown" or cost is None or budget_status == "unknown" else ("infeasible" if violations else "feasible")
    result = {
        "candidate_id": candidate.candidate_id,
        "source_ref": candidate.ref.model_dump(),
        "status": status,
        "inventory_status": inventory_status,
        "cost_status": "known" if cost is not None else "unknown",
        "budget_status": budget_status,
        "total_cost": budget.exact(cost, SCALE * SCALE) if cost is not None else None,
        "known_cost_subtotal": budget.exact(subtotal, SCALE * SCALE) if subtotal is not None else None,
        "reasons": sorted(reasons),
        "violations": violations,
        "daily": daily,
        "terminal_lots": terminal,
        "totals": totals,
    }
    budget.record({key: value for key, value in result.items() if key not in {"daily", "terminal_lots", "violations"}})
    return result


def compute_inventory(source, instructions_digest, runtime):
    source = InventorySource.model_validate(source.model_dump() if isinstance(source, InventorySource) else source)
    runtime = validate_runtime(runtime)
    budget = Budget()
    public = source.model_dump()
    # Account for complete input traversal/reference validation, in addition to
    # hard parser/byte/member caps applied before the native computation.
    budget.tick(len(canonical_json(public).encode()) // 16 + len(source.member_manifest))
    binding = {key: getattr(source, key) for key in SourceBinding.model_fields if key != "projection_hash"}
    binding["projection_hash"] = hash_content(public)
    opening, opening_reasons = _opening(source, budget)
    days, scenario_reasons, rule_reasons = _scenario(source, budget)
    results = []
    for candidate in source.candidates:
        result = _candidate(source, candidate, opening, opening_reasons, days, scenario_reasons, rule_reasons, budget)
        results.append(result)
    feasible = [row for row in results if row["status"] == "feasible"]
    cost = min((Fraction(int(row["total_cost"]["numerator"]), int(row["total_cost"]["denominator"])) for row in feasible), default=None)
    best = [row["candidate_id"] for row in feasible if Fraction(int(row["total_cost"]["numerator"]), int(row["total_cost"]["denominator"])) == cost]
    unknown = sum(row["status"] == "unknown" for row in results)
    closed = not unknown and source.candidate_set_review == "confirmed"
    value = {
        "schema_version": "inventory_analysis_v1",
        "source_binding": binding,
        "rule_id": source.rule_id,
        "recipe_digest": recipe_digest(),
        "input_policy_digest": input_policy_digest(),
        "instructions_digest": instructions_digest,
        "local_runtime": runtime,
        "scope": "declared_finite_candidate_set",
        "status": "complete_comparison" if closed else ("candidate_set_unknown" if source.candidate_set_review != "confirmed" else "input_unknown"),
        "candidate_results": results,
        "best_known_feasible_candidate_ids": best,
        "best_known_feasible_cost": rational(cost) if cost is not None else None,
        "best_among_declared_candidates": bool(closed and best),
        "all_declared_candidates_proven_infeasible": bool(closed and not best),
        "candidate_count": len(results),
        "known_feasible_count": len(feasible),
        "known_infeasible_count": sum(row["status"] == "infeasible" for row in results),
        "unknown_count": unknown,
        "automatically_selected_candidate": None,
        "projection_only": True,
        "work_units": budget.work,
    }
    if len(canonical_json(value).encode()) > MAX_BYTES:
        raise ValueError("Complete exact inventory analysis exceeds UTF8 bound; no truncation")
    return InventoryAnalysis.model_validate(value)


def validate_analysis_binding(analysis, source, instructions_digest, model_version):
    analysis = InventoryAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, InventoryAnalysis) else analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("Registered inventory model differs from native analysis")
    expected = compute_inventory(source, instructions_digest, analysis.local_runtime)
    if analysis.model_dump() != expected.model_dump():
        raise ValueError("Complete inventory original, simulation, candidate set or proof differs")
    return analysis


def generation_result_for_analysis(analysis):
    analysis = InventoryAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, InventoryAnalysis) else analysis)
    if analysis.best_among_declared_candidates:
        summary = f"已完整比较{analysis.candidate_count}个声明方案，列出其中采购成本最低的可行方案及全部并列项。"
    elif analysis.all_declared_candidates_proven_infeasible:
        summary = f"已完整核对{analysis.candidate_count}个声明方案；该有限集合内没有满足全部声明约束的方案。"
    else:
        summary = f"已核对{analysis.candidate_count}个声明方案；候选或范围存在未知项，不能证明整个声明集合的最优或不可行。"
    return {
        "summary": summary,
        "sections": [
            {"title": "核对范围", "source_ids": [analysis.source_binding.source_id], "content": "单品种、单物理范围、明确单位与受审未来情景；逐个比较不可拆分的完整采购候选。"},
            {"title": "库存与成本", "source_ids": [], "content": "按受审日事件顺序与FEFO逐日守恒，冻结量不可分配，过期移除仅为情景账；成本仅包含明确的采购单价及固定费。"},
        ],
        "warnings": ["结果只适用于明确列出的候选集合，不证明所有可能采购组合的全局最优。", "未来数量是受审情景，不代表潜在需求；不执行采购、调拨、报损或库存写入，也未提供运营效果验证。"],
        "missing_data": [f"{row.candidate_id}:input_unknown" for row in analysis.candidate_results if row.status == "unknown"]
        + (["declared_candidate_set_not_confirmed"] if analysis.status == "candidate_set_unknown" else []),
    }
