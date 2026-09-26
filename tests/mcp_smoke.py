#!/usr/bin/env python3
"""MCP-level roundtrip test for the apollo-charting server.

Runs in-process against the FastMCP server (no transport) and checks the tool
trio, the read-only resources, validation, component extraction, error
surfacing, and an end-to-end render. The render section self-skips when Node,
the esbuild bundle, or Chromium are absent, mirroring tests/smoke.sh.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from apollo_charting import server as srv  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

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


async def call(name: str, arguments: dict):
    """Call a tool and return its content blocks, unwrapping structured output."""
    result = await srv.mcp.call_tool(name, arguments)
    if isinstance(result, tuple):
        return result[0]
    return result


async def run() -> None:
    tools = {tool.name for tool in await srv.mcp.list_tools()}
    check("tool trio", sorted(tools), ["chart_component", "render_chart", "validate_spec"])

    resources = {str(resource.uri) for resource in await srv.mcp.list_resources()}
    for uri in ("charting://palettes", "charting://themes", "charting://demos", "charting://schema"):
        ok("resource %s" % uri, uri in resources)

    templates = {str(t.uriTemplate) for t in await srv.mcp.list_resource_templates()}
    for uri in ("charting://palette/{name}", "charting://theme/{name}", "charting://demo/{name}"):
        ok("template %s" % uri, uri in templates)

    demo = json.loads((await srv.mcp.read_resource("charting://demo/bar"))[0].content)

    validated = json.loads((await call("validate_spec", {"spec": demo}))[0].text)
    check("validate valid", validated["valid"], True)
    check("validate family", validated["family"], "bar")

    component = (await call("chart_component", {"spec": demo}))[0].text
    ok("component imports Bar", "import { Bar" in component)
    ok("component disables animation", "isAnimationActive={false}" in component)

    try:
        await call("validate_spec", {"spec": {"chart": "wat"}})
        ok("invalid spec raises", False)
    except ToolError as exc:
        ok("invalid spec code", "invalid_spec" in str(exc))

    _lib = srv._lib
    if not (shutil.which("node") and _lib.bundle_path().is_file() and _lib.chromium_installed()):
        print("SKIP: Node, the chart bundle, and Chromium are all required; render section skipped")
    else:
        home = tempfile.mkdtemp(prefix="apollo-charting-mcp-")
        spec = {
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
        content = await call("render_chart", {"spec": spec, "home": home})
        texts = [block for block in content if getattr(block, "type", None) == "text"]
        images = [block for block in content if getattr(block, "type", None) == "image"]
        check("render text block", len(texts), 1)
        check("render image block", len(images), 1)
        if images:
            check("render image mime", images[0].mimeType, "image/png")
        meta = json.loads(texts[0].text)
        out_path = Path(meta["out"])
        ok("render png exists", out_path.is_file())
        info = _lib.png_info(out_path)
        check("render png width", info["width"], 320)
        check("render png height", info["height"], 200)
        check("render meta width", meta["width"], 320)
        check("render meta scale", meta["scale"], 1)


def main() -> None:
    asyncio.run(run())
    print("\n========================================")
    print("passed: %d   failed: %d" % (PASS, FAIL))
    if FAIL:
        raise SystemExit(1)
    print("mcp smoke test OK")


if __name__ == "__main__":
    main()
