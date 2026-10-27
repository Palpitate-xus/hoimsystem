"""Untouched UTF-8 byte counts and SQL-only hash witnesses across dialects."""

import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import LargeBinary, cast, column, func, literal, select
from sqlalchemy.dialects import mysql, sqlite

from app.ai.deidentification_collection import _sql_hash
from app.sql_text import UTF8Bytes
from tests.sql_dialect_fixtures import connection as connection


@pytest.mark.parametrize("value", (None, "", "ASCII", "中😀", "\\x41\\123", "原文\\u0000\\n", '{"a":1,"a":2}'))
def test_actual_stored_text_bytes_and_hash_match_python_without_parsing_or_normalizing(connection, value):
    expression = literal(value)
    db = SimpleNamespace(get_bind=lambda: connection, connection=lambda: connection)
    actual_bytes, actual_hash = connection.execute(select(UTF8Bytes(expression), _sql_hash(db, expression))).one()
    assert actual_bytes == (None if value is None else len(value.encode("utf-8")))
    assert actual_hash == (None if value is None else hashlib.sha256(value.encode("utf-8")).hexdigest())


@pytest.mark.parametrize("dialect", (sqlite.dialect(), mysql.dialect()))
def test_original_binary_byte_expression_is_preserved_for_existing_dialects(dialect):
    value = column("original_text")
    assert str(UTF8Bytes(value).compile(dialect=dialect)) == str(func.length(cast(value, LargeBinary)).compile(dialect=dialect))
