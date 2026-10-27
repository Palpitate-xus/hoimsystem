"""Actual dialect predicates keep routing hints separate from source authority."""

import pytest
from sqlalchemy import BigInteger, and_, case, cast, func, literal, select
from sqlalchemy.dialects import mysql, sqlite

from app.sql_json import json_extract, json_integer, json_string, json_type, json_valid, text_hex
from tests.sql_dialect_fixtures import connection as connection


def safe(document):
    return case((json_valid(document) == 1, document), else_="{}")


def test_static_paths_have_distinct_statement_cache_keys_while_body_values_stay_bound():
    left = select(json_extract(literal('{"left":"one"}'), "$.left"))
    same_path = select(json_extract(literal('{"left":"other"}'), "$.left"))
    right = select(json_extract(literal('{"right":"two"}'), "$.right"))
    assert left._generate_cache_key() is not None
    assert left._generate_cache_key().key == same_path._generate_cache_key().key
    assert left._generate_cache_key().key != right._generate_cache_key().key


@pytest.mark.parametrize("dialect", (sqlite.dialect(), mysql.dialect()))
def test_original_sqlite_mysql_functions_compile_without_changed_sql(dialect):
    body = literal('{"x":1}')
    for portable, original in (
        (json_valid(body), func.json_valid(body)),
        (json_extract(body, "$.x"), func.json_extract(body, "$.x")),
        (json_type(body, "$.x"), func.json_type(body, "$.x")),
        (json_type(body), func.json_type(body)),
        (text_hex(body), func.hex(body)),
    ):
        assert str(select(portable).compile(dialect=dialect, compile_kwargs={"literal_binds": True})) == str(select(original).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize("body,path,expected", (
    ('{"x":null}', "$.x", "null"),
    ('{}', "$.x", None),
    ('{"x":true}', "$.x", "true"),
    ('{"x":false}', "$.x", "false"),
    ('{"x":1}', "$.x", "integer"),
    ('{"x":1.0}', "$.x", "real"),
    ('{"x":1e0}', "$.x", "real"),
    ('{"x":"1"}', "$.x", "text"),
    ('{"x":[]}', "$.x", "array"),
    ('{"x":{}}', "$.x", "object"),
    ('[{"kind":"source"}]', "$[0].kind", "text"),
    ('{"x":1,"x":"later"}', "$.x", "integer"),
    ('{"x":{"y":1},"x":{"y":"later"}}', "$.x.y", "integer"),
    ('{"x":null}', "$.x.y", None),
    ('[]', "$[1].kind", None),
))
def test_actual_json_type_preserves_null_presence_first_duplicates_and_exact_tokens(connection, body, path, expected):
    assert connection.scalar(select(json_type(safe(literal(body)), path))) == expected


@pytest.mark.parametrize("body", ('broken', '{"x":', 'NaN', 'Infinity', '{x:1}'))
def test_malformed_stored_text_is_quarantined_before_member_read(connection, body):
    document = literal(body)
    assert connection.scalar(select(json_valid(document))) == 0
    assert connection.scalar(select(json_type(safe(document), "$.x"))) is None
    assert connection.scalar(select(json_extract(safe(document), "$.x"))) is None


@pytest.mark.parametrize("token,expected", (('1', True), ('"1"', False), ('true', False), ('false', False), ('1.0', False), ('1e0', False), ('999999999999999999999999999999999', False), ('null', False), ('"invalid cast"', False)))
def test_integer_scope_cannot_be_forged_or_raise_on_huge_or_noninteger_tokens(connection, token, expected):
    document = safe(literal('{"x":' + token + '}'))
    original = cast(json_extract(document, "$.x"), BigInteger)
    predicate = and_(json_type(document, "$.x") == "integer", json_integer(original, document, "$.x") == 1)
    assert bool(connection.scalar(select(predicate))) is expected


def test_first_duplicate_scalar_array_path_and_compiled_path_changes(connection):
    document = literal('{"left":"first","left":"later","right":"second","array":[{"kind":"source"}]}')
    for path, expected in (("$.left", "first"), ("$.right", "second"), ("$.array[0].kind", "source")):
        assert connection.scalar(select(json_extract(document, path))) == expected
    source = literal('{"x":"中😀\\\\x41"}')
    original = json_extract(source, "$.x")
    assert connection.scalar(select(json_string(original, source, "$.x"))) == "中😀\\x41"
    assert connection.scalar(select(text_hex(literal("中😀")))) == "中😀".encode().hex().upper()
