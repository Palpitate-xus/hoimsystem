"""Inspect mounted paths and dependencies through FastAPI's public route API."""

from fastapi.routing import APIRoute, iter_route_contexts


def api_routes(routes):
    return [context for context in iter_route_contexts(routes) if isinstance(context.original_route, APIRoute)]
