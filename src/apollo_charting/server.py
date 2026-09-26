#!/usr/bin/env python3
"""Stateless MCP server for the apollo-charting render core.

The server exposes only the spec-in / chart-out path: ``render_chart``,
``validate_spec``, and ``chart_component``. It reuses the existing engine
modules under ``scripts/`` by importing them; Node/Playwright is shelled out
only for the actual screenshot. No database is opened and no state is written.

Read-only resources make palettes, themes, demos, and the spec schema
discoverable, and one prompt gives the model the spec contract.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _html  # noqa: E402
import _lib  # noqa: E402
import render  # noqa: E402
import themes  # noqa: E402
from mcp.server.fastmcp import FastMCP, Image  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

try:
    from apollo_charting import __version__
except Exception:  # pragma: no cover - direct-path import (mcp dev)
    __version__ = "1.0.0"


def _log_level() -> str:
    level = os.environ.get("APOLLO_CHARTING_LOG_LEVEL", "INFO").upper()
    return level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO"


mcp = FastMCP(
    "apollo-charting",
    instructions=(
        "Render shadcn/Recharts chart specs to PNG. Compose a JSON spec and call "
        "render_chart; use validate_spec to check one without rendering and "
        "chart_component to get the equivalent Recharts JSX."
    ),
    log_level=_log_level(),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_error(exc: _lib.CommandError) -> ToolError:
    """Surface a CommandError as an MCP tool error that keeps its code."""
    return ToolError("%s: %s" % (exc.code, exc.message))


def _stateless_output_dir(home: Path) -> Path:
    configured = _lib.default_settings().get("output_dir", "").strip()
    if configured:
        return Path(str(configured)).expanduser()
    return _lib.resolve_output_path(home)


def _resolve_out(out: Optional[str], home: Path, spec: Dict[str, Any]) -> Path:
    default_name = str(spec.get("title") or "chart")
    if out:
        out_path = Path(out).expanduser()
        if out_path.is_dir():
            out_path = out_path / ("%s.png" % default_name)
        return out_path
    return _stateless_output_dir(home) / ("%s.png" % _lib.slugify(default_name))


def _strict_dependencies() -> Dict[str, bool]:
    """Mirror ``render.cmd_check --strict``: probe Node, bundle, Playwright, Chromium."""
    dependencies = _lib.dependency_report()
    if dependencies["node"] and dependencies["playwright"]:
        node = shutil.which("node")
        completed = subprocess.run(
            [node, render.SCREENSHOT_SCRIPT, "--check"], capture_output=True, text=True
        )
        for line in reversed((completed.stdout or "").strip().splitlines()):
            if line.strip().startswith("{"):
                payload = json.loads(line)
                dependencies["chromium"] = bool((payload.get("data") or {}).get("chromium"))
                break
    return dependencies


def _load_and_validate(spec: Any) -> tuple[Dict[str, Any], List[str]]:
    if not isinstance(spec, dict):
        raise _lib.CommandError("invalid_spec", "the chart spec must be a JSON object")
    resolved = _lib.apply_settings(dict(spec), _lib.default_settings())
    return _lib.validate_spec(resolved)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def render_chart(
    spec: dict,
    out: Optional[str] = None,
    home: Optional[str] = None,
    theme: Optional[str] = None,
    scale: Optional[int] = None,
    transparent: Optional[bool] = None,
    force: bool = False,
    keep_html: bool = False,
):
    """Render a chart spec to a PNG and return metadata plus the inline image.

    Args:
        spec: The chart spec (schema v1); see the charting://schema resource.
        out: Output PNG path. Defaults to ``<output_dir>/<slug>.png``.
        home: Data root. Defaults to ``$CHARTING_HOME`` or ``~/.local/share/charting``.
        theme: Override the spec theme (``light`` or ``dark``).
        scale: Override the pixel scale (1-4).
        transparent: Force a transparent background.
        force: Overwrite an existing output file.
        keep_html: Keep the generated HTML next to the PNG in ``tmp/``.
    """
    try:
        resolved = dict(spec or {})
        if theme:
            resolved["theme"] = theme
        if scale is not None:
            resolved["scale"] = scale
        home_path = _lib.resolve_home(home)
        resolved, _ = _load_and_validate(resolved)
        out_path = _resolve_out(out, home_path, resolved)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _lib.resolve_tmp_path(home_path).mkdir(parents=True, exist_ok=True)
        result = render.render_spec(
            None,
            home_path,
            resolved,
            out_path,
            force=force,
            transparent=bool(transparent),
            keep_html=keep_html,
            no_record=True,
            name=out_path.stem,
        )
    except _lib.CommandError as exc:
        raise _tool_error(exc)

    metadata: Dict[str, Any] = {
        "out": result["out"],
        "bytes": result["bytes"],
        "sha256": result["sha256"],
        "width": result["width"],
        "height": result["height"],
        "scale": result["scale"],
        "family": result["family"],
        "theme": result["theme"],
        "background": result["background"],
        "home": str(home_path),
        "html": result["html"],
        "warnings": result["warnings"],
    }
    return [json.dumps(metadata, indent=2), Image(path=result["out"])]


@mcp.tool()
def validate_spec(spec: dict, strict: bool = False) -> str:
    """Validate a chart spec without rendering it.

    With ``strict``, also report Node/bundle/Playwright/Chromium availability
    and whether the spec is renderable on this host.
    """
    try:
        resolved, warnings = _load_and_validate(spec)
        payload = _html.build_payload(resolved)
    except _lib.CommandError as exc:
        raise _tool_error(exc)

    result: Dict[str, Any] = {
        "valid": True,
        "spec_version": resolved.get("spec_version", _lib.SPEC_VERSION),
        "family": resolved["chart"],
        "series": len(payload["series"]),
        "points": len(payload["rows"]) or len(payload["pie"]),
        "width": resolved["width"],
        "height": resolved["height"],
        "scale": resolved["scale"],
        "palette": payload["palette"],
        "theme": resolved.get("theme"),
        "layout": payload["layout"],
        "warnings": warnings,
        "strict": bool(strict),
    }
    if strict:
        dependencies = _strict_dependencies()
        result["dependencies"] = dependencies
        result["renderable"] = all(
            dependencies.get(key) for key in ("node", "bundle", "playwright", "chromium")
        )
    return json.dumps(result, indent=2)


@mcp.tool()
def chart_component(spec: dict) -> str:
    """Return the equivalent shadcn/Recharts JSX for a chart spec."""
    try:
        resolved, _ = _load_and_validate(spec)
        return _html.build_component(resolved, base_dir=None)
    except _lib.CommandError as exc:
        raise _tool_error(exc)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("charting://palettes", mime_type="application/json")
def palettes() -> str:
    """Every built-in palette with its colors."""
    return json.dumps(
        [{"name": name, "colors": colors} for name, colors in sorted(_lib.PALETTES.items())],
        indent=2,
    )


@mcp.resource("charting://palette/{name}", mime_type="application/json")
def palette(name: str) -> str:
    """One palette's colors."""
    if name not in _lib.PALETTES:
        raise ValueError("no palette named %r (try: %s)" % (name, ", ".join(sorted(_lib.PALETTES))))
    return json.dumps({"name": name, "colors": _lib.PALETTES[name]}, indent=2)


@mcp.resource("charting://themes", mime_type="application/json")
def theme_list() -> str:
    """The light and dark token maps."""
    return json.dumps(
        {
            "light": _lib.theme_tokens("light", _lib.PALETTES["default"]),
            "dark": _lib.theme_tokens("dark", _lib.PALETTES["default"]),
        },
        indent=2,
    )


@mcp.resource("charting://theme/{name}", mime_type="application/json")
def theme(name: str) -> str:
    """One theme's tokens, using the default palette for the chart colors."""
    if name not in _lib.THEMES:
        raise ValueError("no theme named %r (try: %s)" % (name, ", ".join(_lib.THEMES)))
    return json.dumps(_lib.theme_tokens(name, _lib.PALETTES["default"]), indent=2)


@mcp.resource("charting://demos", mime_type="application/json")
def demo_list() -> str:
    """The names of the bundled example specs."""
    return json.dumps(sorted(themes.DEMOS), indent=2)


@mcp.resource("charting://demo/{name}", mime_type="application/json")
def demo(name: str) -> str:
    """A full bundled demo spec."""
    return json.dumps(themes._demo_spec(name), indent=2)


_SCHEMA_SUMMARY = """# Chart spec reference (schema v1)

A spec is a JSON object. Required: `chart`. Cartesian families (`bar`, `line`,
`area`) and `radar` also need `x.key` (radar accepts `axis_key`); pie families
(`pie`, `donut`) and `radial` need `name_key` + `value_key`.

## Top-level keys

| Key | Type | Default | Notes |
|---|---|---|---|
| `spec_version` | int | `1` | Rejected if newer than the server supports. |
| `chart` | string | — | **Required.** `bar` `line` `area` `pie` `donut` `radar` `radial`. |
| `variant` | string | — | `bar` only: `grouped` `stacked` `horizontal`. |
| `title` / `description` | string | — | Card chrome above the plot. |
| `data` | array | — | Tabular rows: a list of objects. |
| `categories` | array | — | Labels paired with series `values` when `data` is omitted. |
| `x` | object | — | Category axis; cartesian needs `x.key`. |
| `y` | object | — | Value axis: `label`, `format`, `domain`, `hide`. |
| `axis_key` | string | `x.key` | `radar` only. |
| `series` | array | inferred | `[{key, label, color}]` or `[{key, values}]`. |
| `name_key` / `value_key` | string | — | Slice fields for `pie` / `donut` / `radial`. |
| `palette` | string \\| array \\| object | `default` | Name, 1-5 colors, or `chart-1..5` overrides. |
| `theme` | string | `light` | `light` or `dark`. |
| `legend` | string \\| bool | `bottom` | `top` `bottom` `right` `none`; `false` = `none`. |
| `grid` | bool | `true` | Cartesian grid (horizontal lines only). |
| `curve` | string | `monotone` | `linear` `monotone` `stepAfter` `step` `basis` `natural`. |
| `stacked` | bool | `false` | Stack series (`bar` / `area`). |
| `horizontal` | bool | `false` | Horizontal bars. |
| `gradient` | bool | `true` | Area gradient fill. |
| `donut` | bool | `false` | Inner radius for pie charts. |
| `inner_radius` / `outer_radius` | number \\| string | family | Percent string or pixels. |
| `fill_opacity` | number | `0.6` | Radar fill opacity. |
| `stroke_width` | number | `2` | Line / area stroke width. |
| `dot` | bool | `false` | Show line dots. |
| `radius` | int | `4` | Bar corner radius. |
| `label` / `labels` | bool | `false` | Value labels on bar/line; slice labels on pie/donut. |
| `expand` | bool | `false` | Percentage stacking (with `stacked`); axis reads 0-100%. |
| `axes` | bool | `false` | Show the value axis (same as `y.hide: false`). |
| `separator` | bool | `true` | Pie slice stroke; `false` removes it. |
| `legend_values` | bool | `false` | Pie legend shows each slice's value. |
| `active` | int | — | 0-based index to highlight. |
| `negative` / `negative_color` | bool / color | `false` / `--chart-2` | Bars below zero. |
| `value_key_2` | string | — | Second ring value for `pie_stacked`. |
| `pie_stacked` | bool | `false` | Two concentric rings. |
| `radar_grid` | string | `polygon` | `polygon` `circle` `none`. |
| `radar_grid_fill` | bool | `false` | Tint the polar grid. |
| `radar_dots` | bool | `false` | Dots on radar vertices. |
| `fill` | bool | `true` | `false` gives an outline-only radar. |
| `radial_grid` | bool | `false` | Circular polar grid behind radial arcs. |
| `radial_labels` | bool | `false` | Inside labels on radial arcs. |
| `radial_corner` | int | `10` | Radial arc corner radius. |
| `radial_stacked` | bool | `false` | One radial ring per series. |
| `center_label` | string | — | Donut or radial center text. |
| `center_total` | bool | `false` | Radial: show the summed value in the center. |
| `background_track` | bool | `true` | Radial background track. |
| `tooltip` | bool | `false` | Include the Recharts tooltip (invisible in a PNG). |
| `background` | string | `transparent` | `transparent`, a hex color, or `rgb()`. |
| `card` | bool | `true` | Draw the card border and radius. |
| `padding` | int | `16` | Inner padding in CSS pixels. |
| `width` / `height` | int | `720` / `420` | CSS pixels, 64-4096. |
| `scale` | int | `2` | Pixel scale, 1-4; PNG is `width*scale` x `height*scale`. |

`y.format` is one of `number` `percent` `currency` `compact` `raw`.
"""


@mcp.resource("charting://schema", mime_type="text/markdown")
def schema() -> str:
    """A concise reference for every chart spec key."""
    return _SCHEMA_SUMMARY


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_MAKE_CHART_PROMPT = """You are composing a chart for the apollo-charting tools.

Build a single JSON chart spec (schema v1), then call `render_chart` with it.

Contract:
- `chart` is required: one of bar, line, area, pie, donut, radar, radial.
- bar/line/area need `x.key` pointing at a field in each `data` row; series are
  `[{"key": "field", "label": "..."}]` (inferred from numeric fields if omitted).
- pie/donut/radial need `name_key` and `value_key`.
- radar needs `x.key` (or `axis_key`) plus at least one series.
- `palette` is a name (default, neutral, blue, emerald, amber, rose, slate), a
  list of up to five colors, or `chart-1..chart-5` overrides.
- `theme` is light or dark; `width`/`height` are CSS pixels; `scale` (1-4)
  multiplies both, so the PNG is width*scale by height*scale.
- Read `charting://schema`, `charting://palettes`, `charting://themes`, and
  `charting://demo/{name}` for reference and example specs.

Call `validate_spec` first if you want to check the spec without rendering. If a
call fails with `dependency_missing`, tell the user to install Node 20+, run the
build, and install Chromium via Playwright (the message includes the exact
command). Return the rendered PNG and note its path and dimensions.
"""


@mcp.prompt(name="make-chart", description="Compose and render a chart spec with apollo-charting.")
def make_chart() -> str:
    return _MAKE_CHART_PROMPT


def main() -> None:
    """Run the server.

    Defaults to stdio for MCP clients. ``--transport streamable-http`` (endpoint
    ``/mcp``) or ``--transport sse`` (endpoint ``/sse``) serves the same MCP API
    over HTTP instead.
    """
    parser = argparse.ArgumentParser(
        prog="apollo-charting",
        description="Stateless MCP server that renders chart specs to PNG.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=os.environ.get("APOLLO_CHARTING_TRANSPORT", "stdio"),
        help="MCP transport to serve (default: stdio, or $APOLLO_CHARTING_TRANSPORT).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("APOLLO_CHARTING_HOST", "127.0.0.1"),
        help="HTTP bind host (default: 127.0.0.1, or $APOLLO_CHARTING_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("APOLLO_CHARTING_PORT", "8000")),
        help="HTTP bind port (default: 8000, or $APOLLO_CHARTING_PORT).",
    )
    parser.add_argument("--version", action="version", version="apollo-charting %s" % __version__)
    args = parser.parse_args()

    if args.transport != "stdio":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
