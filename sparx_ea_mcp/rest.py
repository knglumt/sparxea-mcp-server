"""
Optional plain-REST compatibility layer, mounted alongside the real MCP
JSON-RPC endpoint (MCP_HTTP_PATH).

This is NOT part of the MCP spec. It exists because some internal API
testers (and simple scripts) assume one-URL-per-tool REST semantics -
`POST <base>/<tool_name>` with a plain JSON object of arguments as the
body - rather than MCP's JSON-RPC envelope (`POST <base>`, body
`{"method": "tools/call", "params": {"name": ..., "arguments": {...}}}`).

Every route here calls the exact same repository functions the MCP tools
use - same data, same read-only guarantees, same auth (the bearer-token
middleware covers these routes too) - just a different calling
convention layered on top for tools that expect it.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import db
from . import repository as repo
from .svg import render_diagram_svg

logger = logging.getLogger("sparx_ea_mcp.rest")


def _get_diagram_image(diagram_id: int) -> str:
    diagram = repo.get_diagrams_information(diagram_id)
    if "error" in diagram:
        return diagram["error"]
    return render_diagram_svg(diagram)


_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "check_connection": db.check_connection,
    "get_model_overview": repo.get_model_overview,
    "get_root_packages": repo.get_root_packages,
    "find_packages_by_name": repo.find_packages_by_name,
    "get_package_contents": repo.get_package_contents,
    "find_elements_by_name": repo.find_elements_by_name,
    "get_elements_information": repo.get_elements_information,
    "find_element_in_diagrams": repo.find_element_in_diagrams,
    "export_element_linked_documents": repo.export_element_linked_documents,
    "get_connectors_information": repo.get_connectors_information,
    "find_diagrams_by_name": repo.find_diagrams_by_name,
    "get_diagrams_information": repo.get_diagrams_information,
    "get_diagram_image": _get_diagram_image,
    "search_model": repo.search_model,
}


def _make_handler(fn: Callable[..., Any]):
    async def handler(request: Request) -> JSONResponse:
        try:
            body = await request.body()
            kwargs = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)
        if not isinstance(kwargs, dict):
            return JSONResponse(
                {"error": "Request body must be a JSON object of arguments (e.g. {} or {\"name\": \"...\"})."},
                status_code=400,
            )
        try:
            result = fn(**kwargs)
        except TypeError as exc:
            return JSONResponse({"error": f"Invalid arguments: {exc}"}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("REST tool call failed: %s", fn.__name__)
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse({"result": result})

    return handler


def build_rest_routes(prefix: str = "") -> list[Route]:
    """One POST route per tool, at `<prefix>/<tool_name>`."""
    prefix = prefix.rstrip("/")
    return [
        Route(f"{prefix}/{name}", _make_handler(fn), methods=["POST"])
        for name, fn in _TOOL_FUNCTIONS.items()
    ]
