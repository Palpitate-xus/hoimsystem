"""Dialect expressions for technical JSON routing, never source authorization.

SQLite/MySQL retain their SQL. PostgreSQL reads the original JSON text without
jsonb normalization; first duplicate members match SQLite's existing routing
branch, and a present JSON null remains distinct from a missing member.
"""

import re

from sqlalchemy import BigInteger, Integer, String, literal
from sqlalchemy.exc import CompileError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import GenericFunction
from sqlalchemy.sql.visitors import InternalTraversal


class _JSONValid(GenericFunction):
    name = "json_valid"
    type = Integer()
    inherit_cache = True
    _register = False


class _PathFunction(GenericFunction):
    inherit_cache = True
    _register = False
    _traverse_internals = [*GenericFunction._traverse_internals, ("path_text", InternalTraversal.dp_string)]

    def __init__(self, *arguments):
        value = arguments[-1] if len(arguments) > 1 else "$"
        self.path_text = value if type(value) is str else getattr(value, "value", None)
        super().__init__(*arguments)


class _JSONExtract(_PathFunction):
    name = "json_extract"
    # Paths affect PostgreSQL SQL structure, so they participate in the cache
    # key. Stored task text remains an ordinary bound value.
    inherit_cache = True
    _register = False


class _JSONType(_PathFunction):
    name = "json_type"
    type = String()
    inherit_cache = True
    _register = False


class _TextHex(GenericFunction):
    name = "hex"
    type = String()
    inherit_cache = True
    _register = False


class _JSONInteger(_PathFunction):
    type = BigInteger()
    inherit_cache = True
    _register = False


class _JSONString(_PathFunction):
    type = String()
    inherit_cache = True
    _register = False


def json_valid(document):
    return _JSONValid(document)


def json_extract(document, path):
    return _JSONExtract(document, path)


def json_type(document, path=None):
    return _JSONType(document) if path is None else _JSONType(document, path)


def text_hex(value):
    return _TextHex(value)


def json_integer(original, document, path):
    return _JSONInteger(original, document, path)


def json_string(original, document, path):
    return _JSONString(original, document, path)


def _path_components(path):
    value = getattr(path, "value", None)
    if type(value) is not str or not value.startswith("$"):
        raise CompileError("Technical JSON paths must be explicit bounded member paths")
    result = []
    position = 1
    while position < len(value):
        member = re.match(r"\.([A-Za-z_][A-Za-z_0-9]*)|\[([0-9]+)\]", value[position:])
        if member is None or len(result) >= 16:
            raise CompileError("Unsupported technical JSON member path")
        result.append(member[1] if member[1] is not None else int(member[2]))
        position += member.end()
    return result


def _path_value(document, path, compiler, kwargs):
    original = compiler.process(document, **kwargs)
    value = f"CAST(CASE WHEN ({original}) IS NULL THEN NULL WHEN ({original}) IS JSON THEN ({original}) ELSE '{{}}' END AS JSON)"
    for component in _path_components(path):
        if isinstance(component, int):
            value = (
                f"(SELECT item.value FROM (SELECT {value} AS value) original "
                "CROSS JOIN LATERAL json_array_elements(CASE WHEN json_typeof(original.value)='array' "
                "THEN original.value ELSE '[]'::json END) WITH ORDINALITY AS item(value, position) "
                f"WHERE item.position={component + 1} LIMIT 1)"
            )
        else:
            key = compiler.render_literal_value(component, String())
            value = (
                f"(SELECT item.value FROM (SELECT {value} AS value) original "
                "CROSS JOIN LATERAL json_each(CASE WHEN json_typeof(original.value)='object' "
                "THEN original.value ELSE '{}'::json END) WITH ORDINALITY AS item(key, value, position) "
                f"WHERE item.key={key} ORDER BY item.position LIMIT 1)"
            )
    return value


@compiles(_JSONValid, "postgresql")
def _pg_valid(element, compiler, **kwargs):
    document = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"(CASE WHEN ({document}) IS JSON THEN 1 ELSE 0 END)"


@compiles(_TextHex, "postgresql")
def _pg_hex(element, compiler, **kwargs):
    value = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"upper(encode(convert_to({value}, 'UTF8'), 'hex'))"


@compiles(_JSONExtract, "postgresql")
def _pg_extract(element, compiler, **kwargs):
    document, path = tuple(element.clauses)
    value = _path_value(document, path, compiler, kwargs)
    return f"(({value}) #>> '{{}}')"


@compiles(_JSONType, "postgresql")
def _pg_type(element, compiler, **kwargs):
    arguments = tuple(element.clauses)
    document, path = arguments if len(arguments) == 2 else (arguments[0], literal("$"))
    value = _path_value(document, path, compiler, kwargs)
    return (
        "(SELECT CASE json_typeof(member.value) WHEN 'string' THEN 'text' "
        "WHEN 'number' THEN CASE WHEN member.value::text ~ '^-?[0-9]+$' THEN 'integer' ELSE 'real' END "
        "WHEN 'boolean' THEN member.value::text ELSE json_typeof(member.value) END "
        f"FROM (SELECT {value} AS value) member)"
    )


@compiles(_JSONInteger)
@compiles(_JSONString)
def _original_scalar(element, compiler, **kwargs):
    return compiler.process(next(iter(element.clauses)), **kwargs)


@compiles(_JSONInteger, "postgresql")
def _pg_integer(element, compiler, **kwargs):
    _, document, path = tuple(element.clauses)
    value = _path_value(document, path, compiler, kwargs)
    # Only bounded integer tokens can reach a cast. SQL AND evaluation order
    # cannot make a string/bool/huge historical number raise or become an ID.
    return (
        "(SELECT CASE WHEN json_typeof(member.value)='number' "
        "AND member.value::text ~ '^-?[0-9]+$' AND length(ltrim(member.value::text, '-'))<=10 "
        f"THEN CAST(member.value::text AS BIGINT) ELSE NULL END FROM (SELECT {value} AS value) member)"
    )


@compiles(_JSONString, "postgresql")
def _pg_string(element, compiler, **kwargs):
    _, document, path = tuple(element.clauses)
    value = _path_value(document, path, compiler, kwargs)
    return f"(SELECT CASE WHEN json_typeof(member.value)='string' THEN member.value #>> '{{}}' ELSE NULL END FROM (SELECT {value} AS value) member)"
