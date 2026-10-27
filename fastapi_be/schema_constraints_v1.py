"""Version 1 schema checks, shared by standalone migrations and current models.

SQLite and MySQL keep their original CHECK SQL. PostgreSQL 16+ uses native
UTF-8 conversion and JSON predicates rather than SQLite JSON/HEX functions or
the PostgreSQL bytea input parser (which interprets text backslash escapes).
"""

import copy
import re

from sqlalchemy import CheckConstraint as SQLAlchemyCheckConstraint
from sqlalchemy import Integer, LargeBinary, func, text
from sqlalchemy.exc import CompileError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import Cast, TextClause
from sqlalchemy.sql.functions import FunctionElement


class CheckConstraint(SQLAlchemyCheckConstraint):
    """Keep the original expression and translate only PostgreSQL CHECK DDL."""


PortableCheckConstraint = CheckConstraint


class _UTF8Bytes(FunctionElement):
    type = Integer()
    inherit_cache = True


class _JSONValid(FunctionElement):
    type = Integer()
    inherit_cache = True


@compiles(_UTF8Bytes, "postgresql")
def _compile_utf8_bytes(element, compiler, **kwargs):
    value = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"octet_length(convert_to({value}, 'UTF8'))"


@compiles(_JSONValid, "postgresql")
def _compile_json_valid(element, compiler, **kwargs):
    value = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"(CASE WHEN ({value}) IS JSON THEN 1 ELSE 0 END)"


_TOKENS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\bHEX\s*\(", re.IGNORECASE)
_HEX_ARGUMENT = re.compile(r"\s*('(?:[^']|'')*'|[A-Za-z_][A-Za-z_0-9]*|\"(?:[^\"]|\"\")*\")\s*\)")


def _postgresql_text(expression):
    """Translate known single-argument HEX checks, leaving SQL literals alone."""
    result = []
    position = 0
    for token in _TOKENS.finditer(expression):
        if token.start() < position or token.group().startswith(("'", '"')):
            continue
        argument = _HEX_ARGUMENT.match(expression, token.end())
        if argument is None:
            raise CompileError("Portable HEX checks require a text column or SQL string literal")
        result.extend((expression[position:token.start()], f"upper(encode(convert_to({argument[1]}, 'UTF8'), 'hex'))"))
        position = argument.end()
    result.append(expression[position:])
    return "".join(result)


def _postgresql_expression(expression, table):
    def replace(node):
        if isinstance(node, TextClause):
            return text(_postgresql_text(node.text))
        if isinstance(node, FunctionElement):
            arguments = tuple(node.clauses)
            if node.name.lower() == "json_valid" and len(arguments) == 1:
                return _JSONValid(arguments[0])
            if node.name.lower() == "length" and len(arguments) == 1:
                argument = arguments[0]
                if isinstance(argument, Cast) and isinstance(argument.type, LargeBinary):
                    source = argument.clause
                    column = table.columns.get(getattr(source, "name", None))
                    if isinstance(source.type, LargeBinary) or column is not None and isinstance(column.type, LargeBinary):
                        return func.octet_length(source)
                    return _UTF8Bytes(argument.clause)
        return None

    return visitors.replacement_traverse(expression, {}, replace)


@compiles(PortableCheckConstraint)
def _compile_original(constraint, compiler, **kwargs):
    return compiler.visit_check_constraint(constraint, **kwargs)


@compiles(PortableCheckConstraint, "postgresql")
def _compile_postgresql(constraint, compiler, **kwargs):
    # A shallow copy retains the real table/naming metadata. Compilation must
    # not mutate a shared constraint or append a second constraint to its table.
    portable = copy.copy(constraint)
    portable.sqltext = _postgresql_expression(constraint.sqltext, constraint.table)
    return compiler.visit_check_constraint(portable, **kwargs)
