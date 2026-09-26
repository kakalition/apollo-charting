#!/usr/bin/env python3
"""HTTP-transport smoke test for apollo-charting.

Starts the streamable-HTTP server on a free localhost port and drives it with
the MCP HTTP client, proving the tool trio is reachable over the network API
and not just stdio/in-process. Self-skips when the client transport is missing.
"""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PASS = 0
FAIL = 0


def check(description: str, actual, expected) -> None:
    global PASS, FAIL
    if actual == expected:
        PASS += 1
    else:
        FAIL += 1
        print("FAIL: %s: expected [%r] got [%r]" % (description, expected, actual), file=sys.stderr)


def ok(description: str, condition: bool) -> None:
    check(description, bool(condition), True)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, proc: subprocess.Popen, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


async def run_client(url: str) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(tool.name for tool in (await session.list_tools()).tools)
            check("http tool trio", tools, ["chart_component", "render_chart", "validate_spec"])

            spec = {
                "chart": "bar",
                "data": [{"m": "A", "v": 1}],
                "x": {"key": "m"},
                "series": [{"key": "v"}],
            }
            result = await session.call_tool("validate_spec", {"spec": spec})
            text = "".join(
                block.text for block in result.content if getattr(block, "type", None) == "text"
            )
            check("http validate valid", json.loads(text)["valid"], True)


def main() -> None:
    try:
        from mcp.client.streamable_http import streamablehttp_client  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional transport
        print("SKIP: streamable HTTP client unavailable: %s" % exc)
        return

    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apollo_charting.server",
            "--transport",
            "streamable-http",
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=str(REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if wait_for_port(port, proc):
            asyncio.run(run_client("http://%s:%d/mcp" % (HOST, port)))
        else:
            ok("http server started", False)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n========================================")
    print("passed: %d   failed: %d" % (PASS, FAIL))
    if FAIL:
        raise SystemExit(1)
    print("http smoke test OK")


if __name__ == "__main__":
    main()
