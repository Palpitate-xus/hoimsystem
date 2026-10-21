"""Actual committed SQL dispatch -> HTTP fault -> exact paid uncertainty.

Controlled provider/service errors are not evidence of an unbilled call. These
cases preserve the old full-suite ledger and reproduce its uncovered boundary.
"""

import pytest

from app.ai import rca_evidence_execution as execution
from app.ai import rca_evidence_gateway as gateway
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunResult
from app.config import settings
from app.models import User
from tests.test_ai_rca_evidence_execution import provider_service, setup
from tests.test_ai_rca_evidence_grants import cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case


@pytest.fixture(autouse=True)
def synthetic_host(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("layer", ["gateway", "worker"])
@pytest.mark.parametrize("error_type", [RuntimeError, AssertionError])
async def test_unclassified_actual_http_error_after_own_committed_dispatch_preserves_unknown_paid_receipt_source_loss_no_body_and_no_replay(grant_case, monkeypatch, layer, error_type):
    identifier, lease, owner, value, factory, active, state, reads = setup(grant_case)

    async def reply(body):
        with factory() as db:
            actor = db.get(User, owner)
            original = grants.grant_detail(db, actor, value.binding.event_grant.grant_id)
            grants.revoke_grant(db, actor, original.identity.grant_id, cas(original))
            db.commit()
        state["authority_lost"] = True
        assert active == []
        if layer == "gateway":
            raise error_type("controlled unexpected exception during the real local ASGI request")
        return body

    transport, calls = provider_service("chat", reply, active)
    if layer == "worker":
        actual_gateway = execution.generate_rca_evidence

        async def lost_typed_receipt(*args, **kwargs):
            await actual_gateway(*args, **kwargs)
            raise error_type("controlled loss of the typed receipt after an actual HTTP reply")

        monkeypatch.setattr(execution, "generate_rca_evidence", lost_typed_receipt)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1 and not active and not reads
    with factory() as db:
        header = receipts.technical_header(db, identifier)
        recorded = receipts.read_receipt(db, header)
        assert recorded.status == "failed"
        assert recorded.usage.input_tokens is None and recorded.usage.output_tokens is None
        assert recorded.usage.complete is False
        assert recorded.usage.model_call_attempted is (True if layer == "gateway" else None)
        assert header.artifact["dispatch_event_id"] is not None and header.artifact["usage_event_id"] is not None
        assert len({header.artifact[key] for key in ("create_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")}) == 4
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0
        original_usage_pk = header.artifact["usage_event_id"]
    # A repeated queue delivery cannot replay HTTP, reauthorize revoked Source
    # or replace this original concrete usage PK with an invented zero receipt.
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1 and not active and not reads
    with factory() as db:
        current = receipts.technical_header(db, identifier)
        assert current.artifact["usage_event_id"] == original_usage_pk


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, AssertionError])
async def test_unexpected_gateway_failure_before_http_is_typed_known_uncalled_not_worker_unknown(grant_case, monkeypatch, error_type):
    identifier, lease, _owner, _value, factory, active, _state, reads = setup(grant_case)

    def unavailable_credential(_provider):
        raise error_type("controlled unexpected failure before any provider HTTP")

    monkeypatch.setattr(gateway, "provider_credential", unavailable_credential)
    transport, calls = provider_service("chat", None, active)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert not calls and not active and not reads
    with factory() as db:
        header = receipts.technical_header(db, identifier)
        recorded = receipts.read_receipt(db, header)
        assert recorded.status == "failed" and recorded.error_code == "RCA_PROVIDER_ERROR"
        assert recorded.usage.model_call_attempted is False
        assert (recorded.usage.input_tokens, recorded.usage.output_tokens) == (0, 0)
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0
