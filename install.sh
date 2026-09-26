#!/usr/bin/env bash
# Install apollo-charting.
#
# Creates the Python environment for the MCP server and installs the Node
# render dependencies (React, Recharts, Playwright) plus a headless Chromium.
# Safe to re-run: every step is idempotent.
#
# Usage:
#   ./install.sh                 # server + render dependencies
#   ./install.sh --with-deps     # also install OS packages Chromium needs (Linux; may need sudo)
#   ./install.sh --skip-node     # Python environment only
#   ./install.sh --skip-python   # render dependencies only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_DEPS=0
SKIP_NODE=0
SKIP_PYTHON=0
MIN_NODE_MAJOR=20

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --with-deps) WITH_DEPS=1 ;;
    --skip-node) SKIP_NODE=1 ;;
    --skip-python) SKIP_PYTHON=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'error: unknown option: %s\n\n' "$arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'error: %s is required but was not found on PATH\n' "$1" >&2
    exit 1
  fi
}

if [ "$SKIP_PYTHON" -eq 0 ]; then
  need uv
  printf '\n==> Python environment (uv sync)\n'
  (cd "$ROOT" && uv sync)
fi

if [ "$SKIP_NODE" -eq 0 ]; then
  need node
  need npm
  node_major="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$node_major" -lt "$MIN_NODE_MAJOR" ]; then
    printf 'error: Node %s+ is required (found %s)\n' "$MIN_NODE_MAJOR" "$(node -v)" >&2
    exit 1
  fi
  printf '\n==> Node dependencies (npm ci)\n'
  (cd "$ROOT" && npm ci)
  printf '\n==> Render bundle (esbuild)\n'
  (cd "$ROOT" && node scripts/build.mjs)
  printf '\n==> Chromium (Playwright)\n'
  if [ "$WITH_DEPS" -eq 1 ]; then
    (cd "$ROOT" && npx playwright install --with-deps chromium)
  else
    (cd "$ROOT" && npx playwright install chromium)
  fi
fi

printf '\napollo-charting is installed.\n\n'
printf '  stdio (default):  uv run --directory "%s" apollo-charting\n' "$ROOT"
printf '  streamable HTTP:  uv run --directory "%s" apollo-charting --transport streamable-http --port 8000\n' "$ROOT"
printf '  inspector:        uv run --directory "%s" mcp dev src/apollo_charting/server.py\n' "$ROOT"
