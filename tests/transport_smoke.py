#!/usr/bin/env python3
"""End-to-end transport test for apollo-charting.

Spawns the server as a real subprocess (or lets the stdio client do it) and
drives it over every MCP transport: stdio, streamable HTTP, and SSE. Each
transport must initialize, list the tool trio, and validate a spec; when Node,
the esbuild bundle, and Chromium are present, each also renders a chart and
returns an inline PNG whose file we re-read. Self-skips rendering otherwise.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _noisy in ("httpx", "httpcore", "mcp", "mcp.client"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
os.environ.setdefault("APOLLO_CHARTING_LOG_LEVEL", "WARNING")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from apollo_charting import server as srv  # noqa: E402

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


def _bundle() -> Path:
    return srv._lib.bundle_path()


def renderable() -> bool:
    return bool(shutil.which("node")) and _bundle().is_file() and srv._lib.chromium_installed()


def tiny_spec() -> dict:
    return {
        "spec_version": 1,
        "chart": "bar",
        "title": "Tiny",
        "data": [{"m": "A", "v": 1}, {"m": "B", "v": 2}],
        "x": {"key": "m"},
        "series": [{"key": "v"}],
        "width": 320,
        "height": 200,
        "scale": 1,
    }


def bar_spec() -> dict:
    return {
        "chart": "bar",
        "data": [{"m": "A", "v": 1}],
        "x": {"key": "m"},
        "series": [{"key": "v"}],
    }


def text_of(result) -> str:
    return "".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


async def exercise(session, label: str) -> None:
    """Run the shared assertions against an initialized MCP client session."""
    tools = sorted(tool.name for tool in (await session.list_tools()).tools)
    check("%s tool trio" % label, tools, ["chart_component", "render_chart", "validate_spec"])

    validated = json.loads(text_of(await session.call_tool("validate_spec", {"spec": bar_spec()})))
    check("%s validate valid" % label, validated["valid"], True)

    if not renderable():
        return
    home = tempfile.mkdtemp(prefix="apollo-charting-%s-" % label)
    result = await session.call_tool("render_chart", {"spec": tiny_spec(), "home": home})
    if getattr(result, "isError", False):
        ok("%s render ok" % label, False)
        return
    images = [block for block in result.content if getattr(block, "type", None) == "image"]
    meta = json.loads(text_of(result))
    out_path = Path(meta["out"])
    check("%s render image block" % label, len(images), 1)
    if images:
        check("%s render mime" % label, images[0].mimeType, "image/png")
    ok("%s render png exists" % label, out_path.is_file())
    if out_path.is_file():
        info = srv._lib.png_info(out_path)
        check("%s render png width" % label, info["width"], 320)
        check("%s render png height" % label, info["height"], 200)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def spawn(transport: str, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apollo_charting.server",
            "--transport",
            transport,
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=str(REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


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


async def run_stdio() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "apollo_charting.server"],
        env={**os.environ},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await exercise(session, "stdio")


async def run_http(transport: str, label: str, port: int) -> None:
    from mcp import ClientSession

    if transport == "streamable-http":
        from mcp.client.streamable_http import streamablehttp_client as connect
        url = "http://%s:%d/mcp" % (HOST, port)
    else:
        from mcp.client.sse import sse_client as connect
        url = "http://%s:%d/sse" % (HOST, port)

    proc = spawn(transport, port)
    try:
        if not wait_for_port(port, proc):
            ok("%s server started" % label, False)
            return
        async with connect(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                await exercise(session, label)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    print("== stdio ==")
    try:
        asyncio.run(run_stdio())
    except Exception as exc:  # noqa: BLE001 - report and continue
        ok("stdio transport", False)
        print("  stdio error: %r" % exc, file=sys.stderr)

    print("== streamable-http ==")
    try:
        asyncio.run(run_http("streamable-http", "http", free_port()))
    except Exception as exc:  # noqa: BLE001
        ok("http transport", False)
        print("  http error: %r" % exc, file=sys.stderr)

    print("== sse ==")
    try:
        asyncio.run(run_http("sse", "sse", free_port()))
    except Exception as exc:  # noqa: BLE001
        ok("sse transport", False)
        print("  sse error: %r" % exc, file=sys.stderr)

    if not renderable():
        print("SKIP: Node, the chart bundle, and Chromium are required; render checks skipped")

    print("\n========================================")
    print("passed: %d   failed: %d" % (PASS, FAIL))
    if FAIL:
        raise SystemExit(1)
    print("transport smoke test OK")


if __name__ == "__main__":
    main()
