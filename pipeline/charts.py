"""Step 7: render charts from summary.json, as figure.dg SVG for prasad.tech and PNG for the README.

Usage: python -m pipeline.charts DATA_DIR CHART_DIR
"""
from __future__ import annotations

import html
import json
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROW_H, BAR_H, LABEL_W, BAR_W, WIDTH = 30, 18, 220, 240, 720
ACCENT = "#e5241c"


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    shown: str | None = None

    @property
    def text(self) -> str:
        return self.shown or f"{self.value:.1f}%"


@dataclass(frozen=True)
class Chart:
    slug: str
    title: str
    bars: list[Bar]
    note: str
    caption: str
    axis: str = "% of repos"


def svg(chart: Chart) -> str:
    """Uses the site's .dg classes so 1 drawing works in light and dark themes."""
    top = max((b.value for b in chart.bars), default=1) * 1.05 or 1
    height = 40 + ROW_H * len(chart.bars) + 30
    out = [f'<svg viewBox="0 0 {WIDTH} {height}" role="presentation" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">',
           f'<text class="tk" x="0" y="20">{html.escape(chart.title)}</text>']
    for i, bar in enumerate(chart.bars):
        y, w = 40 + i * ROW_H, max(1.5, BAR_W * bar.value / top)
        out += [f'<text class="t" x="0" y="{y + 14}" style="font-size:13.5px">{html.escape(bar.label)}</text>',
                f'<rect class="box-accent" x="{LABEL_W}" y="{y}" width="{w:.1f}" height="{BAR_H}" rx="2"/>',
                f'<text class="ts" x="{LABEL_W + w + 8:.1f}" y="{y + 14}">{html.escape(bar.text)}</text>']
    out += [f'<text class="tn" x="0" y="{height - 8}">{html.escape(chart.note)}</text>', "</svg>"]
    return "\n".join(out)


def figure(chart: Chart) -> str:
    return (f'<figure class="dg" aria-label="{html.escape(chart.title, quote=True)}">\n<div class="dg-canvas">\n{svg(chart)}\n'
            f"</div>\n<figcaption>{html.escape(chart.caption)}</figcaption>\n</figure>")


def png(chart: Chart, path: Path) -> None:
    bars = chart.bars[::-1]
    values = [b.value for b in bars]
    fig, ax = plt.subplots(figsize=(7.5, 0.42 * len(bars) + 1.2), dpi=150)
    drawn = ax.barh([b.label for b in bars], values, color=ACCENT, height=0.6)
    for rect, bar in zip(drawn, bars):
        ax.text(rect.get_width() + max(values) * 0.01, rect.get_y() + rect.get_height() / 2, bar.text, va="center", fontsize=9)
    fig.suptitle(textwrap.fill(chart.title, 80), x=0.01, ha="left", fontsize=11, fontweight="bold")
    ax.set_xlabel(chart.axis)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(values) * 1.18)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def stars_label(key: str) -> str:
    lo, hi = key.split("-")
    return f"{int(lo):,}+ stars" if hi == "max" else f"{int(lo):,} to {int(hi):,} stars"


def section_bars(sections: dict[str, float]) -> list[Bar]:
    return [Bar(k.replace("_", " "), v) for k, v in sorted(sections.items(), key=lambda kv: -kv[1])[:12]]


def charts(s: dict) -> list[Chart]:
    a, ad, fa, both = s["frame"]["A_repos"], s["adoption"], s["files_A"], s["both_files"]
    files_note = "Files in the census of repos with 1,000+ stars; headings matched to 17 categories."
    link = both["link_share"]
    return [
        Chart("adoption-by-stars", f"Repos with an AGENTS.md or CLAUDE.md, by stars ({a:,} repos)",
              [Bar(stars_label(k), v["has_either"], f"{v['has_either']:.1f}% of {v['n']:,}") for k, v in ad["by_stars_A"].items()],
              "Census of public repos with 1,000+ stars pushed in the last 12 months.",
              "The share of repos with an AGENTS.md or CLAUDE.md rises with stars."),
        Chart("adoption-by-file", "Which agent files repos ship (1,000+ stars)",
              [Bar(label, ad["A"][k], f"{ad['A'][k]:.1f}% (100 to 999 stars: {ad['B'][k]:.1f}%)") for k, label in (
                  ("has_agents_md", "AGENTS.md"), ("has_claude_any", "CLAUDE.md"), ("has_skills", "SKILL.md (skills folder)"),
                  ("has_copilot", "Copilot instructions"), ("has_cursor", "Cursor rules"), ("has_gemini_md", "GEMINI.md"),
                  ("has_mcp_json", ".mcp.json"))],
              f"{a:,} repos with 1,000+ stars; {s['frame']['B_repos']:,} sampled repos with 100 to 999.",
              "AGENTS.md leads, then CLAUDE.md, then skills folders."),
        Chart("sections-agents", "Sections found in AGENTS.md files", section_bars(fa["agents_md"]["sections"]),
              files_note, "The section categories AGENTS.md files cover.", "% of files"),
        Chart("sections-claude", "Sections found in CLAUDE.md files", section_bars(fa["claude_md"]["sections"]),
              files_note, "The section categories CLAUDE.md files cover.", "% of files"),
        Chart("commands", "Files that tell the agent which command to run",
              [Bar(f"{label}: {what}", fa[kind][key]) for kind, label in (("agents_md", "AGENTS.md"), ("claude_md", "CLAUDE.md"))
               for what, key in (("any command", "has_any_command"), ("a test command", "has_test_cmd"), ("a lint command", "has_lint_cmd"))],
              "Commands found in shell code blocks or inline code, census files.",
              "How many files give the agent exact commands.", "% of files"),
        Chart("both-files", f"What CLAUDE.md does with AGENTS.md ({both['repos_A']:,} repos with both)",
              [Bar("Symlink to AGENTS.md", link.get("symlink", 0.0)), Bar("Imports it with @AGENTS.md", link.get("import", 0.0)),
               Bar("Mentions it in the text", link.get("mention", 0.0)), Bar("Never mentions it", link.get("none", 0.0))],
              "Claude Code reads AGENTS.md only when no CLAUDE.md exists.",
              "How CLAUDE.md connects to AGENTS.md in repos that ship both."),
    ]


def main() -> None:
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    built = charts(json.loads((data / "summary.json").read_text()))
    for chart in built:
        (out / f"{chart.slug}.svg").write_text(svg(chart))
        png(chart, out / f"{chart.slug}.png")
    (out / "post-figures.html").write_text("\n\n".join(f"<!-- {c.slug} -->\n{figure(c)}" for c in built))
    print(f"{len(built)} charts written to {out}")


if __name__ == "__main__":
    main()
