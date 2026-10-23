"""Installed local arithmetic identity; no endpoint, clinical validation or activation."""

import hashlib
from pathlib import Path

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_statistics_contract as k

FILES = ("infection_cluster_contract.py", "infection_cluster_projection.py", "infection_cluster_statistics_contract.py", "infection_cluster_statistics.py")


def implementation_descriptor():
    base = Path(__file__).parent
    return {
        "schema_version": "infection_local_implementation_v1",
        "engine": "prediction",
        "execution": "installed_local_exact_integer_statistics_no_external_model",
        "version": k.RECIPE["version"],
        "recipe_hash": c.digest(k.RECIPE),
        "code_hashes": {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in FILES},
        "local_clinical_validation": "not_provided_by_implementation_identity",
        "automatic_enable": False,
    }
