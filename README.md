# apollo-charting

A standalone, **stateless** [MCP](https://modelcontextprotocol.io) server that
renders **shadcn/ui-style charts** — bar, line, area, pie, donut, radar, radial
— to PNG from a compact JSON spec, and extracts the equivalent
Recharts/shadcn JSX.

It is the charting engine that used to ship as the `charting` Agent Skill in
[apollo-pack](https://github.com/kakalition/apollo-pack), re-homed as an MCP. The
render core (`scripts/_lib.py`, `scripts/_html.py`, `scripts/render.py`) is reused
unchanged; Node/Playwright is shelled out to only for the screenshot.

## Stateless by design

Every tool is spec in, chart out. The server opens no database and writes no
state — it renders to a PNG and returns it. The only directories it touches are
under the data root (`tmp/` for generated HTML and the default output
directory). The chart library, settings CRUD, render history, scheduler
artifacts, and the pdf-creator `--register` integration still exist as CLI code
in `scripts/`, but they are **not exposed over MCP**.

Settings come from the built-in defaults (`_lib.SETTING_DEFAULTS`) with optional
`CHARTING_*` environment overrides. The data root resolves in order: the `home`
tool argument, `$CHARTING_HOME`, then `~/.local/share/charting`.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `render_chart` | `spec`, `out`, `home`, `theme`, `scale`, `transparent`, `force`, `keep_html` | JSON metadata (path, bytes, sha256, dimensions, scale, family, theme, warnings) **and** the inline `image/png`. |
| `validate_spec` | `spec`, `strict` | JSON mirroring `render.py check`: `valid`, `family`, `series`, `points`, dimensions, palette, layout, warnings; with `strict`, dependency report + `renderable`. |
| `chart_component` | `spec` | The equivalent `recharts` + `@/components/ui/chart` JSX as text. |

Defaults for `render_chart.out`: `<output_dir>/<slug>.png`, where the name comes
from `spec.title` (or `chart`).

## Resources (read-only)

| URI | Content |
|---|---|
| `charting://palettes` | Every palette with its colors. |
| `charting://palette/{name}` | One palette's colors. |
| `charting://themes` | The `light` and `dark` token maps. |
| `charting://theme/{name}` | One theme's tokens. |
| `charting://demos` | Names of the bundled example specs. |
| `charting://demo/{name}` | A full demo spec. |
| `charting://schema` | A concise reference for every spec key. |

## Prompt

`make-chart` gives the model the spec contract (families, `x.key` requirement,
palette names, scale semantics, and the `dependency_missing` hint) and instructs
it to compose a spec and call `render_chart`.

## Run

```bash
# install the Python environment (creates .venv and uv.lock)
uv sync

# stdio server (how an MCP client launches it)
uv run apollo-charting

# or explore it in the MCP inspector
uv run mcp dev src/apollo_charting/server.py
```

The server is not registered in any host config; register it yourself when you
want it, for example as a stdio server running `uv run --directory
/path/to/apollo-charting apollo-charting`.

## Requirements

- **Python 3.10+** (the MCP layer requires `mcp`; the engine itself is standard
  library only).
- **Node 20+** with a headless Chromium for `render_chart`. Install once from
  the repo:

  ```bash
  npm ci
  node scripts/build.mjs
  npx playwright install chromium
  ```

Without Node, the bundle, or Chromium, `render_chart` fails fast with a
`dependency_missing` error whose message includes that install command;
`validate_spec` and `chart_component` keep working.

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

Read `charting://schema` (or `references/schema.md`) for the full key reference,
`references/charts.md` for per-family options and gallery-variant knobs, and
`references/themes.md` for the tokens and palettes.

## Layout

```
apollo-charting/
├── pyproject.toml          # uv project; dependency: mcp<2
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

## Test

```bash
bash tests/smoke.sh              # CLI engine
uv run python tests/mcp_smoke.py # MCP trio + resources
```

`smoke.sh` generates its own fixtures and self-skips the render sections when
Node, the bundle, or Chromium are absent. `mcp_smoke.py` checks the tool trio,
the resources, validation, component extraction, error surfacing, and an
end-to-end render (which self-skips the same way).

## License

MIT. See `LICENSE`.
