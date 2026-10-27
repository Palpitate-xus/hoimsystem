"""Byte-oriented database expressions for untouched stored UTF-8 text."""

from sqlalchemy import Integer, LargeBinary, cast, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class UTF8Bytes(FunctionElement):
    type = Integer()
    inherit_cache = True


@compiles(UTF8Bytes)
def _original_bytes(element, compiler, **kwargs):
    value = next(iter(element.clauses))
    return compiler.process(func.length(cast(value, LargeBinary)), **kwargs)


@compiles(UTF8Bytes, "postgresql")
def _postgresql_bytes(element, compiler, **kwargs):
    value = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"octet_length(convert_to({value}, 'UTF8'))"
