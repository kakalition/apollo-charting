# apollo-charting

[![CI](https://github.com/kakalition/apollo-charting/actions/workflows/ci.yml/badge.svg)](https://github.com/kakalition/apollo-charting/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-server-6E56CF.svg)](https://modelcontextprotocol.io)

A standalone, **stateless** [Model Context Protocol](https://modelcontextprotocol.io)
server that renders **shadcn/ui-style charts** — bar, line, area, pie, donut,
radar, and radial — to PNG from a compact JSON spec, and extracts the equivalent
Recharts/shadcn JSX.

It is the charting engine that used to ship as the `charting`
[Agent Skill](https://skills.sh) in
[apollo-pack](https://github.com/kakalition/apollo-pack), re-homed as an MCP.
The render core (`scripts/_lib.py`, `scripts/_html.py`, `scripts/render.py`) is
reused as-is; Node/Playwright is shelled out to only for the screenshot.

- **Spec in, chart out** — one JSON object, one PNG (returned inline and written
  to disk).
- **Stateless** — no database, no render history, no state written; safe to run
  as many copies as you like.
- **Faithful shadcn styling** — hairline grid, no axis lines, rounded bars, the
  `--chart-1..5` token palette, light and dark themes.
- **Deterministic output** — animations off, fixed viewport, exact
  `width × scale` by `height × scale` pixels, optional transparency.
- **Discoverable** — palettes, themes, demo specs, and the spec schema are
  read-only MCP resources, plus a `make-chart` prompt.

## Requirements

- **Python 3.10+** for the MCP server. The Python engine is standard library
  only; the MCP layer depends on `mcp`.
- **Node 20+** with a headless Chromium for `render_chart`. Without it,
  `render_chart` fails fast with a `dependency_missing` error while
  `validate_spec` and `chart_component` keep working.

## Install

```bash
git clone https://github.com/kakalition/apollo-charting
cd apollo-charting

uv sync                 # Python environment for the server
npm ci                  # pinned render dependencies
node scripts/build.mjs  # build the React + Recharts bundle
npx playwright install chromium
```

The Node step is a one-time setup. After it, rendering is fully offline. (`uv`
is the only extra tool you need; install it from
<https://docs.astral.sh/uv/>.)

## Use with an MCP client

The server speaks MCP over **stdio**. Point your client at the console script:

```json
{
  "mcpServers": {
    "apollo-charting": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/apollo-charting", "apollo-charting"]
    }
  }
}
```

Run it directly, or explore it with the MCP Inspector:

```bash
uv run apollo-charting                 # stdio server
uv run mcp dev src/apollo_charting/server.py   # inspector UI
```

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `render_chart` | `spec` (required), `out`, `home`, `theme`, `scale`, `transparent`, `force`, `keep_html` | JSON metadata (path, bytes, sha256, width, height, scale, family, theme, background, home, html, warnings) **and** an inline `image/png`. |
| `validate_spec` | `spec` (required), `strict` | JSON mirroring `render.py check`: `valid`, `family`, `series`, `points`, dimensions, palette, theme, layout, warnings; with `strict`, a Node/bundle/Playwright/Chromium report and a `renderable` boolean. |
| `chart_component` | `spec` (required) | The equivalent `recharts` + `@/components/ui/chart` JSX as text. |

Defaults for `render_chart`:

- `out` — `<output_dir>/<slug>.png`, named from `spec.title` (or `chart`).
- `home` — `$CHARTING_HOME`, else `~/.local/share/charting`.
- `theme`, `scale` — fall back to the spec, then the built-in defaults.
- `transparent` — off; the spec's `background` decides otherwise.
- `force` — `false`; an existing `out` raises a `conflict` error.

### Example

```json
{
  "spec": {
    "chart": "bar",
    "title": "Revenue by month",
    "data": [
      {"month": "Jan", "desktop": 186, "mobile": 80},
      {"month": "Feb", "desktop": 205, "mobile": 120}
    ],
    "x": {"key": "month"},
    "series": [{"key": "desktop"}, {"key": "mobile"}],
    "palette": "default",
    "width": 720,
    "height": 420,
    "scale": 2
  }
}
```

`render_chart` returns a text block like:

```json
{
  "out": "/home/you/.local/share/charting/output/Revenue-by-month.png",
  "bytes": 48210,
  "sha256": "6f1c…",
  "width": 1440,
  "height": 840,
  "scale": 2,
  "family": "bar",
  "theme": "light",
  "background": "transparent",
  "home": "/home/you/.local/share/charting",
  "html": null,
  "warnings": []
}
```

followed by an `image/png` content block with the chart.

## Resources (read-only)

| URI | Content |
|---|---|
| `charting://palettes` | Every palette with its colors. |
| `charting://palette/{name}` | One palette's colors. |
| `charting://themes` | The `light` and `dark` token maps. |
| `charting://theme/{name}` | One theme's tokens. |
| `charting://demos` | Names of the bundled example specs. |
| `charting://demo/{name}` | A full demo spec (`bar`, `line`, `area`, `pie`, `donut`, `radar`, `radial`). |
| `charting://schema` | A concise reference for every spec key. |

## Prompt

| Name | Purpose |
|---|---|
| `make-chart` | Gives the model the spec contract (families, the `x.key` requirement, palette names, scale semantics, and the `dependency_missing` hint) and instructs it to compose a spec and call `render_chart`. |

## The chart spec

```json
{
  "spec_version": 1,
  "chart": "bar",
  "title": "Revenue by month",
  "data": [
    {"month": "Jan", "desktop": 186, "mobile": 80},
    {"month": "Feb", "desktop": 205, "mobile": 120}
  ],
  "x": {"key": "month"},
  "y": {"hide": false, "format": "number"},
  "series": [
    {"key": "desktop", "label": "Desktop"},
    {"key": "mobile", "label": "Mobile"}
  ],
  "palette": "default",
  "legend": "bottom",
  "width": 720, "height": 420, "scale": 2,
  "background": "transparent"
}
```

- `chart` is required: `bar`, `line`, `area`, `pie`, `donut`, `radar`, or
  `radial`.
- Cartesian families need `x.key`; pie/donut/radial need `name_key` +
  `value_key`; radar needs `x.key` (or `axis_key`) and a series.
- `palette` is a name (`default`, `neutral`, `blue`, `emerald`, `amber`, `rose`,
  `slate`), an array of up to five colors, or a `chart-1..chart-5` override map.
- `theme` is `light` or `dark`; `width`/`height` are CSS pixels; `scale` (1–4)
  multiplies both.

Read `charting://schema` (or [`references/schema.md`](references/schema.md)) for
the full key reference, [`references/charts.md`](references/charts.md) for
per-family options and gallery-variant knobs, and
[`references/themes.md`](references/themes.md) for the tokens and palettes.

## Errors

Tool failures surface as MCP errors whose message starts with the error code:

| Code | Meaning |
|---|---|
| `invalid_spec` | The spec failed validation (unknown family, missing `x.key`, bad scale, unknown palette, …). |
| `dependency_missing` | Node, the esbuild bundle, or Chromium is missing; the message includes the exact install command. |
| `conflict` | The output file exists and `force` was not set. |
| `render_failed` | Chromium produced no result or reported an error. |

## Configuration

Settings come from the built-in defaults (`scripts/_lib.py`) and optional
`CHARTING_*` environment variables. They apply only to fields the spec leaves
unset.

| Env var | Default | Env var | Default |
|---|---|---|---|
| `CHARTING_HOME` | `~/.local/share/charting` | `CHARTING_GRID` | `true` |
| `CHARTING_THEME` | `light` | `CHARTING_LEGEND` | `bottom` |
| `CHARTING_PALETTE` | `default` | `CHARTING_FONT` | `system` |
| `CHARTING_WIDTH` | `720` | `CHARTING_BACKGROUND` | `transparent` |
| `CHARTING_HEIGHT` | `420` | `CHARTING_OUTPUT_DIR` | `<home>/output` |
| `CHARTING_SCALE` | `2` | | |

The data root holds only generated artifacts: `output/` (the default PNG
destination) and `tmp/` (generated HTML, kept only with `keep_html`). No
database is opened and no render is recorded.

## How it works

```
spec ──▶ _lib.apply_settings ──▶ _lib.validate_spec
     ──▶ _html.build_html ──▶ Node: screenshot.mjs (Playwright) ──▶ PNG
```

The Python engine resolves rows/series, tokens, palette, and layout;
`screenshot.mjs` loads the self-contained HTML into headless Chromium and
captures the chart node, with React + Recharts bundled by esbuild from
`scripts/boot/`. The MCP layer reuses those modules unchanged and returns the
PNG both inline (base64) and on disk. The database-backed chart library,
settings CRUD, render history, scheduler artifacts, and the pdf-creator
`--register` integration still exist as CLI code in `scripts/`, but are **not
exposed over MCP**.

## Development

```bash
uv sync
bash tests/smoke.sh              # CLI engine end-to-end (self-skips render when Node/Chromium are absent)
uv run python tests/mcp_smoke.py # MCP tools, resources, validation, and a render roundtrip
```

`tests/smoke.sh` generates its own fixtures and exercises every CLI verb against
a throwaway data root. `tests/mcp_smoke.py` drives the FastMCP server in-process
and checks the tool trio, the resources, validation, component extraction, error
surfacing, and an end-to-end render. Both self-skip the render sections when
Node, the bundle, or Chromium are missing.

## Layout

```
apollo-charting/
├── pyproject.toml          # uv project; runtime dep: mcp; dev: mcp[cli]
├── src/apollo_charting/
│   ├── __init__.py         # __version__
│   └── server.py           # FastMCP server (tools + resources + prompt)
├── scripts/                # the engine and CLI verbs (reused as-is)
│   ├── _lib.py  _html.py  render.py
│   ├── charts.py  init.py  settings.py  themes.py  reports.py
│   ├── screenshot.mjs  build.mjs  boot/  _chart.html  _chart.css
│   └── vendor/             # generated bundle (gitignored)
├── references/             # schema, commands, charts, themes, scheduling
├── tests/
│   ├── smoke.sh            # CLI engine end-to-end
│   └── mcp_smoke.py        # MCP-level roundtrip
├── package.json  package-lock.json
└── LICENSE
```

## License

MIT. See [`LICENSE`](LICENSE).
