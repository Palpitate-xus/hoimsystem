"""Two explicit operational target adapters; free rule text remains private."""

from sqlalchemy import LargeBinary, cast, func

from app.ai import document_change_contract as c
from app.ai import risk_rule_profiles
from app.ai.models import AIRiskRuleProfile
from app.models import ClinicalPathway


class CaseBudget:
    """Bound raw SQL loads and incremental canonical proof construction.

    A reserved envelope covers root/governance/reference keys; the final whole
    object is checked again. The budget never truncates or silently drops roots.
    """

    def __init__(self, maximum=c.MAX_CASE_BYTES, reserve=65536):
        self.maximum = maximum
        self.used = reserve
        self.members = 0

    def check_raw(self, size, *, maximum=None):
        if size is None:
            size = 0
        if type(size) is not int or size < 0 or size > (self.maximum - self.used if maximum is None else min(maximum, self.maximum - self.used)):
            raise ValueError("The complete SQL original would exceed the remaining UTF8 case budget")

    def add(self, value, *, members=0):
        if type(members) is not int or members < 0 or self.members + members > c.MAX_MEMBERS:
            raise ValueError("All dependency collections share the one exact 8192 member limit")
        size = len(c.e.utf8(c.e.canonical_json(value))) + 2
        self.check_raw(size)
        self.used += size
        self.members += members


def sql_octets(column):
    # CAST(... AS BLOB/BINARY) makes SQLite length count UTF8 bytes as MySQL
    # octet_length does, without loading a TEXT/MEDIUMTEXT value into Python.
    return func.coalesce(func.length(cast(column, LargeBinary)), 0)


def _preflight(db, model, field, identifier, names, budget):
    values = [getattr(model, name) for name in names]
    with db.no_autoflush:
        row = db.query(getattr(model, field), *(sql_octets(value) for value in values)).filter(getattr(model, field) == identifier).with_for_update(read=True).one_or_none()
    if row is not None:
        budget.check_raw(sum(row[1:]), maximum=c.MAX_LINK_BYTES)
    return row is not None


def target_snapshot(db, reference, budget=None):
    budget = budget or CaseBudget()
    if reference.kind == "risk_rule_profile":
        model, key, names = AIRiskRuleProfile, "rule_profile_id", c.RISK_COLUMNS
    else:
        model, key, names = ClinicalPathway, "pathway_id", c.PATHWAY_COLUMNS
    if not _preflight(db, model, key, reference.target_id, names, budget):
        return c.TargetSnapshot(schema_version="document_change_target_snapshot_v1", target=reference, exists=False, columns=None, state="missing", state_reasons=["target_missing"])
    if reference.kind == "risk_rule_profile":
        # Every query in this helper is a current read. profile_detail itself
        # also uses FOR SHARE rather than overwriting the row from an old RR view.
        with db.no_autoflush:
            checked = risk_rule_profiles.profile_detail(db, reference.target_id, locking=True)
    with db.no_autoflush:
        row = db.query(model).filter(getattr(model, key) == reference.target_id).populate_existing().with_for_update(read=True).one()
    columns = {name: getattr(row, name) for name in names}
    for name in ("created_at", "published_at", "revoked_at") if reference.kind == "risk_rule_profile" else ("create_time",):
        if columns[name] is not None:
            columns[name] = str(columns[name])
    reasons = []
    if reference.kind == "risk_rule_profile":
        if checked["status"] != "published":
            reasons.append("target_inactive")
        if not checked["implementation_current"]:
            reasons.append("profile_implementation_changed")
        state = "stale" if "profile_implementation_changed" in reasons else "inactive" if reasons else "current"
    elif type(row.source_revision) is not int or row.source_revision < 1 or type(row.status) is not int or row.status not in (0, 1):
        state, reasons = "unknown", ["target_state_unknown"]
    elif row.status == 1:
        state, reasons = "inactive", ["target_inactive"]
    else:
        state = "current"
    result = c.TargetSnapshot(schema_version="document_change_target_snapshot_v1", target=reference, exists=True, columns=columns, state=state, state_reasons=reasons)
    c.byte_bound(result, c.MAX_LINK_BYTES)
    return result
