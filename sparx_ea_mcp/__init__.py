"""
SparxEA-MCP-Server - a read-only Model Context Protocol (MCP) server for
Sparx Systems Enterprise Architect repositories, talking directly to the
project database instead of driving a running copy of EA.exe.

Unlike Sparx Systems' own MCP Server for Enterprise Architect (Windows-only,
requires a running EA.exe instance and its COM Automation Interface), this
server connects straight to the EA repository's database over the network
(or opens a local SQLite .qea/.qeax file directly), so it runs anywhere
Python runs - including Linux, macOS, and containers.

Supported repository backends (see EA_DB_BACKEND in config.py): SQL
Server, MySQL/MariaDB, PostgreSQL, Oracle, Firebird, and SQLite. MS Access
(.eap/.eapx, Jet/ACE) is not supported - see README.md for why.

Because there is no running EA instance to drive, only the *read* /
*informational* side of the official tool surface is implemented (browsing
packages, elements, diagrams, connectors, tagged values and linked
documents). There is no live EA session to interact with, so tools like
`open_diagrams`, `select_element_in_browser`, `get_opened_diagrams` or any
model-editing tool are intentionally out of scope.
"""

__version__ = "2.0.0"
