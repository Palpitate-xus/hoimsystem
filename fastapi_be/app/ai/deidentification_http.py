"""Whole UTF8 JSON request/response boundaries, without timestamp rewriting."""

import asyncio
import json
import math

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.ai.deidentification_contract import MAX_BYTES
from app.ai.deidentification_spans import utf8


def parse_json(raw):
    def pairs(values):
        value = {}
        for key, item in values:
            if key in value:
                raise ValueError("Duplicate JSON keys")
            value[key] = item
        return value

    def finite(value):
        raise ValueError("Nonfinite JSON values are not permitted")

    text = raw.decode("utf-8", errors="strict")

    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite JSON number")
        return result

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=finite, parse_float=floating)

    # JSON escape sequences can create unpaired surrogates after UTF8 decoding.
    def scalars(item):
        if type(item) is str:
            utf8(item)
        elif type(item) is dict:
            for key, val in item.items():
                utf8(key)
                scalars(val)
        elif type(item) is list:
            for val in item:
                scalars(val)

    scalars(value)
    return value


def response_bytes(data):
    raw = JSONResponse({"code": 200, "msg": "success", "data": data}).body
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "完整75回执超8MiB，未截断")
    return raw


class BoundedDeidentificationResponse(JSONResponse):
    def render(self, content):
        raw = super().render(content)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "完整75回执超8MiB，未截断")
        return raw


class BoundedDeidentificationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PUT", "PATCH"}:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise HTTPException(415, "75请求须明确UTF8 application/json")
                sizes = request.headers.getlist("content-length")
                if len(sizes) > 1 or sizes and (not sizes[0].isascii() or not sizes[0].isdigit() or len(sizes[0]) > 10):
                    raise HTTPException(400, "75请求长度不规范")
                if sizes and int(sizes[0]) > MAX_BYTES:
                    raise HTTPException(413, "75完整请求超8MiB，未读取或写入")
                raw = bytearray()
                try:
                    async with asyncio.timeout(10):
                        async for chunk in request.stream():
                            if len(raw) + len(chunk) > MAX_BYTES:
                                raise HTTPException(413, "75完整请求超8MiB，未截断或写入")
                            raw.extend(chunk)
                except TimeoutError as exc:
                    raise HTTPException(408, "75上传超过10秒，未接受原件") from exc
                try:
                    parse_json(bytes(raw))
                except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                    raise HTTPException(422, "75须完整UTF8 JSON，禁止重复键、非有限数与非法Unicode") from exc
                request._body = bytes(raw)
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise HTTPException(422, "75请求不符合明确范围、逐字或独立审核合同") from exc

        return bounded
