# SparxEA-MCP-Server

A **read-only** [MCP](https://modelcontextprotocol.io) server for Sparx
Systems Enterprise Architect repositories, written in Python, built to run
on **Ubuntu**. It connects **directly to the EA project database** - no
running copy of EA.exe, no Windows, no .NET runtime required.

## How it connects: one driver, any DBMS EA supports

Sparx EA can store a repository in several different DBMSs: SQL Server,
MySQL/MariaDB, PostgreSQL, Oracle, Firebird, SQLite, or MS Access. This
server connects to all of the server-based ones via **ODBC** (`pyodbc`) -
which is exactly what Sparx EA's own documentation recommends for
server-based repositories that aren't using its "Native Connection":
*"set up an ODBC driver to enable connection to the repository."*

Because every query in `repository.py` is written in strict **ANSI
SQL:2008** - `FETCH FIRST n ROWS ONLY` instead of vendor-specific `TOP`/
`LIMIT`, `?` placeholders (the ODBC standard, honored by every driver
regardless of the DBMS's native paramstyle), double-quoted identifiers for
reserved words - this server is DBMS-agnostic by construction rather than
needing a different code path per backend. You only ever install one
Python dependency (`pyodbc`); which *database* you're pointed at is
purely a matter of which ODBC driver is registered and what's in `.env`.

**Verified against real servers**, not just assumed: this was tested
end-to-end against live PostgreSQL 16 and MariaDB 10.11 instances (in
addition to SQL Server), catching real cross-backend differences along
the way - see [Known cross-DBMS quirks](#known-cross-dbms-quirks-already-handled).

### What this means isn't supported

- **SQLite (`.qea`/`.qeax`)**: SQLite has no `FETCH FIRST` clause, so it
  can't run this server's queries as written. If your model is a local
  SQLite file, either use EA's Project Transfer feature to move it to one
  of the DBMSs above first, or ask for a SQLite-specific fork of
  `repository.py` (it's a small, mechanical change - swap `FETCH FIRST n
  ROWS ONLY` for `LIMIT n`).
- **MS Access (`.eap`/`.eapx`, Jet/ACE)**: there's no maintained Linux ODBC
  driver for Jet with reliable SQL support. If you're on Access, use EA's
  Project Transfer feature to move to one of the supported DBMSs.
- Live-EA-session tools (opening diagrams in the EA UI, selecting
  elements in the Browser, etc.) - there's no running EA.exe to drive.
  This server only implements the *read/browse* side.

## Requirements

- **Ubuntu** (22.04/24.04 LTS primarily tested; the general approach works
  on any Linux with unixODBC)
- Python 3.10+
- unixODBC, plus the ODBC driver for **your specific DBMS** (see below)
- A DB login with read-only access to the EA repository database

### Installing the right ODBC driver

| Your DBMS | Ubuntu package | Driver name for `.env` |
|---|---|---|
| SQL Server (Microsoft's driver) | `msodbcsql18` (from Microsoft's apt repo) | `ODBC Driver 18 for SQL Server` |
| SQL Server (open-source alternative) | `tdsodbc` | `FreeTDS` |
| MySQL or MariaDB | `odbc-mariadb` | `MariaDB Unicode` |
| PostgreSQL | `odbc-postgresql` | `PostgreSQL Unicode` |
| Oracle | manual (Oracle-licensed download) | varies - see below |
| Firebird | manual (not packaged for Ubuntu) | varies - see below |

`./install.sh` automates the first four. For Oracle and Firebird, `install.sh`
prints the manual steps (both require downloading a driver from outside
Ubuntu's package repos - Oracle's due to licensing, Firebird's because it
simply isn't packaged there).

After installing any driver, confirm it registered:

```bash
odbcinst -q -d
```

The bracketed name shown (e.g. `[MariaDB Unicode]`) is what goes in
`EA_DB_DRIVER`.

## Setup

### Option A: automated

```bash
cd sparxea-mcp-server
chmod +x install.sh
./install.sh                    # prompts you to pick a backend
# or: ./install.sh --backend postgresql
```

This installs unixODBC + the matching driver, creates a `.venv`, installs
the project into it, and writes a `.env` from `.env.example` with
`EA_DB_DRIVER`/`EA_DB_BACKEND` pre-filled for your choice. Safe to re-run.

### Option B: manual

```bash
sudo apt-get update
sudo apt-get install -y unixodbc unixodbc-dev
sudo apt-get install -y odbc-mariadb      # or odbc-postgresql, or tdsodbc, etc.

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# edit .env: EA_DB_DRIVER, EA_DB_SERVER, EA_DB_NAME, EA_DB_USER, EA_DB_PASSWORD
```

### Verify

```bash
.venv/bin/python3 scripts/smoke_test.py
```

Prints the live DBMS name/version (via ODBC's own `SQLGetInfo`, not a
vendor-specific query - so this line works identically on every backend),
a model overview, and the top-level packages. Fix any errors here before
wiring up an MCP client.

## Running

```bash
python3 -m sparx_ea_mcp.server
```

Or, after `pip install -e .`:

```bash
sparxea-mcp-server
```

Either way the server speaks MCP over **STDIO**, the same transport the
official Windows add-in uses.

## Connecting an MCP client

### Claude Desktop / Claude Code (`claude_desktop_config.json` or `.mcp.json`)

```json
{
  "mcpServers": {
    "Enterprise Architect": {
      "command": "/absolute/path/to/sparxea-mcp-server/.venv/bin/python3",
      "args": ["-m", "sparx_ea_mcp.server"],
      "env": {
        "EA_DB_DRIVER": "MariaDB Unicode",
        "EA_DB_BACKEND": "mariadb",
        "EA_DB_SERVER": "db-host.example.com",
        "EA_DB_NAME": "ea_repository",
        "EA_DB_USER": "ea_reader",
        "EA_DB_PASSWORD": "change-me"
      }
    }
  }
}
```

(Or omit `env` and rely on the `.env` file next to the project - `server.py`
loads it automatically via `python-dotenv`.)

### Claude Desktop, connecting to a private-network HTTP deployment

If the server is already running in HTTP mode on a machine you can reach
over your LAN/VPN but that has **no public domain and no TLS** (e.g. a
bare internal IP like `http://10.0.0.1:8765/mcp`), Claude Desktop's
built-in "Custom Connector" UI (Customize → Connectors) **will not work**
for this - it always connects from Anthropic's cloud infrastructure, not
your device, so a private IP is simply unreachable that way, even from
Claude Desktop running on the same network.

The fix: bridge it through [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
in `claude_desktop_config.json`, which runs as a local process on your
machine and does the actual HTTP call from there - that's real local
network traffic, not Anthropic's cloud:

```json
{
  "mcpServers": {
    "Enterprise Architect": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://10.0.0.1:8765/mcp",
        "--allow-http",
        "--header",
        "Authorization:${AUTH_HEADER}"
      ],
      "env": {
        "AUTH_HEADER": "Bearer <your MCP_AUTH_TOKEN value>"
      }
    }
  }
}
```

A few details here that matter (each was a real failure mode when
setting this up):

- **`-y`** is required - without it, `npx`'s interactive first-run
  confirmation prompt has nothing to answer it (Claude Desktop launches
  this headless), and the connection just hangs and then reports
  "Server disconnected" with no useful detail.
- **`--allow-http`** is required for anything other than `localhost` -
  `mcp-remote` refuses plain HTTP to any other host by default as a
  safety measure (`Non-HTTPS URLs are only allowed for localhost or when
  --allow-http flag is provided`). This is fine to accept for a trusted
  internal network; never do this for a public address.
- **The env var name must match the `${...}` placeholder exactly** -
  `${AUTH_HEADER}` in `args` only resolves if `env` defines `AUTH_HEADER`,
  not some other name.
- **No space around the `:`** in `Authorization:${AUTH_HEADER}` - Claude
  Desktop on Windows has a known bug where spaces inside `args` values
  get mangled when it invokes `npx`. Put the space inside the *env var's
  value* instead (`"Bearer <token>"`), not in the arg string.

To debug this independent of Claude Desktop (which hides the real error
behind a generic "Server disconnected"), run the exact same command in a
terminal:

```bash
npx -y mcp-remote http://10.0.0.1:8765/mcp --allow-http --header "Authorization:Bearer <your token>"
```

`Connected to remote server using StreamableHTTPClientTransport` /
`Proxy established successfully` means it works - restart Claude Desktop
and it should too. Any other output (auth rejection, connection refused,
etc.) is the actual problem, uncut.

### VS Code (`.vscode/mcp.json`)

```json
{
  "servers": {
    "Enterprise Architect": {
      "command": "/absolute/path/to/sparxea-mcp-server/.venv/bin/python3",
      "args": ["-m", "sparx_ea_mcp.server"]
    }
  }
}
```

## Hosting on a server

By default this server speaks MCP over **STDIO**: a client (Claude
Desktop, Claude Code) launches it as a local subprocess. That's all you
need if the assistant runs on the same Ubuntu box as the database, or if
you're fine using Claude only from that machine.

To make it reachable remotely - so you can use it from Claude.ai's Custom
Connectors on any device, or share it with a team - run it as a
persistent **HTTP** service instead. Three things change from local use:

1. **Transport**: set `MCP_TRANSPORT=http` (env var already in `.env.example`).
2. **Process supervision**: run it under systemd so it survives reboots
   and restarts on crash (`deploy/sparxea-mcp-server.service`).
3. **A reverse proxy for HTTPS**: Claude's custom connectors require
   HTTPS, and Claude connects to your server *from Anthropic's cloud, not
   from your device* - so the server must be reachable on the public
   internet (or you allowlist Anthropic's IP ranges for a private-network
   setup; see [Anthropic's network requirements
   doc](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
   if you need that route instead).

### 1. Enable HTTP transport

In `.env`:

```bash
MCP_TRANSPORT=http
MCP_HTTP_HOST=127.0.0.1   # bind locally; the reverse proxy is what's public
MCP_HTTP_PORT=8765
MCP_AUTH_TOKEN=$(openssl rand -hex 32)   # put the generated value in .env, not this command
MCP_PUBLIC_HOSTNAME=mcp.your-domain.example.com   # the domain clients will use
```

`MCP_AUTH_TOKEN` is a shared secret: any request to `/mcp` must send
`Authorization: Bearer <token>` or get a 401. This is the same style of
auth Claude's custom connector UI has a dedicated field for ("If your
server's documentation shows `Authorization: Bearer YOUR_TOKEN`, enter
`Bearer` followed by your token"). **Never** run with `MCP_AUTH_TOKEN`
unset on a port reachable from the internet.

`MCP_PUBLIC_HOSTNAME` matters for a subtler reason: the MCP SDK's
built-in DNS-rebinding protection only allows `Host`/`Origin` headers
matching `127.0.0.1`/`localhost` by default. A reverse proxy forwards the
*original* public hostname, which would otherwise get every request
rejected with `421 Invalid Host header` - setting this env var adds your
real domain to the allow-list without disabling the protection for
anything else (arbitrary hosts still get rejected).

### 2. Run it as a systemd service

```bash
sudo mkdir -p /opt/sparxea-mcp-server
sudo cp -r . /opt/sparxea-mcp-server   # or however you deploy code to this box
cd /opt/sparxea-mcp-server
sudo python3 -m venv .venv
sudo .venv/bin/pip install -e .

sudo useradd --system --no-create-home --shell /usr/sbin/nologin sparxea-mcp
sudo chown -R sparxea-mcp:sparxea-mcp /opt/sparxea-mcp-server

sudo cp deploy/sparxea-mcp-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sparxea-mcp-server
sudo systemctl status sparxea-mcp-server
sudo journalctl -u sparxea-mcp-server -f   # tail logs
```

The unit file runs the server under a dedicated unprivileged user with
`ProtectSystem=strict`/`ProtectHome=true` (it never needs to write
anywhere on disk), and restarts it automatically on failure.

### 3. Put a reverse proxy in front for HTTPS

Pick one - both configs are in `deploy/`, each with install steps in
comments at the top:

- **`deploy/Caddyfile`** - simplest option, automatic Let's Encrypt
  certificate and renewal with almost no config.
- **`deploy/nginx-sparxea-mcp.conf`** - if you already run nginx.

Either way, edit the domain name in the config first, and make sure DNS
for that domain already points at this server's public IP.

### 4. Open the firewall

```bash
sudo ufw allow 80/tcp    # for Let's Encrypt's HTTP challenge
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

Notice port `8765` (or whatever `MCP_HTTP_PORT` is) is **not** opened -
only the reverse proxy is internet-facing; it forwards to the app over
localhost.

### 5. Connect from Claude

In Claude.ai: **Customize → Connectors → + → Add custom connector**,
enter `https://mcp.your-domain.example.com/mcp`, open **Advanced
settings**, and under the bearer-token field enter `Bearer <your
MCP_AUTH_TOKEN value>` (the literal word `Bearer`, a space, then the
token).

### Verifying it works

```bash
curl -i -X POST https://mcp.your-domain.example.com/mcp \
  -H "Authorization: Bearer <your token>" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

A `200` with a JSON-RPC result listing the 14 tools means everything is
wired up correctly. `401` means the token's wrong; `421` means
`MCP_PUBLIC_HOSTNAME` doesn't match the domain in the URL you're hitting.

### Calling a specific tool directly

MCP's actual protocol has no per-tool REST URL - it's one JSON-RPC
endpoint reached via `POST`, using the `tools/call` method with the
tool's name and arguments. This server runs the HTTP transport in
**stateless mode**, so - unlike the MCP spec's default session-based flow
- a single request works standalone, with no `initialize` handshake or
`Mcp-Session-Id` header required first:

```bash
curl -s -X POST https://mcp.your-domain.example.com/mcp \
  -H "Authorization: Bearer <your token>" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
          "name": "get_root_packages",
          "arguments": {}
        }
      }'
```

Swap `"name"` and `"arguments"` for any of the 14 tools listed below - e.g.
`{"name": "find_elements_by_name", "arguments": {"name": "Customer"}}`.

For interactively browsing tools/arguments instead of hand-writing JSON,
use [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
(`npx @modelcontextprotocol/inspector`, transport type "Streamable HTTP",
your server URL, and the same bearer token in its auth field).

### Plain-REST compatibility routes (for non-MCP tool testers)

Some internal API testers/dashboards assume a classic REST shape - one
`POST` endpoint per tool, a plain JSON object of arguments in, a plain
JSON object out - rather than MCP's JSON-RPC envelope above. For those,
`sparx_ea_mcp/rest.py` mounts the exact same 14 tools at
`POST <base>/<tool_name>`, at both the server root and under the MCP path
(so it works whichever base URL such a tool was configured with):

```bash
curl -s -X POST https://mcp.your-domain.example.com/get_root_packages \
  -H "Authorization: Bearer <your token>" \
  -H "Content-Type: application/json" \
  -d '{}'
# identical result via the other mount point:
curl -s -X POST https://mcp.your-domain.example.com/mcp/get_root_packages \
  -H "Authorization: Bearer <your token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Arguments go directly in the body - no `"arguments"` wrapper, no
`jsonrpc`/`method` envelope:

```bash
curl -s -X POST https://mcp.your-domain.example.com/find_elements_by_name \
  -H "Authorization: Bearer <your token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Customer"}'
```

The response is always `{"result": ...}`, or `{"error": "..."}` with a
4xx/5xx status on failure. This is **not part of the MCP spec** and real
MCP clients (Claude, MCP Inspector) never use it - it exists purely for
tooling that expects REST. The bearer-token auth covers these routes
exactly like the real `/mcp` endpoint, and adding them changes nothing
about `/mcp` itself - existing Claude Desktop/`mcp-remote` connections
are unaffected by enabling or using this layer.

## Tool reference

| Tool | Description |
|---|---|
| `get_model_overview` | Repo-wide stats (packages/elements/diagrams/connectors counts, top element types) - good starting point |
| `get_root_packages` | Top-level packages, as shown at the root of the EA Browser tree |
| `find_packages_by_name` | Search packages by name |
| `get_package_contents` | A package's metadata plus its direct subpackages, elements, and diagrams (one level deep) |
| `find_elements_by_name` | Search elements (classes, interfaces, actors, use cases, ...) by name |
| `get_elements_information` | Full detail for one element: attributes, operations, tagged values |
| `find_element_in_diagrams` | Every diagram that displays a given element |
| `export_element_linked_documents` | Linked/embedded documents attached to an element |
| `get_connectors_information` | Every connector (relationship) attached to an element, either end |
| `find_diagrams_by_name` | Search diagrams by name |
| `get_diagrams_information` | A diagram's elements and the connectors between them |
| `get_diagram_image` | **Approximate** schematic SVG rebuilt from stored coordinates - not EA's own renderer |
| `search_model` | One free-text search across packages/elements/diagrams |
| `check_connection` | Reports the live DBMS name/version via ODBC, plus table visibility |

This is a **read-only** server: nothing that requires a live, running EA
session (opening diagrams, selecting elements in the Browser, etc.) or
that writes to the repository is implemented - see "How it connects"
above for why.

### `get_diagram_image` caveat

Reconstructs a plain box-and-line SVG from `t_diagramobjects`/`t_connector`
coordinates - useful for a rough layout sense, but EA's own notation
styling (UML/BPMN/ArchiMate shapes, colors, fonts) isn't reproduced. Treat
`get_diagrams_information`'s structured data as the source of truth.

## Docker

A prebuilt, ODBC-ready image is the fastest path to a working deployment
- no manual driver installs, no venv management.

```bash
docker build -t sparxea-mcp-server .
# Or skip Microsoft's SQL Server driver (its EULA) if you don't need it:
docker build --build-arg INSTALL_MSODBC=false -t sparxea-mcp-server .
```

One image covers SQL Server (both Microsoft's driver and FreeTDS), MySQL,
MariaDB, and PostgreSQL - which one you use is just the `EA_DB_*` env vars
at run time, not a different build. Oracle and Firebird still need their
driver added on top (same reasons as bare-metal - see Requirements above);
extend this Dockerfile with the same manual steps `install.sh` prints for
those two.

```bash
cp .env.example .env   # fill in EA_DB_* and MCP_AUTH_TOKEN - see earlier sections
docker run -d --name sparxea-mcp --env-file .env -p 127.0.0.1:8765:8765 sparxea-mcp-server
```

Or with Compose:

```bash
docker compose up -d --build
docker compose logs -f
```

### Why `MCP_HTTP_HOST=0.0.0.0` inside the container (not `127.0.0.1`)

Everywhere else in this README, binding `127.0.0.1` and putting a reverse
proxy in front is the recommended pattern. Inside a container that still
holds - it's just one layer removed: `0.0.0.0` is what Docker's networking
needs in order to route traffic *into* the container at all (a container
process bound to `127.0.0.1` is only reachable from inside that same
container, invisible even to `docker run -p`). The safety property is
preserved by the **host-side** half of the port mapping instead:
`-p 127.0.0.1:8765:8765` means the port is still only reachable from the
Docker host itself, not the internet - your reverse proxy on the host
(`deploy/Caddyfile`/`deploy/nginx-sparxea-mcp.conf`) is still what's
actually internet-facing, exactly as in the bare-metal setup. Don't change
that first `127.0.0.1:` to `0.0.0.0:` in the port mapping unless you
understand you're removing that boundary.

`Dockerfile` sets `MCP_TRANSPORT=http` as its default (containers are
inherently about remote hosting - nothing runs a container as a locally-
spawned STDIO subprocess), overridable via `.env` like everything else.

### Publishing to a registry from Bitbucket Pipelines

`bitbucket-pipelines.yml` is included: every push builds the image and
runs the exact same smoke test as the manual verification steps earlier
(reject unauthenticated, accept a real MCP handshake with the token) -
using only the open-source drivers, so CI doesn't depend on reaching
Microsoft's package server or accepting its EULA. Pushing a `v*` tag also
builds and pushes to a registry, once you set these as **Repository
variables** (Repository settings → Pipelines → Repository variables in
Bitbucket; mark `DOCKER_PASSWORD` **Secured**):

| Variable | Example |
|---|---|
| `DOCKER_REGISTRY` | `docker.io`, or `<account>.dkr.ecr.<region>.amazonaws.com` |
| `DOCKER_IMAGE` | `your-org/sparxea-mcp-server` |
| `DOCKER_USERNAME` | your registry username |
| `DOCKER_PASSWORD` | a registry access token, not your account password |

Bitbucket itself doesn't host container images, so you still need a
registry somewhere - Docker Hub, ECR, ACR, GHCR, or a self-hosted one all
work the same way here.

### Getting the code onto Bitbucket

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://bitbucket.org/<your-workspace>/<your-repo>.git
git push -u origin main
```

`.env` is already excluded via `.gitignore` - double-check `git status`
shows it untracked before your first push. Nothing in this repo needs
secrets baked in; every credential is supplied at deploy time via `.env`
or Bitbucket's repository variables.

## Known cross-DBMS quirks (already handled)

Testing against real PostgreSQL and MariaDB servers surfaced genuine
differences that are easy to miss if you only test against one backend:

- **Column name casing**: PostgreSQL's ODBC driver folds unaliased output
  column names to lowercase (`Object_Type` → `object_type`); other
  backends preserve the case as written. Every query explicitly aliases
  every output column with a quoted alias (`AS "Object_Type"`) to pin the
  exact casing everywhere, so tool output is identical regardless of
  backend.
- **`LIKE` case sensitivity**: case-sensitive by default on PostgreSQL,
  case-insensitive by default on SQL Server/MySQL. All substring search
  wraps both sides in `LOWER()` (plain ANSI SQL) for consistent behavior.
- **Reserved words**: MySQL/MariaDB treat double-quoted text as a string
  literal unless `ANSI_QUOTES` mode is enabled - `db.py` sets this
  automatically right after connecting when `EA_DB_BACKEND` is `mysql` or
  `mariadb`.
- **Identifier case-folding for table/column *source* names**: Oracle and
  Firebird fold unquoted identifiers to UPPERCASE by default, unlike
  SQL Server/MySQL. If your Oracle/Firebird schema was created without
  quoting, and doesn't match the names in `repository.py`'s docstring,
  `scripts/smoke_test.py` will surface a clear driver error naming the
  problem so you can adjust.

## Security notes

- Only ever issues `SELECT` statements; `db.py` actively rejects any
  statement containing `INSERT`/`UPDATE`/`DELETE`/`DROP`/etc. as
  defense-in-depth, even though nothing in the codebase constructs such
  statements.
- Use a DB login scoped to read-only access on the EA repository database.
- All queries are parameterized; user-supplied search text is never
  concatenated into SQL.
- Every list-returning tool is capped by `EA_MCP_ROW_LIMIT` regardless of
  what a client requests.
- If hosting over HTTP, `MCP_AUTH_TOKEN` is checked with a constant-time
  comparison (`hmac.compare_digest`) to avoid timing side-channels, and
  should be treated like any other credential (long, random, not committed
  to version control - `.env` is already in `.gitignore`).

## Project layout

```
Dockerfile               Ubuntu 24.04 image w/ every open-source ODBC driver + Microsoft's
docker-compose.yml        Convenience wrapper around docker build/run
.dockerignore             Keeps .env and other secrets out of the image
bitbucket-pipelines.yml   CI: build + smoke-test every push; publish on v* tags
install.sh       Ubuntu setup: unixODBC + your chosen driver + Python venv
deploy/
  sparxea-mcp-server.service   systemd unit for persistent HTTP hosting (bare-metal)
  Caddyfile                    reverse proxy w/ automatic HTTPS (recommended)
  nginx-sparxea-mcp.conf       reverse proxy alternative (+ certbot)
sparx_ea_mcp/
  config.py      ODBC connection-string builder from environment variables
  db.py          pyodbc connection handling, read-only guard, ANSI_QUOTES hook
  repository.py  All SQL (ANSI SQL:2008) against the EA schema
  svg.py         Schematic SVG renderer for get_diagram_image
  auth.py        Bearer-token middleware for the HTTP transport
  rest.py        Optional plain-REST compat routes (POST <base>/<tool_name>)
  server.py      MCP tool definitions; STDIO and HTTP entry points
scripts/
  smoke_test.py  Standalone connectivity check
```

## Extending

To add a new read tool: add a function to `sparx_ea_mcp/repository.py`
that runs a parameterized, ANSI-SQL `SELECT` via `db.run_query`/
`run_query_one` (remember to alias every output column in double quotes),
then wrap it with `@mcp.tool()` in `sparx_ea_mcp/server.py` with a clear
docstring - the docstring is what the LLM client reads to decide when to
call it.
