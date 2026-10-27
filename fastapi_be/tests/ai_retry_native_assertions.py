"""Controlled transient delivery and immutable synthetic business-row evidence."""

import hashlib
import json

import httpx

from app.models import Base


class RecoverAfterTwoFailures(httpx.AsyncBaseTransport):
    def __init__(self, final):
        self.final = final
        self.attempts = 0

    async def handle_async_request(self, request):
        self.attempts += 1
        if self.attempts <= 2:
            return httpx.Response(503, content=b"synthetic-temporary-failure")
        return await self.final.handle_async_request(request)

    async def aclose(self):
        await self.final.aclose()


def business_fingerprint(db):
    """Hash actual business rows; independently append-only request audit is allowed."""
    rows = {
        table.name: [tuple(row) for row in db.execute(table.select().order_by(*table.primary_key.columns)).all()]
        for table in sorted(Base.metadata.tables.values(), key=lambda table: table.name)
        if not table.name.startswith("hoimsystem_ai_") and table.name != "hoimsystem_operation_log"
    }
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def assert_unknown(receipt):
    if hasattr(receipt, "model_dump"):
        receipt = receipt.model_dump(mode="json")
    assert receipt["input_tokens"] is receipt["output_tokens"] is None
    assert receipt["model_call_attempted"] is True
    if "complete" in receipt:
        assert receipt["complete"] is False
