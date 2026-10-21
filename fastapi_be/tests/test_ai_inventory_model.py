"""Hand ledgers and a separate per-quarter-unit event oracle for complete finite plans."""

import copy
import random
from fractions import Fraction

import pytest

from app.ai.inventory_config import runtime_descriptor, runtime_from_descriptor
from app.ai.inventory_contract import hash_content
from app.ai.inventory_model import Budget, compute_inventory, generation_result_for_analysis, validate_analysis_binding
from tests.test_ai_inventory_contract import amount, candidate, constraint, date_value, lot, make_source, receipt, refresh, uid


def analyze(source):
    return compute_inventory(source, "a" * 64, runtime_from_descriptor(runtime_descriptor()))


def exact(value):
    if hasattr(value, "fraction"):
        return value.fraction()
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def opening(source, lots):
    source["observation"]["lots"] = lots
    total = sum(Fraction(row["quantity"]["value"]) for row in lots)
    text = str(total.numerator // total.denominator) if total.denominator == 1 else format(float(total), ".6f").rstrip("0")
    source["observation"]["declared_total_quantity"] = amount(text)
    source["observation"]["legacy_snapshot"]["catalog_quantity"] = amount(text)
    source["observation"]["legacy_snapshot"]["batch_quantity_sum"] = amount(text)
    return source


def test_hand_cost_and_complete_day_balance_without_mutating_original():
    source = make_source()
    before = copy.deepcopy(source)
    analysis = analyze(source)
    row = analysis.candidate_results[0]
    assert source == before
    assert analysis.status == "complete_comparison" and analysis.best_among_declared_candidates
    assert exact(row.total_cost) == Fraction(5, 2)
    assert [exact(day.closing_total) for day in row.daily] == [3, 3, 1]
    for day in row.daily:
        assert exact(day.opening_total) + exact(day.arrived) == exact(day.allocated) + exact(day.expired) + exact(day.closing_total)
        assert exact(day.closing_total) == exact(day.closing_usable) + exact(day.closing_frozen)
    assert exact(row.totals.fulfilled) == 6 and exact(row.totals.received) == 2
    assert analysis.automatically_selected_candidate is None


def test_expiry_includes_its_date_frozen_never_allocated_and_expired_arrival_still_charged():
    source = make_source()
    opening(source, [lot("frozen", "3", "2", "2026-10-21")])
    source["candidates"][0]["orders"][0]["lines"] = [receipt(quantity="2", arrival="2026-10-21", expiry="2026-10-20", price="3")]
    analysis = analyze(source)
    result = analysis.candidate_results[0]
    assert exact(result.total_cost) == 6
    assert exact(result.daily[0].expired) == 2 and exact(result.daily[0].allocated) == 1
    assert exact(result.daily[0].closing_frozen) == 2
    assert exact(result.daily[1].expired) == 2
    assert exact(result.totals.unmet) == 5 and result.status == "infeasible"
    assert analysis.all_declared_candidates_proven_infeasible


def test_fefo_expiry_before_nonexpiring_and_uuid_tie_is_explicit():
    source = make_source()
    ids = sorted([uid("a"), uid("b")])
    lots = [lot("none", "2", "0", None), lot("a", "2", "0", "2026-10-25"), lot("b", "2", "0", "2026-10-25")]
    opening(source, lots)
    source["candidates"] = [candidate("none", [])]
    refresh(source)
    row = analyze(source).candidate_results[0]
    assert row.daily[0].allocations[0].lot_id == ids[0]
    assert row.daily[1].allocations[0].lot_id == ids[1]
    assert row.daily[2].allocations[0].lot_id == uid("none")


def test_all_tied_minima_and_unknown_candidate_prevents_whole_set_claim():
    source = make_source()
    source["candidates"] += [candidate("tie", [receipt("tie-receipt")]), candidate("unknown", [receipt("unknown-receipt", price=None)])]
    refresh(source)
    result = analyze(source)
    assert len(result.best_known_feasible_candidate_ids) == 2
    assert result.unknown_count == 1 and not result.best_among_declared_candidates
    assert not result.all_declared_candidates_proven_infeasible
    assert result.candidate_results[2].inventory_status == "feasible" and result.candidate_results[2].total_cost is None
    assert result.candidate_results[2].status == "unknown"


def test_explicit_zero_cost_budget_quantity_and_residual_constraints():
    source = make_source()
    source["candidates"] = [candidate("no-buy", [])]
    for day in source["scenario"]["days"]:
        day["required_quantity"] = amount("0.000000")
        day["minimum_end_usable"] = constraint("5")
        day["maximum_end_total"] = constraint("5")
    source["scenario"]["budget"] = constraint("0", True)
    refresh(source)
    result = analyze(source)
    row = result.candidate_results[0]
    assert row.status == "feasible" and row.budget_status == "satisfied"
    assert exact(row.total_cost) == 0 and exact(row.totals.ordered) == 0 and exact(row.totals.ending_total) == 5


def test_shared_budget_and_fixed_order_fees_charge_even_zero_quantity_orders():
    source = make_source()
    source["candidates"][0]["plan_fixed_fee"] = amount("1.25", True)
    source["candidates"][0]["orders"][0]["order_fixed_fee"] = amount("2.5", True)
    source["candidates"][0]["orders"][0]["lines"][0]["quantity"] = amount("0")
    source["scenario"]["budget"] = constraint("3.5", True)
    result = analyze(source).candidate_results[0]
    assert exact(result.total_cost) == Fraction(15, 4)
    assert result.budget_status == "violated" and result.status == "infeasible"
    assert any(v.code == "budget_exceeded" and exact(v.limit) == Fraction(7, 2) for v in result.violations)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("legacy_capture", "opening_not_independently_observed"),
        ("negative_legacy", "invalid_original_inventory_quantity"),
        ("legacy_conflict", "initial_total_conflict"),
        ("physical_conflict", "initial_total_conflict"),
        ("frozen_conflict", "frozen_exceeds_quantity"),
        ("stock_unknown", "unknown_quantity"),
        ("unit_mismatch", "quantity_unit_mismatch"),
        ("scenario_unknown", "unknown_quantity"),
        ("carry", "opening_carry_forward_not_confirmed"),
        ("price_unit", "cost_unit_mismatch"),
        ("arrival", "unknown_arrival"),
        ("expiry", "unknown_expiry"),
        ("policy", "policy_not_confirmed"),
        ("partial_plan", "candidate_incomplete"),
    ],
)
def test_unknown_facts_remain_unknown_without_losing_independent_cost(mutation, reason):
    source = make_source()
    obs = source["observation"]
    line = source["candidates"][0]["orders"][0]["lines"][0]
    if mutation == "legacy_capture":
        obs["method"] = "legacy_current_capture"
        obs["observed_at"] = None
    elif mutation == "negative_legacy":
        obs["legacy_snapshot"]["catalog_quantity"] = amount("-1")
    elif mutation == "legacy_conflict":
        obs["legacy_snapshot"]["catalog_quantity"] = amount("7")
    elif mutation == "physical_conflict":
        obs["declared_total_quantity"] = amount("4")
    elif mutation == "frozen_conflict":
        obs["lots"][0]["frozen_quantity"] = amount("7")
    elif mutation == "stock_unknown":
        obs["lots"][0]["quantity"] = amount(None)
    elif mutation == "unit_mismatch":
        obs["lots"][0]["quantity"]["unit_token"] = hash_content("a different unit")
    elif mutation == "scenario_unknown":
        source["scenario"]["days"][0]["required_quantity"] = amount(None)
    elif mutation == "carry":
        source["scenario"]["assumptions"]["opening_carry_forward"] = "unknown"
    elif mutation == "price_unit":
        line["unit_price"]["unit_token"] = hash_content("another currency")
    elif mutation == "arrival":
        line["arrival_date"] = date_value(None, "unknown")
    elif mutation == "expiry":
        line["valid_through"] = date_value(None, "unknown")
    elif mutation == "policy":
        source["scenario"]["policy"]["policy_review"] = "unknown"
    elif mutation == "partial_plan":
        source["candidates"][0]["completeness"] = "incomplete"
    result = analyze(source)
    row = result.candidate_results[0]
    assert row.status == "unknown" and reason in row.reasons
    assert result.unknown_count == 1 and not result.best_among_declared_candidates and not result.all_declared_candidates_proven_infeasible
    if mutation not in ("price_unit", "partial_plan"):
        assert exact(row.total_cost) == Fraction(5, 2)
    if mutation == "price_unit":
        assert row.inventory_status == "feasible" and row.total_cost is None
    elif mutation != "partial_plan":
        assert row.daily is None


def test_unknown_constraints_do_not_erase_actual_closed_inventory_ledger():
    source = make_source()
    source["scenario"]["days"][1]["maximum_end_total"] = constraint(mode="unknown")
    row = analyze(source).candidate_results[0]
    assert row.status == "unknown" and row.inventory_status == "unknown"
    assert row.daily is not None and len(row.daily) == 3 and exact(row.totals.fulfilled) == 6


def test_known_legacy_conflict_is_reported_even_when_physical_count_is_unknown():
    source = make_source()
    source["observation"]["lots"][0]["quantity"] = amount(None)
    source["observation"]["legacy_snapshot"]["batch_quantity_sum"] = amount("7")
    row = analyze(source).candidate_results[0]
    assert "initial_total_conflict" in row.reasons
    assert row.inventory_status == "unknown"


def test_incomplete_candidate_never_labels_partial_order_sum_as_whole_quantity():
    source = make_source()
    source["candidates"][0]["completeness"] = "incomplete"
    row = analyze(source).candidate_results[0]
    assert row.totals.ordered is None and row.total_cost is None
    assert row.known_cost_subtotal is not None


def test_unreviewed_candidate_set_is_not_a_closed_comparison():
    source = make_source()
    source["candidate_set_review"] = "unknown"
    result = analyze(source)
    assert result.status == "candidate_set_unknown" and not result.best_among_declared_candidates
    assert result.known_feasible_count == 1 and result.unknown_count == 0


def quarter_text(value):
    # Literal decimal fixtures: quarter-atom indices, not a production conversion.
    return str(value // 4) + ["", ".25", ".5", ".75"][value % 4]


def literal_quarter_oracle(source, plan):
    """Track each quarter-unit separately; no native lot arithmetic/helper reuse."""
    tokens = []

    def add(raw):
        count = int(Fraction(raw["quantity"]["value"]) * 4)
        blocked = int(Fraction(raw["frozen_quantity"]["value"]) * 4)
        return [{"lot": raw["lot_id"], "expiry": raw["valid_through"]["value"], "blocked": i < blocked} for i in range(count)]

    for raw in source["observation"]["lots"]:
        tokens += add(raw)
    days = []
    cost = Fraction(plan["plan_fixed_fee"]["value"])
    arrivals = {}
    for order in plan["orders"]:
        cost += Fraction(order["order_fixed_fee"]["value"])
        for raw in order["lines"]:
            cost += Fraction(raw["quantity"]["value"]) * Fraction(raw["unit_price"]["value"])
            arrivals.setdefault(raw["arrival_date"]["value"], []).append(raw)
    for day in source["scenario"]["days"]:
        before = len(tokens)
        tokens = [t for t in tokens if t["expiry"] is None or t["expiry"] >= day["date"]]
        expired = before - len(tokens)
        incoming = []
        for raw in arrivals.get(day["date"], []):
            incoming += add(raw)
        tokens += incoming
        good = [t for t in tokens if t["expiry"] is None or t["expiry"] >= day["date"]]
        expired += len(tokens) - len(good)
        tokens = good
        wanted = int(Fraction(day["required_quantity"]["value"]) * 4)
        available = sorted([t for t in tokens if not t["blocked"]], key=lambda t: (t["expiry"] is None, t["expiry"] or "", t["lot"]))
        taken = available[:wanted]
        # Multiset identity matters: tokens are physical separate objects.
        selected = {id(t) for t in taken}
        tokens = [t for t in tokens if id(t) not in selected]
        days.append(
            {
                "opening_total": Fraction(before, 4),
                "arrived": Fraction(len(incoming), 4),
                "expired": Fraction(expired, 4),
                "allocated": Fraction(len(taken), 4),
                "unmet": Fraction(wanted - len(taken), 4),
                "closing_total": Fraction(len(tokens), 4),
                "closing_frozen": Fraction(sum(t["blocked"] for t in tokens), 4),
                "closing_usable": Fraction(sum(not t["blocked"] for t in tokens), 4),
            }
        )
    return cost, days


@pytest.mark.parametrize("seed", range(24))
def test_every_day_and_cost_against_independent_discrete_physical_token_oracle(seed):
    rng = random.Random(seed)
    source = make_source()
    lots = [lot("start:" + str(i), quarter_text(n := rng.randrange(0, 13)), quarter_text(rng.randrange(n + 1)), rng.choice(["2026-10-20", "2026-10-21", "2026-10-23", None])) for i in range(2)]
    opening(source, lots)
    for day in source["scenario"]["days"]:
        day["required_quantity"] = amount(quarter_text(rng.randrange(0, 13)))
    plans = []
    for i in range(3):
        lines = [
            receipt(
                f"{seed}:{i}:{j}",
                quarter_text(n := rng.randrange(0, 13)),
                rng.choice(["2026-10-21", "2026-10-22", "2026-10-23"]),
                rng.choice(["2026-10-20", "2026-10-22", "2026-10-23", None]),
                quarter_text(rng.randrange(0, 13)),
            )
            for j in range(2)
        ]
        for line in lines:
            line["frozen_quantity"] = amount(quarter_text(rng.randrange(int(Fraction(line["quantity"]["value"]) * 4) + 1)))
        plan = candidate("plan:" + str(i), lines, quarter_text(rng.randrange(0, 8)))
        plan["orders"][0]["order_fixed_fee"] = amount(quarter_text(rng.randrange(0, 8)), True)
        plans.append(plan)
    source["candidates"] = plans
    refresh(source)
    result = analyze(source)
    feasible = []
    for raw, row in zip(plans, result.candidate_results, strict=True):
        expected_cost, expected_days = literal_quarter_oracle(source, raw)
        assert exact(row.total_cost) == expected_cost
        for actual, expected in zip(row.daily, expected_days, strict=True):
            for field, value in expected.items():
                assert exact(getattr(actual, field)) == value
        expected_feasible = all(day["unmet"] == 0 for day in expected_days)
        assert row.status == ("feasible" if expected_feasible else "infeasible")
        if expected_feasible:
            feasible.append((expected_cost, raw["candidate_id"]))
    best = min((value for value, _ in feasible), default=None)
    assert result.best_known_feasible_candidate_ids == [identifier for value, identifier in feasible if value == best]
    assert result.best_among_declared_candidates == bool(feasible)
    assert result.all_declared_candidates_proven_infeasible == (not bool(feasible))


@pytest.mark.parametrize("mutation", ["cost", "allocation", "state", "prompt", "membership", "runtime", "work"])
def test_full_proof_recomputation_rejects_tampering(mutation):
    source = make_source()
    result = analyze(source)
    value = result.model_dump()
    if mutation == "cost":
        value["candidate_results"][0]["total_cost"] = {"numerator": "0", "denominator": "1"}
    elif mutation == "allocation":
        value["candidate_results"][0]["daily"][0]["allocations"][0]["quantity"] = {"numerator": "0", "denominator": "1"}
    elif mutation == "state":
        value["candidate_results"][0]["daily"][0]["lot_state_digest"] = "f" * 64
    elif mutation == "prompt":
        value["instructions_digest"] = "b" * 64
    elif mutation == "membership":
        value["source_binding"]["projection_hash"] = "f" * 64
    elif mutation == "runtime":
        value["local_runtime"]["timezone_database_digest"] = "f" * 64
    elif mutation == "work":
        value["work_units"] += 1
    with pytest.raises(ValueError):
        validate_analysis_binding(value, source, "a" * 64, result.local_runtime.model_version)


def test_budget_bounds_stream_before_materializing_a_giant_state():
    visited = []

    def rows():
        for i in range(1000000):
            visited.append(i)
            yield {"lot_id": uid(i), "quantity": {"numerator": "0", "denominator": "1"}}

    with pytest.raises(ValueError, match="stream exceeds"):
        Budget(max_bytes=1000).digest_rows(rows())
    assert len(visited) < 20
    with pytest.raises(ValueError, match="work budget"):
        Budget(max_work=1).tick(2)


def test_fixed_explanation_does_not_choose_or_claim_undeclared_global_optimum():
    result = analyze(make_source())
    text = generation_result_for_analysis(result)
    assert "声明方案" in text["summary"]
    assert text["sections"][0]["source_ids"] == [result.source_binding.source_id]
    assert text["sections"][1]["source_ids"] == []
    assert any("不证明" in warning for warning in text["warnings"])
