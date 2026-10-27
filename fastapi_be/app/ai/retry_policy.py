"""Versioned retry configuration without database, network or environment access."""

from pydantic import BaseModel, Field, model_serializer


class ProviderRetrySnapshot(BaseModel):
    # Missing means the original single-attempt contract. Preserve original
    # serialized bytes; an explicitly frozen value1 is still serialized.
    max_attempts: int = Field(default=1, strict=True, ge=1, le=3)

    @model_serializer(mode="wrap")
    def original_retry_fields(self, handler):
        value = handler(self)
        if "max_attempts" not in self.model_fields_set:
            value.pop("max_attempts", None)
        return value


def configured_attempts(provider):
    value = provider.get("max_attempts", 1) if isinstance(provider, dict) else getattr(provider, "max_attempts", 1)
    # Unflushed legacy ORM/test providers have not applied their column default.
    if value is None:
        value = 1
    if type(value) is not int or not 1 <= value <= 3:
        raise ValueError("Provider max_attempts must be an integer between1and3")
    kind = provider.get("kind") if isinstance(provider, dict) else getattr(provider, "kind", None)
    return value if kind in {"chat", "responses"} else 1


def _original_single_attempt(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        result = {key: _original_single_attempt(item) for key, item in value.items()}
        if {"provider_id", "revision", "timeout_seconds"} <= result.keys() and type(result.get("max_attempts")) is int and result["max_attempts"] == 1:
            result.pop("max_attempts")
        return result
    if isinstance(value, (list, tuple)):
        return [_original_single_attempt(item) for item in value]
    return value


def retry_snapshots_equal(current, frozen):
    """Only missing retry policy and an actual integer1 have equal semantics."""
    return _original_single_attempt(current) == _original_single_attempt(frozen)


def retry_snapshot_hash_matches(current, frozen_hash, digest):
    # The original immutable receipt/hash is checked; it is never replaced.
    return digest(current) == frozen_hash or digest(_original_single_attempt(current)) == frozen_hash
