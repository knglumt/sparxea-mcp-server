"""
Configuration for the SparxEA-MCP-Server.

Architecture: one driver (pyodbc), talking to whatever ODBC driver is
installed for your specific DBMS. Sparx EA itself documents this exact
approach for server-based repositories ("set up an ODBC driver to enable
connection to the repository"), so it isn't a workaround - it's how EA
expects non-native-connection setups to work anyway.

Because the actual SQL in repository.py is written in strict ANSI SQL
(FETCH FIRST instead of TOP/LIMIT, double-quoted identifiers, `?`
placeholders - which ODBC standardizes across every driver), this server
is DBMS-agnostic as long as the target database's ANSI SQL support is
recent enough: SQL Server 2012+, PostgreSQL 8.4+, Oracle 12c+, MySQL
8.0.19+/MariaDB 10.2+, Firebird 3.0+. Older versions, and engines that
never implemented the ANSI OFFSET/FETCH clause (notably SQLite), are out
of scope for this code path - see README.md.

EA_DB_BACKEND is optional metadata, not a branch into different SQL: it
only controls two small, genuinely vendor-specific things that ANSI SQL
doesn't cover - (1) SQL Server's connection-security keys (Encrypt /
TrustServerCertificate), and (2) issuing `SET SESSION sql_mode =
ANSI_QUOTES` right after connecting to MySQL/MariaDB, since MySQL treats
double-quoted strings as string literals unless that mode is enabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Backend(str, Enum):
    SQLSERVER = "sqlserver"
    MYSQL = "mysql"
    MARIADB = "mariadb"
    POSTGRESQL = "postgresql"
    ORACLE = "oracle"
    FIREBIRD = "firebird"
    OTHER = "other"  # any other ANSI-SQL DBMS reachable via ODBC


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: Optional[int]) -> Optional[int]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


@dataclass(frozen=True)
class EAConfig:
    driver: str                      # ODBC driver name, exactly as in `odbcinst -q -d`
    server: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None   # database name, or a file path for file-based ODBC drivers
    username: Optional[str] = None
    password: Optional[str] = None
    connect_timeout: int = 10
    row_limit: int = 200

    backend: Backend = Backend.OTHER  # informational only, see module docstring

    # SQL Server specific connection-string keys (only added when backend == sqlserver)
    trusted_connection: bool = False
    encrypt: bool = True
    trust_server_certificate: bool = True

    # Raw passthrough appended verbatim to the ODBC connection string, for
    # any driver-specific key this config doesn't already special-case
    # (e.g. "SSLMode=require" for some PostgreSQL driver builds).
    extra_params: Optional[str] = None

    def connection_string(self) -> str:
        parts = [f"DRIVER={{{self.driver}}}"]
        if self.server:
            parts.append(f"SERVER={self.server}")
        if self.port:
            parts.append(f"PORT={self.port}")
        if self.database:
            parts.append(f"DATABASE={self.database}")

        if self.trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            if self.username:
                parts.append(f"UID={self.username}")
            if self.password is not None:
                parts.append(f"PWD={self.password}")

        if self.backend == Backend.SQLSERVER and "freetds" not in self.driver.lower():
            parts.append(f"Encrypt={'yes' if self.encrypt else 'no'}")
            parts.append(f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'}")
            parts.append("ApplicationIntent=ReadOnly")
        elif self.backend == Backend.SQLSERVER:
            # FreeTDS uses a different key/value for encryption and has no
            # TrustServerCertificate equivalent (see README).
            parts.append(f"Encryption={'require' if self.encrypt else 'off'}")

        if self.extra_params:
            parts.append(self.extra_params)

        return ";".join(parts)


_config_instance: Optional[EAConfig] = None


def get_config(force_reload: bool = False) -> EAConfig:
    global _config_instance
    if _config_instance is None or force_reload:
        driver = os.getenv("EA_DB_DRIVER")
        if not driver:
            raise RuntimeError(
                "EA_DB_DRIVER is required - set it to the exact name of an "
                "installed ODBC driver, as shown by `odbcinst -q -d` "
                "(e.g. 'ODBC Driver 18 for SQL Server', 'FreeTDS', "
                "'MariaDB Unicode', 'PostgreSQL Unicode')."
            )
        try:
            backend = Backend(os.environ.get("EA_DB_BACKEND", "other").strip().lower())
        except ValueError as exc:
            valid = ", ".join(b.value for b in Backend)
            raise RuntimeError(
                f"EA_DB_BACKEND={os.environ.get('EA_DB_BACKEND')!r} is not recognized. "
                f"Valid values: {valid}."
            ) from exc

        _config_instance = EAConfig(
            driver=driver,
            server=os.getenv("EA_DB_SERVER"),
            port=_int_env("EA_DB_PORT", None),
            database=os.getenv("EA_DB_NAME"),
            username=os.getenv("EA_DB_USER"),
            password=os.getenv("EA_DB_PASSWORD"),
            connect_timeout=_int_env("EA_DB_CONNECT_TIMEOUT", 10),
            row_limit=_int_env("EA_MCP_ROW_LIMIT", 200),
            backend=backend,
            trusted_connection=_bool_env("EA_DB_TRUSTED_CONNECTION", False),
            encrypt=_bool_env("EA_DB_ENCRYPT", True),
            trust_server_certificate=_bool_env("EA_DB_TRUST_SERVER_CERT", True),
            extra_params=os.getenv("EA_DB_EXTRA_PARAMS"),
        )
    return _config_instance
