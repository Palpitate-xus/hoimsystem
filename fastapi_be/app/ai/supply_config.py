"""Independent recorded supply statistics settings and reproducible runtime identity; no dotenv."""

import hashlib
import platform
from importlib.metadata import version
from pathlib import Path
from zoneinfo import TZPATH

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.supply_contract import INPUT_POLICY, MAX_BYTES, RECIPE, RULE_ID, SupplyRuntime, hash_content, input_policy_digest, recipe_digest
from app.ai.supply_model import implementation_hashes


class SupplySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUPPLY_", env_file=None, extra="ignore")
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_SUPPLY_API_KEY", min_length=32)
    max_request_bytes: int = Field(default=MAX_BYTES, ge=65536, le=MAX_BYTES)
    timeout_seconds: int = Field(default=90, ge=1, le=110)


def timezone_database_digest():
    roots = []
    for directory in TZPATH:
        root = Path(directory)
        if not root.is_dir():
            continue
        entries = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if data.startswith(b"TZif") or path.name == "tzdata.zi":
                entries[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
        if entries:
            roots.append(entries)
    if not roots:
        # A standalone deployment must install a reviewable IANA database;
        # UTC-only fallback would silently reject legitimate business zones.
        raise ValueError("No verifiable system IANA timezone database is available")
    return hash_content(roots)


def runtime_descriptor(config=None):
    identity = {
        "engine": "stdlib_recorded_supply_forecast",
        "python_version": platform.python_version(),
        "engine_versions": {package.replace("-", "_"): version(package) for package in ("fastapi", "pydantic", "pydantic-settings", "uvicorn")},
        "core_sha256": implementation_hashes(),
        "recipe_digest": recipe_digest(),
        "input_policy_digest": input_policy_digest(),
        "timezone_database_digest": timezone_database_digest(),
        "clinical_validation": "not_provided",
        "operational_validation": "not_provided",
        "prompt_handling": "provenance_only",
        "coverage_guarantee": "not_provided",
    }
    digest = hash_content(identity)
    return {
        "schema_version": "13",
        "feature_key": "supply_forecast",
        "rule_id": RULE_ID,
        **identity,
        "runtime_digest": digest,
        "model_version": "supply:" + digest,
        "recipe": RECIPE,
        "input_policy": INPUT_POLICY,
        "independent_implementation": True,
        "max_request_bytes": config.max_request_bytes if config else MAX_BYTES,
        "max_response_bytes": MAX_BYTES,
        "timeout_seconds": config.timeout_seconds if config else 90,
        "scope": "single_sku_single_scope_recorded_requests_issues_consumption",
        "forecast_only": True,
    }


def runtime_from_descriptor(descriptor):
    return SupplyRuntime.model_validate({key: descriptor[key] for key in SupplyRuntime.model_fields}).model_dump()
