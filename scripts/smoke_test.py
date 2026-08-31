#!/usr/bin/env python3
"""
Quick standalone check that the DB connection and a few core queries work,
independent of any MCP client. Run this first when setting things up:

    python3 scripts/smoke_test.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sparx_ea_mcp import repository as repo
from sparx_ea_mcp.config import get_config
from sparx_ea_mcp.db import check_connection


def main() -> int:
    try:
        cfg = get_config()
    except Exception as exc:  # noqa: BLE001
        print(f"Configuration error: {exc}")
        print("Check your .env file - see .env.example for the fields your EA_DB_BACKEND needs.")
        return 1

    print(f"1) Checking database connection (driver: {cfg.driver}, backend: {cfg.backend.value})...")
    try:
        info = check_connection()
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {exc}")
        print(
            "   Common causes: wrong EA_DB_SERVER/EA_DB_PORT/EA_DB_NAME/"
            "EA_DB_USER/EA_DB_PASSWORD in .env, EA_DB_DRIVER not matching "
            "a name in `odbcinst -q -d`, or the host being unreachable on "
            "its port. See README's Requirements section for your DBMS."
        )
        return 1
    print("   OK -", info)

    print("2) Fetching model overview...")
    overview = repo.get_model_overview()
    print(json.dumps(overview, indent=2))

    print("3) Fetching root packages...")
    roots = repo.get_root_packages()
    for pkg in roots[:10]:
        print(f"   - [{pkg['Package_ID']}] {pkg['Name']}")
    if not roots:
        print("   (none found - is this an empty/new repository?)")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
