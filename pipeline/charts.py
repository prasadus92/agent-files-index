"""Step 7: render the charts from summary.json.

Usage: python -m pipeline.charts DATA_DIR CHART_DIR

Each chart is laid out once and written 3 ways: light and dark SVG with the font subset embedded,
2x PNGs of both for the README and email, and figure.dg markup for prasad.tech that takes the
site's color tokens so it follows the site theme.
"""
from __future__ import annotations

import base64
import html
import io
import json
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FONT_DIR = Path(__file__).parent / "fonts"
FONT_FILES = {400: FONT_DIR / "InstrumentSans-Regular.ttf", 600: FONT_DIR / "InstrumentSans-SemiBold.ttf"}
FAMILY = "Instrument Sans"
SITE_FAMILY = "'Instrument Sans Variable','Instrument Sans',system-ui,sans-serif"
REPO_URL = "github.com/prasadus92/agent-files-index"

WIDTH, PAD, PNG_ZOOM = 720, 32, 2
BAR_H, ROW_H = 16, 32
PAIR_BAR_H, PAIR_GAP, PAIR_ROW_H = 12, 2, 40
RADIUS = 4

# (weight, size, line height) per text role.
TEXT = {
    "title": (600, 20, 26),
    "subtitle": (400, 14, 20),
    "legend": (400, 13, 18),
    "label": (400, 14, 20),
    "value": (600, 13, 18),
    "value-muted": (400, 13, 18),
    "source": (400, 12, 17),
}

# Site palette: black, white, 1 red accent, greys. Red vs grey checked with the dataviz
# validator: CVD dE 16.3 light / 8.5 dark; light grey is under 3:1, so every bar carries its value.
THEMES = {
    "light": {"surface": "#FFFFFF", "title": "#0C0C0C", "subtitle": "#5C5C5C", "legend": "#3A3A3A",
              "label": "#1A1A1A", "value": "#0C0C0C", "value-muted": "#5C5C5C", "source": "#6B6B6B",
              "rule": "#D4D4D4", "accent": "#E5241C", "base": "#A3A3A3"},
    "dark": {"surface": "#0C0C0C", "title": "#F5F5F5", "subtitle": "#A8A8A8", "legend": "#CFCFCF",
             "label": "#E8E8E8", "value": "#F5F5F5", "value-muted": "#A8A8A8", "source": "#8F8F8F",
             "rule": "#2E2E2E", "accent": "#F0352C", "base": "#6B6B6B"},
    "site": {"title": "var(--dg-ink)", "subtitle": "var(--dg-muted)", "legend": "var(--dg-muted)",
             "label": "var(--dg-ink)", "value": "var(--dg-ink)", "value-muted": "var(--dg-muted)",
             "source": "var(--dg-muted)", "rule": "var(--dg-line)", "accent": "var(--dg-accent)",
             "base": "color-mix(in srgb, var(--dg-ink) 34%, var(--dg-surface))"},
}


@dataclass(frozen=True)
class Row:
    label: str
    values: tuple[float, ...]
    note: str = ""
    highlight: bool = False


@dataclass(frozen=True)
class Chart:
    slug: str
    title: str
    subtitle: str
    rows: list[Row]
    source: str
    series: tuple[str, ...] = ()


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    text: str
    role: str


@dataclass(frozen=True)
class Bar:
    x: float
    y: float
    w: float
    h: float
    role: str


@dataclass(frozen=True)
class Rule:
    x: float
    y1: float
    y2: float


@dataclass
class Drawing:
    chart: Chart
    height: float = 0
    shapes: list[Text | Bar | Rule] = field(default_factory=list)


@cache
def font(weight: int) -> TTFont:
    return TTFont(FONT_FILES[weight])


def text_width(text: str, role: str) -> float:
    weight, size, _ = TEXT[role]
    tt = font(weight)
    cmap, hmtx = tt.getBestCmap(), tt["hmtx"]
    units = sum(hmtx[cmap.get(ord(c), cmap[ord("?")])][0] for c in text)
    return units * size / tt["head"].unitsPerEm


def wrap(text: str, role: str, width: float) -> list[str]:
    """Greedy wrap, then narrowed while the line count holds, so the last line is never a lone word."""
    lines = greedy_wrap(text, role, width)
    while len(lines) > 1 and len(narrower := greedy_wrap(text, role, width - 8)) == len(lines):
        lines, width = narrower, width - 8
    return lines


def greedy_wrap(text: str, role: str, width: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and text_width(candidate, role) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line] if line else lines


def percent(v: float) -> str:
    return f"{v:.1f}%"


def label_column(charts: list[Chart]) -> float:
    """1 label column for the whole set, so stacked charts share a baseline."""
    return max(text_width(r.label, "label") for c in charts for r in c.rows) + 24


def layout(chart: Chart, label_w: float, with_source: bool) -> Drawing:
    d = Drawing(chart)
    y = 0.0

    def block(text: str, role: str, gap: float) -> None:
        nonlocal y
        _, size, lead = TEXT[role]
        y += gap
        for i, line in enumerate(wrap(text, role, WIDTH)):
            y += size if i == 0 else lead
            d.shapes.append(Text(0, y, line, role))

    block(chart.title, "title", 0)
    block(chart.subtitle, "subtitle", 8)

    if chart.series:
        y += 16
        x = 0.0
        for i, name in enumerate(chart.series):
            d.shapes += [Bar(x, y, 10, 10, "accent" if i == 0 else "base"), Text(x + 16, y + 9.5, name, "legend")]
            x += 16 + text_width(name, "legend") + 24
        y += 10

    paired = len(chart.series) > 1
    row_h = PAIR_ROW_H if paired else ROW_H
    value_w = max(text_width(percent(v) + (f" {r.note}" if r.note else ""), "value") for r in chart.rows for v in r.values) + 12
    top = max(max(r.values) for r in chart.rows) or 1
    scale = (WIDTH - label_w - value_w) / top
    plot_top = y + 20

    for i, row in enumerate(chart.rows):
        ry = plot_top + i * row_h
        d.shapes.append(Text(0, ry + row_h / 2 + 5, row.label, "label"))
        bars = [(v, PAIR_BAR_H, (row_h - 2 * PAIR_BAR_H - PAIR_GAP) / 2 + j * (PAIR_BAR_H + PAIR_GAP)) for j, v in enumerate(row.values)] \
            if paired else [(row.values[0], BAR_H, (row_h - BAR_H) / 2)]
        for j, (v, h, offset) in enumerate(bars):
            strong = j == 0 if paired else row.highlight
            w = max(v * scale, 1.5)
            d.shapes.append(Bar(label_w, ry + offset, w, h, "accent" if strong else "base"))
            value = percent(v) + (f" {row.note}" if row.note and j == 0 else "")
            d.shapes.append(Text(label_w + w + 8, ry + offset + h / 2 + 4.5, value, "value" if strong else "value-muted"))

    plot_bottom = plot_top + len(chart.rows) * row_h
    d.shapes.append(Rule(label_w, plot_top - 2, plot_bottom + 2))
    y = plot_bottom
    if with_source:
        block(chart.source, "source", 22)
    d.height = y + 4
    return d


def bar_path(b: Bar) -> str:
    """Square at the baseline, rounded at the data end."""
    r = min(RADIUS, b.w / 2, b.h / 2)
    x1, y2 = b.x + b.w, b.y + b.h
    return (f"M{b.x:.1f} {b.y:.1f}H{x1 - r:.1f}A{r:.1f} {r:.1f} 0 0 1 {x1:.1f} {b.y + r:.1f}"
            f"V{y2 - r:.1f}A{r:.1f} {r:.1f} 0 0 1 {x1 - r:.1f} {y2:.1f}H{b.x:.1f}Z")


def shapes_svg(d: Drawing, colors: dict[str, str], site: bool) -> list[str]:
    out = []
    for s in d.shapes:
        if isinstance(s, Text):
            weight, size, _ = TEXT[s.role]
            font_style = f"font:{weight} {size}px {SITE_FAMILY};" if site else ""
            attrs = f'style="{font_style}fill:{colors[s.role]}"' if site else \
                f'font-size="{size}" font-weight="{weight}" fill="{colors[s.role]}"'
            out.append(f'<text x="{s.x:.1f}" y="{s.y:.1f}" {attrs}>{html.escape(s.text)}</text>')
        elif isinstance(s, Bar):
            path = bar_path(s) if s.h > 10 else None
            fill = f'style="fill:{colors[s.role]}"' if site else f'fill="{colors[s.role]}"'
            out.append(f'<path d="{path}" {fill}/>' if path else
                       f'<rect x="{s.x:.1f}" y="{s.y:.1f}" width="{s.w:.1f}" height="{s.h:.1f}" rx="2" {fill}/>')
        else:
            stroke = f'style="stroke:{colors["rule"]}"' if site else f'stroke="{colors["rule"]}"'
            out.append(f'<line x1="{s.x - 0.5:.1f}" y1="{s.y1:.1f}" x2="{s.x - 0.5:.1f}" y2="{s.y2:.1f}" stroke-width="1" {stroke}/>')
    return out


def embedded_fonts(d: Drawing) -> str:
    rules = []
    for weight, path in FONT_FILES.items():
        used = "".join({c for s in d.shapes if isinstance(s, Text) and TEXT[s.role][0] == weight for c in s.text}) or " "
        options = subset.Options()
        options.layout_features = ["kern", "liga"]
        sub = subset.Subsetter(options)
        tt = TTFont(path)
        sub.populate(text=used)
        sub.subset(tt)
        buf = io.BytesIO()
        tt.save(buf)
        data = base64.b64encode(buf.getvalue()).decode()
        rules.append(f'@font-face{{font-family:"{FAMILY}";font-weight:{weight};src:url(data:font/ttf;base64,{data}) format("truetype")}}')
    return "".join(rules)


def standalone_svg(d: Drawing, theme: str) -> str:
    colors = THEMES[theme]
    w, h = WIDTH + 2 * PAD, round(d.height + 2 * PAD)
    style = f'{embedded_fonts(d)}text{{font-family:"{FAMILY}",system-ui,sans-serif}}'
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(d.chart.title)}</title>',
        f'<desc id="desc">{html.escape(d.chart.subtitle)}</desc>',
        f"<style>{style}</style>",
        f'<rect width="{w}" height="{h}" fill="{colors["surface"]}"/>',
        f'<g transform="translate({PAD} {PAD})">',
        *shapes_svg(d, colors, site=False),
        "</g>",
        "</svg>",
    ]) + "\n"


def png(svg_text: str) -> bytes:
    import resvg_py  # only the render step needs it, so layout tests run with fonttools alone

    return bytes(resvg_py.svg_to_bytes(svg_string=svg_text, zoom=PNG_ZOOM, skip_system_fonts=True,
                                       font_files=[str(p) for p in FONT_FILES.values()], font_family=FAMILY))


def figure(chart: Chart, label_w: float) -> str:
    """No blank lines inside: the site renders this as a raw HTML block in markdown."""
    d = layout(chart, label_w, with_source=False)
    return "\n".join([
        f'<figure class="dg" aria-label="{html.escape(chart.title, quote=True)}">',
        '<div class="dg-canvas">',
        f'<svg viewBox="0 0 {WIDTH} {round(d.height)}" role="presentation" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">',
        *shapes_svg(d, THEMES["site"], site=True),
        "</svg>",
        "</div>",
        f"<figcaption>{html.escape(chart.source)}</figcaption>",
        "</figure>",
    ])


SECTION_LABELS = {"lint_format": "lint and format", "git_pr": "git and pull requests", "code_style": "code style",
                  "agent_workflow": "agent workflow", "config": "configuration"}
LINK_LABELS = {"import": "Imports it with @AGENTS.md", "symlink": "Is a symlink to it", "mention": "Mentions it in the text",
               "none": "Never refers to it", "symlink_other": "Is a symlink to another file"}


def stars_label(key: str) -> str:
    lo, hi = key.split("-")
    return f"{int(lo):,}+ stars" if hi == "max" else f"{int(lo):,} to {int(hi):,} stars"


def section_rows(sections: dict[str, float], limit: int = 12) -> list[Row]:
    """Top categories by share, always including security, since the finding is how rare it is."""
    ranked = sorted(sections.items(), key=lambda kv: -kv[1])
    shown = ranked[:limit] if any(k == "security" for k, _ in ranked[:limit]) else ranked[:limit - 1] + [("security", sections["security"])]
    return [Row(SECTION_LABELS.get(k, k).capitalize(), (v,), highlight=k == "security") for k, v in shown]


def charts(s: dict) -> list[Chart]:
    fr, ad, fa, both = s["frame"], s["adoption"], s["files_A"], s["both_files"]
    a, b = fr["A_repos"], fr["B_repos"]
    source = f"Source: Agent Files Index, snapshot {fr['snapshot']}, {REPO_URL}. Data CC BY 4.0."
    census = f"Census of {a:,} GitHub repos with 1,000+ stars."
    stars = list(ad["by_stars_A"].items())
    top_band = stars[-1][1]["has_either"]
    files = sorted((("has_agents_md", "AGENTS.md"), ("has_claude_any", "CLAUDE.md"), ("has_skills", "SKILL.md (skills folder)"),
                    ("has_copilot", "Copilot instructions"), ("has_cursor", "Cursor rules"), ("has_gemini_md", "GEMINI.md"),
                    ("has_mcp_json", ".mcp.json")), key=lambda kv: -ad["A"][kv[0]])
    link = sorted(both["link_share"].items(), key=lambda kv: -kv[1])
    cmd = (("has_any_command", "Any command"), ("has_test_cmd", "A test command"), ("has_lint_cmd", "A lint command"))
    sec = {kind: fa[kind]["sections"]["security"] for kind in ("agents_md", "claude_md")}
    return [
        Chart("adoption-by-stars", f"The more stars a repo has, the likelier it ships an agent file: {percent(top_band)} at 50,000+",
              f"Repos with a root AGENTS.md or CLAUDE.md, by star count. {census}",
              [Row(stars_label(k), (v["has_either"],), f"of {v['n']:,}", highlight=k.endswith("max")) for k, v in stars], source),
        Chart("adoption-by-file", "AGENTS.md is the common format; tool-specific files trail far behind",
              f"Repos shipping each file. {a:,} repos with 1,000+ stars and a sample of {b:,} with 100 to 999.",
              [Row(label, (ad["A"][k], ad["B"][k])) for k, label in files], source, ("1,000+ stars", "100 to 999 stars")),
        Chart("sections-agents", f"Only {percent(sec['agents_md'])} of AGENTS.md files have a security section",
              f"AGENTS.md files with a heading in each category, top 12 of 17. {census}",
              section_rows(fa["agents_md"]["sections"]), source),
        Chart("sections-claude", f"Only {percent(sec['claude_md'])} of CLAUDE.md files have a security section",
              f"CLAUDE.md files with a heading in each category, top 12 of 17. {census}",
              section_rows(fa["claude_md"]["sections"]), source),
        Chart("commands", "CLAUDE.md files give the agent fewer exact commands than AGENTS.md",
              f"Files with each kind of command in a code block or inline code. {census}",
              [Row(label, (fa["claude_md"][k], fa["agents_md"][k])) for k, label in cmd], source, ("CLAUDE.md", "AGENTS.md")),
        Chart("both-files", f"In {percent(both['link_share']['none'])} of repos with both files, CLAUDE.md never points to AGENTS.md",
              f"What a root CLAUDE.md does with the AGENTS.md beside it, in the {both['repos_A']:,} census repos that have both. "
              "Claude Code reads AGENTS.md only when there is no CLAUDE.md.",
              [Row(LINK_LABELS[k], (v,), highlight=k == "none") for k, v in link], source),
    ]


def main() -> None:
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    built = charts(json.loads((data / "summary.json").read_text()))
    label_w = label_column(built)
    for chart in built:
        d = layout(chart, label_w, with_source=True)
        for theme, suffix in (("light", ""), ("dark", "-dark")):
            svg_text = standalone_svg(d, theme)
            (out / f"{chart.slug}{suffix}.svg").write_text(svg_text)
            (out / f"{chart.slug}{suffix}.png").write_bytes(png(svg_text))
    (out / "post-figures.html").write_text("\n\n".join(f"<!-- {c.slug} -->\n{figure(c, label_w)}" for c in built) + "\n")
    print(f"{len(built)} charts written to {out}")


if __name__ == "__main__":
    main()
