"""Complete nullable usage aggregates from an unlocked, fresh admin snapshot."""

from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.ai.admin_read_snapshot import admin_read_snapshot
from app.ai.admin_task_directory import DOMAIN_FEATURES
from app.ai.admin_usage_receipts import artifact_headers, checked_usage, receipt_bodies, receipt_fk
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIRun
from app.ai.native_task_routing import _domains

PAGE_SIZE = 200
RUN_FIELDS = ("run_id", "feature_key", "requested_by", "status", "lease_token", "error_code", "latency_ms", "start_time", "finish_time", "input_tokens", "output_tokens")


@dataclass
class UsageGroup:
    feature_key: str | None
    status: str
    count: int = 0
    states: dict = field(default_factory=lambda: dict(recorded=0, pending=0, invalid=0, unverified=0))
    known: dict = field(default_factory=lambda: dict(input_tokens=0, output_tokens=0))
    known_count: dict = field(default_factory=lambda: dict(input_tokens=0, output_tokens=0))
    attempts: dict = field(default_factory=lambda: dict(attempted=0, unattempted=0, unknown=0))
    local_count: int = 0
    local_attempted: int = 0
    local_unattempted: int = 0
    local_unknown: int = 0
    local_ms: int = 0
    local_ms_count: int = 0

    def add(self, state, usage=None, *, local=False):
        self.count += 1
        self.states[state] += 1
        usage = usage or {}
        for key in self.known:
            if usage.get(key) is not None:
                self.known[key] += usage[key]
                self.known_count[key] += 1
        attempt = usage.get("model_call_attempted")
        self.attempts["attempted" if attempt is True else "unattempted" if attempt is False else "unknown"] += 1
        if local:
            self.local_count += 1
            calculation = usage.get("calculation_attempted")
            if calculation is True:
                self.local_attempted += 1
            elif calculation is False:
                self.local_unattempted += 1
            else:
                self.local_unknown += 1
            if usage.get("calculation_ms") is not None:
                self.local_ms += usage["calculation_ms"]
                self.local_ms_count += 1

    def output(self):
        value = {"feature_key": self.feature_key, "status": self.status, "count": self.count}
        value.update({name + "_count": count for name, count in self.states.items()})
        for key in self.known:
            value[key] = self.known[key] if self.known_count[key] == self.count else None
            value[key + "_known_sum"] = self.known[key]
            value[key + "_known_count"] = self.known_count[key]
            value[key + "_unknown_count"] = self.count - self.known_count[key]
        value.update({"model_call_" + name + "_count": count for name, count in self.attempts.items()})
        value.update(
            local_calculation_count=self.local_count,
            local_calculation_attempted_count=self.local_attempted,
            local_calculation_unattempted_count=self.local_unattempted,
            local_calculation_unknown_count=self.local_unknown,
            local_calculation_ms_known_sum=self.local_ms,
            local_calculation_ms_known_count=self.local_ms_count,
        )
        return value


def _pending(run):
    if run["latency_ms"] is not None or (run["input_tokens"], run["output_tokens"]) != (0, 0):
        return False
    if run["status"] == "queued":
        return all(run[key] is None for key in ("lease_token", "start_time", "finish_time", "error_code"))
    if run["status"] == "running":
        return run["lease_token"] is not None and run["start_time"] is not None and run["finish_time"] is None and run["error_code"] is None
    return run["status"] == "cancelled" and all(run[key] is not None for key in ("lease_token", "start_time", "finish_time")) and run["error_code"] == "TASK_CANCELLED"


def usage_summary(db, user):
    """Unknown is independent for input/output; no legacy SUM is authoritative.

    The scope is exact usage-event accounting. Private Source/result integrity
    remains checked only by the original purpose-authorized domain readers.
    Keyset pages cover every task in the same snapshot, without a silent cap.
    """
    groups, scanned, last = {}, 0, None
    domains = _domains()
    with admin_read_snapshot(db, user) as snapshot:
        total = snapshot.scalar(select(func.count()).select_from(AIRun))
        while True:
            statement = select(*(getattr(AIRun, key) for key in RUN_FIELDS)).order_by(AIRun.run_id).limit(PAGE_SIZE)
            if last is not None:
                statement = statement.where(AIRun.run_id > last)
            runs = snapshot.execute(statement).mappings().all()
            if not runs:
                break
            anchors = artifact_headers(snapshot, [run["run_id"] for run in runs], domains)
            candidates = []
            for run in runs:
                found = anchors.get(run["run_id"], [])
                if len(found) == 1:
                    domain, artifact = found[0]
                    if artifact["run_id"] == run["run_id"] and type(run["requested_by"]) is int and run["requested_by"] > 0 and artifact["requested_by"] == run["requested_by"]:
                        candidates.append((run, domain, artifact))
            bodies = receipt_bodies(snapshot, candidates)
            eligible = {run["run_id"]: (domain, artifact) for run, domain, artifact in candidates}
            for run in runs:
                found = anchors.get(run["run_id"], [])
                feature = DOMAIN_FEATURES[found[0][0]] if len(found) == 1 else run["feature_key"] if not found and run["feature_key"] in FEATURE_BY_KEY else None
                status = run["status"] if run["status"] in {"queued", "running", "succeeded", "failed", "cancelled"} else "invalid"
                group = groups.setdefault((feature, status), UsageGroup(feature, status))
                usage, state = None, "invalid" if found else "unverified"
                entry = eligible.get(run["run_id"])
                if entry:
                    domain, artifact = entry
                    identifier = receipt_fk(domain, artifact)
                    if identifier is None and _pending(run):
                        state = "pending"
                    elif type(identifier) is int and identifier > 0:
                        raw = bodies.get((run["run_id"], domain))
                        if raw is not None:
                            try:
                                usage = checked_usage(run, domain, artifact, raw)
                                state = "recorded"
                            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                                pass
                group.add(state, usage, local=len(found) == 1 and found[0][0] == "infection")
            scanned += len(runs)
            last = runs[-1]["run_id"]
        if scanned != total:
            raise RuntimeError("The usage snapshot did not cover every actual task")
    return {
        "code": 200,
        "msg": "success",
        "schema_version": "global_ai_usage_summary_v2",
        "accounting_scope": "specific_usage_audit_record_without_source_or_result_content_validation",
        "coverage": {"total": total, "scanned": scanned, "complete": True},
        "data": [groups[key].output() for key in sorted(groups, key=lambda key: (key[0] or "", key[1]))],
    }
