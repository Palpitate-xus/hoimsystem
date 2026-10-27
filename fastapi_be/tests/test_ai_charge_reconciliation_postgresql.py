"""Additive PostgreSQL Float witnesses preserve old source contracts and proofs."""

import copy

import pytest
from sqlalchemy import column
from sqlalchemy.dialects import mysql, postgresql

from app.ai import charge_reconciliation_contract as contract
from app.ai import charge_reconciliation_sources as source
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case

PG_METHOD = "postgresql_CAST_AS_DOUBLE_PRECISION_in_same_current_statement"


def test_postgres_float_promotion_is_explicit_while_mysql_sql_remains_unchanged():
    value = source.SQLFloatPromotion(column("quantity"))
    assert str(value.compile(dialect=postgresql.dialect())) == "CAST(quantity AS DOUBLE PRECISION)"
    assert str(value.compile(dialect=mysql.dialect())) == "CAST(quantity AS DOUBLE)"


@pytest.mark.parametrize("value", (None, 0.0, -0.0, -0.5, 0.1, 2.675))
def test_postgres_witness_retains_original_float_hex_repr_and_null(value):
    witness = contract.SQLFloatWitness(method=PG_METHOD, value_text=None if value is None else repr(value), binary_hex=None if value is None else value.hex())
    original = contract.stored_float(value, sql_witness=witness)
    assert original["storage_witness"]["method"] == PG_METHOD
    assert original["storage_witness"]["value_text"] == original["value_text"]
    assert original["storage_witness"]["binary_hex"] == original["binary_hex"]


def reseal(value):
    value["member_manifest"] = source.member_manifest(value)
    value["manifest_hash"] = contract.digest(value["member_manifest"])
    value["collection_digest"] = contract.digest(source.collection_content(value))
    return value


def test_matching_postgres_basis_is_required_even_after_all_modified_digests_are_resealed(charge_case):
    original = source.capture_case(charge_case["db"], charge_case["super_admin_user"], {
        "patient_id": charge_case["patient"].patient_id,
        "admission_id": charge_case["admission"].admission_id,
    })
    original_bytes = contract.canonical_json(original)
    value = copy.deepcopy(original)
    value["float_capture_basis"] = "postgresql_same_statement_float8"
    for charge in value["charges"]:
        quantity = charge["quantity"]
        quantity["storage_witness"] = {"method": PG_METHOD, "value_text": quantity["value_text"], "binary_hex": quantity["binary_hex"]}
    assert source.verify_capture(reseal(value))
    forged = copy.deepcopy(value)
    forged["float_capture_basis"] = "mysql_same_statement_double_promotion"
    assert not source.verify_capture(reseal(forged))
    forged = copy.deepcopy(value)
    forged["charges"][0]["quantity"]["storage_witness"]["method"] = "mysql_CAST_AS_DOUBLE_in_same_current_statement"
    assert not source.verify_capture(reseal(forged))
    assert source.verify_capture(original) and contract.canonical_json(original) == original_bytes
