"""Render charts from summary.json: dg-class SVG snippets for prasad.tech and PNGs for the README.

Usage: python scripts/make_charts.py DATA_DIR CHART_DIR
"""
from __future__ import annotations

import html
import textwrap
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROW_H, BAR_H, LABEL_W, BAR_W, WIDTH = 30, 18, 230, 330, 640


def svg_hbar(title: str, rows: list[tuple[str, float, str | None]], max_value: float, note: str, accent_first: bool = False) -> str:
    """rows: (label, value, display text). Values are percentages unless display text says otherwise."""
    height = 40 + ROW_H * len(rows) + 30
    out = [f'<svg viewBox="0 0 {WIDTH} {height}" role="presentation" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">',
           f'<text class="tk" x="0" y="20">{html.escape(title)}</text>']
    for i, (label, value, shown) in enumerate(rows):
        y = 40 + i * ROW_H
        w = max(1.5, BAR_W * value / max_value) if max_value else 0
        cls = "box-accent" if (accent_first and i == 0) or not accent_first else "box"
        out.append(f'<text class="t" x="0" y="{y + 14}" style="font-size:13.5px">{html.escape(label)}</text>')
        out.append(f'<rect class="{cls}" x="{LABEL_W}" y="{y}" width="{w:.1f}" height="{BAR_H}" rx="2"/>')
        out.append(f'<text class="ts" x="{LABEL_W + w + 8:.1f}" y="{y + 14}">{html.escape(shown or f"{value:.1f}%")}</text>')
    out.append(f'<text class="tn" x="0" y="{height - 8}">{html.escape(note)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def figure(aria: str, svg: str, caption: str) -> str:
    return (f'<figure class="dg" aria-label="{html.escape(aria, quote=True)}">\n<div class="dg-canvas">\n{svg}\n</div>\n'
            f"<figcaption>{html.escape(caption)}</figcaption>\n</figure>")


def png_hbar(path: Path, title: str, rows: list[tuple[str, float, str | None]], xlabel: str) -> None:
    labels = [r[0] for r in rows][::-1]
    values = [0.0 if r[1] != r[1] else r[1] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 0.42 * len(rows) + 1.2), dpi=150)
    bars = ax.barh(labels, values, color="#e5241c", height=0.6)
    for b, r in zip(bars, rows[::-1]):
        ax.text(b.get_width() + max(values) * 0.01, b.get_y() + b.get_height() / 2, r[2] or f"{r[1]:.1f}%", va="center", fontsize=9)
    fig.suptitle(textwrap.fill(title, 80), x=0.01, ha="left", fontsize=11, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(values) * 1.18 if values else 1)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _stars_label(key: str) -> str:
    lo, hi = key.split("-")
    return f"{int(lo):,}+ stars" if hi == "max" else f"{int(lo):,} to {int(hi):,} stars"


def main() -> None:
    data, charts = Path(sys.argv[1]), Path(sys.argv[2])
    charts.mkdir(parents=True, exist_ok=True)
    s = json.loads((data / "summary.json").read_text())
    nA = s["frame"]["A_repos"]
    specs = []

    by_stars = s["adoption_by_stars_A"]
    rows = [(_stars_label(k), v["has_either"], f"{v['has_either']:.1f}% of {v['n']:,}") for k, v in by_stars.items()]
    specs.append(("adoption-by-stars", f"Repos with AGENTS.md or CLAUDE.md at the root, by stars ({nA:,} repos)", rows,
                  f"Census of public repos with 1,000+ stars pushed in the last 12 months.",
                  "Share of repos with a root AGENTS.md or CLAUDE.md rises with stars."))

    ad = s["adoption"]
    labels = [("has_agents_md", "AGENTS.md"), ("has_claude_any", "CLAUDE.md"), ("has_skills", "SKILL.md (skills folder)"),
              ("has_copilot", "Copilot instructions"), ("has_cursor", "Cursor rules"), ("has_gemini_md", "GEMINI.md"),
              ("has_mcp_json", ".mcp.json")]
    rows = [(lab, ad["A"][k], f"{ad['A'][k]:.1f}% (100 to 999 stars: {ad['B'][k]:.1f}%)") for k, lab in labels]
    specs.append(("adoption-by-file", "Which agent files repos ship (1,000+ stars)", rows,
                  f"{s['frame']['A_repos']:,} repos with 1,000+ stars; {s['frame']['B_repos']:,} sampled repos with 100 to 999.",
                  "AGENTS.md leads, then CLAUDE.md, then skills folders."))

    files = s["files"]
    rows = [(f"{k.replace('_', ' ')}", v, None) for k, v in sorted(files["claude_md"]["sections"].items(), key=lambda kv: -kv[1])[:12]]
    specs.append(("sections-claude", "Sections found in CLAUDE.md files", rows,
                  f"{files['claude_md']['n']:,} CLAUDE.md files; headings matched to 17 categories.",
                  "The section categories CLAUDE.md files cover."))
    rows = [(f"{k.replace('_', ' ')}", v, None) for k, v in sorted(files["agents_md"]["sections"].items(), key=lambda kv: -kv[1])[:12]]
    specs.append(("sections-agents", "Sections found in AGENTS.md files", rows,
                  f"{files['agents_md']['n']:,} AGENTS.md files; headings matched to 17 categories.",
                  "The section categories AGENTS.md files cover."))

    rows = []
    for kind, lab in (("agents_md", "AGENTS.md"), ("claude_md", "CLAUDE.md")):
        f = files[kind]
        rows += [(f"{lab}: any command", f["has_any_command"], None), (f"{lab}: a test command", f["has_test_cmd"], None),
                 (f"{lab}: a lint command", f["has_lint_cmd"], None)]
    specs.append(("commands", "Files that tell the agent which command to run", rows,
                  "Commands found in shell code blocks or inline code.", "How many files give the agent exact commands."))

    b = s["both_files"]
    ls = b["link_share"]
    rows = [("Symlink to AGENTS.md", ls.get("symlink", 0.0), None),
            ("Imports it with @AGENTS.md", ls.get("import", 0.0), None),
            ("Mentions it in the text", ls.get("mention", 0.0), None),
            ("Never mentions it", ls.get("none", 0.0), None)]
    specs.append(("both-files", f"What CLAUDE.md does with AGENTS.md ({b['claude_md_files']:,} repos with both)", rows,
                  "Claude Code reads AGENTS.md only when no CLAUDE.md exists.", "How CLAUDE.md connects to AGENTS.md in repos that ship both."))

    snippets = []
    for name, title, rows, note, caption in specs:
        max_v = max((r[1] for r in rows), default=1) or 1
        svg = svg_hbar(title, rows, max_v * 1.05, note)
        (charts / f"{name}.svg").write_text(svg)
        snippets.append(f"<!-- {name} -->\n" + figure(title, svg, caption))
        png_hbar(charts / f"{name}.png", title, rows, "% of files" if "Section" in title or "command" in title else "% of repos")
    (charts / "post-figures.html").write_text("\n\n".join(snippets))
    print(f"{len(specs)} charts written to {charts}")


if __name__ == "__main__":
    main()
