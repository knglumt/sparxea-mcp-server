#!/usr/bin/env bash
#
# One-shot Ubuntu setup for SparxEA-MCP-Server. Installs unixODBC plus the
# ODBC driver for whichever DBMS your EA repository uses, then creates a
# Python venv (this server only ever needs one dependency set - pyodbc -
# regardless of backend).
#
# Usage:
#   chmod +x install.sh
#   ./install.sh                    # prompts you to pick a backend
#   ./install.sh --backend mariadb  # or pass one directly:
#                                    #   sqlserver-msodbc, sqlserver-freetds,
#                                    #   mysql-mariadb, postgresql,
#                                    #   oracle, firebird
#
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if [ ! -f /etc/os-release ] || ! grep -qi '^ID=ubuntu' /etc/os-release; then
  echo "This script targets Ubuntu. See README.md for other distributions."
  exit 1
fi
UBUNTU_VERSION="$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2)"

BACKEND=""
if [ "${1:-}" == "--backend" ] && [ -n "${2:-}" ]; then
  BACKEND="$2"
fi

if [ -z "$BACKEND" ]; then
  cat <<'MENU'
Which Sparx EA repository backend are you connecting to?

  1) sqlserver-msodbc   SQL Server, via Microsoft's ODBC Driver 18 (proprietary, most compatible)
  2) sqlserver-freetds  SQL Server, via FreeTDS (open source, no EULA)
  3) mysql-mariadb      MySQL or MariaDB, via the MariaDB ODBC connector (wire-compatible with both)
  4) postgresql         PostgreSQL, via the community psqlODBC driver
  5) oracle             Needs a manual driver install (Oracle-licensed download)
  6) firebird           Needs a manual driver install (not packaged in Ubuntu)

MENU
  read -rp "Enter a number [1-6]: " choice
  case "$choice" in
    1) BACKEND="sqlserver-msodbc" ;;
    2) BACKEND="sqlserver-freetds" ;;
    3) BACKEND="mysql-mariadb" ;;
    4) BACKEND="postgresql" ;;
    5) BACKEND="oracle" ;;
    6) BACKEND="firebird" ;;
    *) echo "Unrecognized choice: $choice"; exit 1 ;;
  esac
fi

echo "==> Selected backend: $BACKEND"
echo "==> [1/3] Base packages..."
$SUDO apt-get update -qq || echo "    Warning: apt-get update reported errors (possibly an unrelated third-party repo) - continuing."
$SUDO apt-get install -y curl python3-venv python3-pip unixodbc unixodbc-dev

ENV_DRIVER=""
ENV_BACKEND=""

case "$BACKEND" in
  sqlserver-msodbc)
    echo "==> [2/3] Installing Microsoft's ODBC Driver 18 for SQL Server..."
    SUPPORTED="18.04 20.04 22.04 24.04 25.10"
    if [[ "$SUPPORTED" != *"$UBUNTU_VERSION"* ]]; then
      echo "    Warning: Ubuntu $UBUNTU_VERSION isn't in Microsoft's tested list ($SUPPORTED). Continuing anyway."
    fi
    TMP_DEB="$(mktemp --suffix=.deb)"
    curl -sSL -o "$TMP_DEB" "https://packages.microsoft.com/config/ubuntu/${UBUNTU_VERSION}/packages-microsoft-prod.deb"
    $SUDO dpkg -i "$TMP_DEB"
    rm -f "$TMP_DEB"
    $SUDO apt-get update -qq || echo "    Warning: apt-get update reported errors - continuing."
    $SUDO ACCEPT_EULA=Y apt-get install -y msodbcsql18
    odbcinst -q -d -n "ODBC Driver 18 for SQL Server" || echo "    Warning: could not confirm driver registration."
    ENV_DRIVER="ODBC Driver 18 for SQL Server"
    ENV_BACKEND="sqlserver"
    ;;
  sqlserver-freetds)
    echo "==> [2/3] Installing FreeTDS (open source, no EULA)..."
    $SUDO apt-get install -y tdsodbc
    if ! odbcinst -q -d | grep -qi FreeTDS; then
      echo "    Warning: FreeTDS did not auto-register in odbcinst.ini as [FreeTDS]. Check 'odbcinst -q -d'."
    fi
    ENV_DRIVER="FreeTDS"
    ENV_BACKEND="sqlserver"
    ;;
  mysql-mariadb)
    echo "==> [2/3] Installing the MariaDB ODBC connector (works for MySQL and MariaDB)..."
    $SUDO apt-get install -y odbc-mariadb
    ENV_DRIVER="MariaDB Unicode"
    ENV_BACKEND="mariadb"
    ;;
  postgresql)
    echo "==> [2/3] Installing the community PostgreSQL ODBC driver..."
    $SUDO apt-get install -y odbc-postgresql
    ENV_DRIVER="PostgreSQL Unicode"
    ENV_BACKEND="postgresql"
    ;;
  oracle)
    cat <<'ORACLE_MSG'
    Oracle's ODBC driver isn't in Ubuntu's repos and requires accepting
    Oracle's license to download, so this can't be automated here:

      1. Download the Oracle Instant Client Basic + ODBC packages for
         Linux x86-64 from:
         https://www.oracle.com/database/technologies/instant-client/linux-x86-64-downloads.html
      2. Follow Oracle's README to run odbc_update_ini.sh, which registers
         the driver in odbcinst.ini for you.
      3. Note the exact driver name it registers (odbcinst -q -d), and use
         that as EA_DB_DRIVER below.

    This script will still set up the Python venv; come back and set
    EA_DB_DRIVER once the Oracle driver is installed.
ORACLE_MSG
    ENV_DRIVER="CHANGE_ME - see instructions above"
    ENV_BACKEND="oracle"
    ;;
  firebird)
    cat <<'FIREBIRD_MSG'
    Firebird's ODBC driver isn't packaged in Ubuntu's repos either. Get it
    from the official project:
      https://github.com/FirebirdSQL/firebird-odbc-driver/releases
    Download the Linux .tar.gz, follow its README (it ships an
    install-odbc-driver.sh helper that registers it in odbcinst.ini), and
    also install the Firebird client library:
      sudo apt-get install firebird3.0-utils
    Then note the driver name it registered (odbcinst -q -d) for EA_DB_DRIVER.

    This script will still set up the Python venv; come back and set
    EA_DB_DRIVER once the Firebird driver is installed.
FIREBIRD_MSG
    $SUDO apt-get install -y firebird3.0-utils || $SUDO apt-get install -y libfbclient2
    ENV_DRIVER="CHANGE_ME - see instructions above"
    ENV_BACKEND="firebird"
    ;;
  *)
    echo "Unknown backend: $BACKEND"
    exit 1
    ;;
esac

echo "==> [3/3] Setting up the Python virtual environment..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

if [ ! -f .env ]; then
  cp .env.example .env
  python3 - "$ENV_DRIVER" "$ENV_BACKEND" <<'PYEOF'
import re
import sys

driver, backend = sys.argv[1], sys.argv[2]
with open(".env") as f:
    content = f.read()
content = re.sub(r"^EA_DB_DRIVER=.*$", f"EA_DB_DRIVER={driver}", content, flags=re.M)
content = re.sub(r"^EA_DB_BACKEND=.*$", f"EA_DB_BACKEND={backend}", content, flags=re.M)
with open(".env", "w") as f:
    f.write(content)
PYEOF
  echo "    Created .env with EA_DB_DRIVER=$ENV_DRIVER, EA_DB_BACKEND=$ENV_BACKEND - fill in the rest."
else
  echo "    .env already exists, leaving it untouched."
fi

cat <<EOF

Setup complete for backend: $BACKEND
Next steps:
  1. Edit .env with your connection details (server, database, credentials).
  2. Verify connectivity:
       .venv/bin/python3 scripts/smoke_test.py
  3. Point your MCP client at:
       command: $SCRIPT_DIR/.venv/bin/python3
       args:    ["-m", "sparx_ea_mcp.server"]
     (see README.md for full Claude Desktop / VS Code config examples)
EOF
