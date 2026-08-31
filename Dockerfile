# syntax=docker/dockerfile:1
#
# SparxEA-MCP-Server container image.
#
# Base is ubuntu:24.04 (not a slim/alpine Python image) on purpose: this
# project's whole ODBC-driver story - and everything verified in its
# README - targets Ubuntu specifically, and musl-based Alpine has known
# compatibility issues with unixODBC/pyodbc.
#
# Includes ODBC drivers for every backend Sparx EA supports server-side
# except Oracle/Firebird (both require a manually-downloaded, license- or
# packaging-gated driver - see README's "Docker" section for how to add
# either on top of this image). One image works for SQL Server, MySQL,
# MariaDB, and PostgreSQL; which one you actually use is just an EA_DB_*
# env var choice at `docker run` time, not a different build.
#
# Build:
#   docker build -t sparxea-mcp-server .
#   # Skip Microsoft's driver (EULA) if you only need the open-source ones:
#   docker build --build-arg INSTALL_MSODBC=false -t sparxea-mcp-server .
#
# Run (see README's "Docker" section for the full explanation of why
# MCP_HTTP_HOST must be 0.0.0.0 here even though bare-metal deployments
# use 127.0.0.1):
#   docker run -d --name sparxea-mcp \
#     --env-file .env \
#     -p 127.0.0.1:8765:8765 \
#     sparxea-mcp-server

FROM ubuntu:24.04

ARG INSTALL_MSODBC=true
ENV DEBIAN_FRONTEND=noninteractive

# --- System packages: unixODBC + every open-source driver, always ---
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        python3 \
        python3-pip \
        python3-venv \
        unixodbc \
        unixodbc-dev \
        tdsodbc \
        odbc-mariadb \
        odbc-postgresql \
    && rm -rf /var/lib/apt/lists/*

# --- Microsoft's ODBC Driver 18 for SQL Server (proprietary, EULA) ---
# Opt out with --build-arg INSTALL_MSODBC=false if you only need FreeTDS/
# MySQL/PostgreSQL. Hardcoded to 24.04 since that's this image's fixed
# base (see install.sh for the general, host-version-detecting version of
# this same install for bare-metal Ubuntu).
RUN if [ "$INSTALL_MSODBC" = "true" ]; then \
        curl -sSL -o /tmp/packages-microsoft-prod.deb \
            https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb \
        && dpkg -i /tmp/packages-microsoft-prod.deb \
        && rm -f /tmp/packages-microsoft-prod.deb \
        && apt-get update \
        && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
        && rm -rf /var/lib/apt/lists/* ; \
    fi

# --- App ---
WORKDIR /app

# Copy dependency manifests first so the pip install layer only rebuilds
# when dependencies actually change, not on every source edit.
COPY pyproject.toml requirements.txt ./
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY sparx_ea_mcp/ ./sparx_ea_mcp/
RUN pip install --break-system-packages --no-cache-dir -e .

# Runs as an unprivileged user - this server never writes to the EA
# repository or to disk at all, so it doesn't need root or a home dir.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin sparxea-mcp
USER sparxea-mcp

# Container deployments are inherently "remote hosting", so default the
# transport to http here even though the library's own default (used for
# local STDIO installs) is stdio. 0.0.0.0 (not 127.0.0.1!) is required so
# Docker's networking can actually route to this port from outside the
# container - see README for why that's still safe (only the host-side
# port mapping, not this bind address, controls what's internet-facing).
ENV MCP_TRANSPORT=http
ENV MCP_HTTP_HOST=0.0.0.0
ENV MCP_HTTP_PORT=8765
ENV MCP_HTTP_PATH=/mcp

EXPOSE 8765

ENTRYPOINT ["python3", "-m", "sparx_ea_mcp.server"]
