"""Dialect checks preserve stored UTF-8, JSON validity and exact identity SQL."""

import concurrent.futures

import pytest
from sqlalchemy import CheckConstraint, Column, Integer, LargeBinary, MetaData, String, Table, Text, cast, column, func
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.exc import CompileError
from sqlalchemy.schema import CreateTable

from app.database import Base
from app.sql_constraints import PortableCheckConstraint


def definition(constraint=PortableCheckConstraint):
    return Table(
        "portable_probe", MetaData(),
        Column("status", String(24), nullable=False),
        Column("body", Text, nullable=False),
        Column("bytes", Integer, nullable=False),
        Column("key", LargeBinary(32), nullable=False),
        constraint("HEX(status)=HEX('draft')", name="ck_probe_case"),
        constraint(func.json_valid(column("body")) == 1, name="ck_probe_json"),
        constraint(func.length(cast(column("body"), LargeBinary)) == column("bytes"), name="ck_probe_utf8"),
        constraint(func.length(cast(column("key"), LargeBinary)) == 32, name="ck_probe_binary"),
    )


@pytest.mark.parametrize("dialect", [sqlite.dialect(), mysql.dialect()])
def test_sqlite_and_mysql_ddl_remain_identical_to_original_constraints(dialect):
    original = str(CreateTable(definition(CheckConstraint)).compile(dialect=dialect))
    portable = str(CreateTable(definition()).compile(dialect=dialect))
    assert portable == original


def test_postgres_uses_native_json_predicate_exact_hex_and_utf8_bytes():
    ddl = str(CreateTable(definition()).compile(dialect=postgresql.dialect()))
    assert "upper(encode(convert_to(status, 'UTF8'), 'hex'))" in ddl
    assert "upper(encode(convert_to('draft', 'UTF8'), 'hex'))" in ddl
    assert "(CASE WHEN (body) IS JSON THEN 1 ELSE 0 END) = 1" in ddl
    assert "octet_length(convert_to(body, 'UTF8')) = bytes" in ddl
    assert "octet_length(key) = 32" in ddl
    assert "CAST(" not in ddl and "json_valid(" not in ddl and "HEX(" not in ddl


def test_compilation_does_not_mutate_sql_or_add_constraints_between_dialects():
    table = definition()
    before = [(id(check), str(check.sqltext)) for check in table.constraints if isinstance(check, CheckConstraint)]
    dialects = [postgresql.dialect(), mysql.dialect(), sqlite.dialect()] * 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers:
        list(workers.map(lambda dialect: str(CreateTable(table).compile(dialect=dialect)), dialects))
    after = [(id(check), str(check.sqltext)) for check in table.constraints if isinstance(check, CheckConstraint)]
    assert after == before


def test_hex_literal_contents_and_sql_escaped_quotes_are_not_rewritten():
    table = Table("probe", MetaData(), Column("value", Text), PortableCheckConstraint("value='HEX(not_a_call)' OR HEX(value)=HEX('quote''d')", name="ck_quote"))
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "value='HEX(not_a_call)'" in ddl
    assert "convert_to('quote''d', 'UTF8')" in ddl


def test_unrecognized_text_hex_expression_is_rejected_instead_of_silently_weakened():
    table = Table("probe", MetaData(), Column("value", Text), PortableCheckConstraint("HEX(lower(value))=HEX('draft')", name="ck_unknown"))
    with pytest.raises(CompileError, match="Portable HEX checks"):
        str(CreateTable(table).compile(dialect=postgresql.dialect()))


def test_all_current_model_tables_compile_for_postgres_without_sqlite_only_checks():
    assert len(Base.metadata.tables) >= 266
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "json_valid(" not in ddl.lower(), table.name
        # HEX mentioned inside a literal is covered separately; the model
        # checks use it only as an identity comparison function.
        assert "HEX(" not in ddl, table.name
        assert " AS BYTEA)" not in ddl, table.name
