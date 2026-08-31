"""
SparxEA-MCP-Server entry point.

Exposes read-only Enterprise Architect repository access as MCP tools over
STDIO, so it can be launched by any MCP client (Claude Desktop, Claude
Code, VS Code, etc.) the same way the official Sparx MCP3.exe is, just
with `python3 -m sparx_ea_mcp.server` instead of an .exe.

Works against every backend Sparx EA supports on the server side (see
EA_DB_BACKEND in config.py): SQL Server, MySQL/MariaDB, PostgreSQL,
Oracle, Firebird, plus SQLite for local .qea/.qeax files.

Tool surface deliberately mirrors the *read* half of Sparx Systems' own
MCP Server for Enterprise Architect (see
https://www.sparxsystems.jp/en/MCP/#feature):

    Packages:  get_root_packages, find_packages_by_name, get_package_contents
    Elements:  find_elements_by_name, get_elements_information,
               find_element_in_diagrams, export_element_linked_documents
    Connectors: get_connectors_information
    Diagrams:  find_diagrams_by_name, get_diagrams_information,
               get_diagram_image
    Misc:      get_model_overview, search_model, check_connection

Tools that require a *live* EA.exe session (get_current_diagram,
open_diagrams, select_element_in_browser, get_opened_diagrams,
reload_diagrams, and every create/update/delete tool) are out of scope for
a pure database reader and are not implemented here.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _MCPServerImpl
except ImportError:
    # mcp < 2.0
    from mcp.server.fastmcp import FastMCP as _MCPServerImpl  # type: ignore

from . import repository as repo
from .db import check_connection as _check_connection
from .svg import render_diagram_svg

logging.basicConfig(
    level=os.getenv("EA_MCP_LOG_LEVEL", "INFO"),
    stream=sys.stderr,  # stdout is reserved for the MCP STDIO protocol
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sparx_ea_mcp.server")

mcp = _MCPServerImpl(
    "SparxEA-MCP-Server",
    instructions=(
        "Read-only access to a Sparx Systems Enterprise Architect model, "
        "on whichever database backend this repository uses (SQL Server, "
        "MySQL/MariaDB, PostgreSQL, Oracle, Firebird, or a local SQLite "
        ".qea/.qeax file). Start broad (get_model_overview, "
        "get_root_packages, or search_model) then drill down with the "
        "*_by_name finder tools to get an Object_ID / Diagram_ID / "
        "Package_ID, and pass that ID into the matching *_information "
        "tool for full detail. IDs are small integers local to this "
        "repository, safe to pass between tool calls."
    ),
)


@mcp.tool()
def check_connection() -> dict:
    """
    Verify the database connection and report which backend, SQL dialect
    and driver this server is talking to, and how many tables are visible.
    """
    return _check_connection()


@mcp.tool()
def get_model_overview() -> dict:
    """
    Get high-level statistics about the connected EA repository: total
    counts of packages, elements, diagrams and connectors, plus the most
    common element types and diagram types. Good first call to orient in
    an unfamiliar model.
    """
    return repo.get_model_overview()


@mcp.tool()
def get_root_packages() -> list[dict]:
    """
    List the top-level packages exactly as they appear at the root of the
    Enterprise Architect Browser window (e.g. 'Requirements', 'Analysis
    Model', 'Design Model'), including sub-item counts for each.
    """
    return repo.get_root_packages()


@mcp.tool()
def find_packages_by_name(name: str, exact_match: bool = False, limit: int = 50) -> list[dict]:
    """
    Find packages (folders in the Browser tree) by name.

    Args:
        name: Text to search for.
        exact_match: If True, match the name exactly; otherwise substring match.
        limit: Maximum number of results (server-capped).
    """
    return repo.find_packages_by_name(name, exact_match, limit)


@mcp.tool()
def get_package_contents(package_id: int) -> dict:
    """
    Get a package's metadata plus its direct subpackages, elements and
    diagrams (one level deep, like expanding a node in the Browser tree).
    Call again with a returned subpackage's Package_ID to go deeper.
    """
    return repo.get_package_contents(package_id)


@mcp.tool()
def find_elements_by_name(
    name: str,
    exact_match: bool = False,
    object_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Find model elements (classes, interfaces, actors, use cases,
    activities, requirements, etc.) by name.

    Args:
        name: Text to search for.
        exact_match: If True, match the name exactly; otherwise substring match.
        object_type: Optional EA element type filter, e.g. 'Class', 'Interface',
            'UseCase', 'Actor', 'Requirement', 'Component'.
        limit: Maximum number of results (server-capped).
    """
    return repo.find_elements_by_name(name, exact_match, object_type, limit)


@mcp.tool()
def get_elements_information(object_id: int) -> dict:
    """
    Get full detail for one element by its Object_ID: core properties,
    attributes (with their tagged values), operations (with parameters
    and tagged values), the element's own tagged values, and summary
    counts of connectors and diagram placements. Get the Object_ID from
    find_elements_by_name, search_model, or another tool's output first.
    """
    return repo.get_elements_information(object_id)


@mcp.tool()
def find_element_in_diagrams(object_id: int) -> list[dict]:
    """
    Find every diagram that an element (by Object_ID) is placed on, along
    with its position on each diagram. Equivalent to the official Sparx
    MCP's find_element_in_diagrams tool.
    """
    return repo.find_element_in_diagrams(object_id)


@mcp.tool()
def export_element_linked_documents(object_id: int) -> list[dict]:
    """
    Export any Linked Documents (rich text notes attached via EA's
    'Linked Document' feature) stored against an element, by Object_ID.
    """
    return repo.export_element_linked_documents(object_id)


@mcp.tool()
def get_connectors_information(object_id: int) -> list[dict]:
    """
    Get every connector (association, dependency, generalization, etc.)
    attached to an element, by Object_ID, at either end - including the
    name and type of the element at the other end, role names,
    multiplicities and tagged values.
    """
    return repo.get_connectors_information(object_id)


@mcp.tool()
def find_diagrams_by_name(name: str, exact_match: bool = False, limit: int = 50) -> list[dict]:
    """
    Find diagrams by name.

    Args:
        name: Text to search for.
        exact_match: If True, match the name exactly; otherwise substring match.
        limit: Maximum number of results (server-capped).
    """
    return repo.find_diagrams_by_name(name, exact_match, limit)


@mcp.tool()
def get_diagrams_information(diagram_id: int) -> dict:
    """
    Get full detail for one diagram by its Diagram_ID: metadata, every
    element placed on it (with layout rectangle), and every connector
    drawn between those elements on this diagram. Get the Diagram_ID from
    find_diagrams_by_name or search_model first.
    """
    return repo.get_diagrams_information(diagram_id)


@mcp.tool()
def get_diagram_image(diagram_id: int) -> str:
    """
    Render a schematic SVG of a diagram's layout (boxes for elements,
    lines for connectors) reconstructed from stored coordinates.

    This is NOT Enterprise Architect's own rendering - there is no live
    EA.exe instance to ask for a real image when reading straight from
    the database, so shapes, colors, fonts and notation-specific symbols
    (actors, lifelines, swimlanes, etc.) are not reproduced. Use
    get_diagrams_information for authoritative element/connector data;
    use this only for a rough visual sense of the layout.
    """
    diagram = repo.get_diagrams_information(diagram_id)
    if "error" in diagram:
        return diagram["error"]
    return render_diagram_svg(diagram)


@mcp.tool()
def search_model(text: str, limit: int = 25) -> dict:
    """
    Free-text search across package names, element names/notes and
    diagram names in a single call. Use this first when you don't yet
    know whether what you're looking for is a package, element or
    diagram, then follow up with the more specific *_information tools.
    """
    return repo.search_model(text, limit)


def main() -> None:
    """
    Entry point. Defaults to STDIO (for local MCP clients like Claude
    Desktop/Code launching this as a subprocess). Set MCP_TRANSPORT=http
    to instead listen on the network as a remote MCP server - see
    README.md's "Hosting on a server" section for the full setup
    (systemd service, reverse proxy, bearer-token auth).
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    if transport != "http":
        raise RuntimeError(f"Unknown MCP_TRANSPORT={transport!r}; use 'stdio' or 'http'.")

    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    from .auth import BearerTokenMiddleware

    host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_HTTP_PORT", "8765"))
    path = os.getenv("MCP_HTTP_PATH", "/mcp")

    # MCP's streamable-http transport auto-enables DNS-rebinding
    # protection when bound to 127.0.0.1/localhost, but its default
    # allow-list only accepts Host/Origin headers matching that bind
    # address. That breaks the moment a reverse proxy forwards the
    # original public hostname (Host: mcp.your-domain.example.com)
    # unchanged, exactly as the deploy/Caddyfile and
    # deploy/nginx-sparxea-mcp.conf configs do - so if you're behind a
    # reverse proxy, set MCP_PUBLIC_HOSTNAME to the public domain clients
    # actually connect to.
    public_hostname = os.getenv("MCP_PUBLIC_HOSTNAME", "").strip()
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if public_hostname:
        allowed_hosts += [public_hostname, f"{public_hostname}:*"]
        allowed_origins += [f"https://{public_hostname}", f"http://{public_hostname}"]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )

    app = mcp.streamable_http_app(
        streamable_http_path=path, host=host, transport_security=transport_security,
        # Stateless: each request is handled independently rather than
        # requiring an initialize handshake + Mcp-Session-Id header kept
        # across requests. Every tool here is a self-contained read (no
        # server-push/resumability needed), so this trades away nothing
        # this server actually uses, while making a single curl POST -
        # or a request from any simple HTTP client - work standalone.
        # Compliant MCP clients (Claude, MCP Inspector) that still do the
        # full initialize handshake work identically either way.
        stateless_http=True,
    )

    # Optional plain-REST compatibility layer (POST <base>/<tool_name>,
    # plain JSON body of arguments) for tools/scripts that don't speak
    # MCP's JSON-RPC envelope - see rest.py. Mounted at both the root and
    # under the MCP path, since different callers configure their "base
    # URL" either way before appending the tool name.
    from .rest import build_rest_routes

    for route in build_rest_routes(prefix="") + build_rest_routes(prefix=path):
        app.router.routes.append(route)

    token = os.getenv("MCP_AUTH_TOKEN")
    if token:
        app.add_middleware(BearerTokenMiddleware, token=token)
        logger.info("HTTP transport starting with bearer-token auth enabled on %s", path)
    else:
        logger.warning(
            "MCP_AUTH_TOKEN is not set - the HTTP endpoint at %s will accept "
            "unauthenticated requests. Only do this behind a trusted network "
            "boundary (e.g. localhost + reverse proxy that adds auth, or a "
            "private network). See README.md for how to set MCP_AUTH_TOKEN.",
            path,
        )

    logger.info("Listening on http://%s:%s%s", host, port, path)
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("EA_MCP_LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
