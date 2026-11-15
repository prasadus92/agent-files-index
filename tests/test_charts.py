import json
import unittest
from pathlib import Path

try:
    from pipeline import charts
except ImportError:
    charts = None

SUMMARY = json.loads((Path(__file__).parent.parent / "data" / "summary.json").read_text())


@unittest.skipUnless(charts, "chart layout needs fonttools")
class ChartTests(unittest.TestCase):
    def setUp(self):
        self.built = {c.slug: c for c in charts.charts(SUMMARY)}
        self.label_w = charts.label_column(list(self.built.values()))

    def test_wrapped_text_never_ends_on_a_lone_word(self):
        text = "Repos with a root AGENTS.md or CLAUDE.md, by star count. Census of 38,272 public GitHub repos with 1,000+ stars."
        lines = charts.wrap(text, "subtitle", charts.WIDTH)
        self.assertEqual(len(lines), 2)
        self.assertGreater(len(lines[-1].split()), 1)

    def test_security_always_shown_and_highlighted(self):
        sections = {f"cat{i}": 50.0 - i for i in range(16)} | {"security": 1.0}
        rows = charts.section_rows(sections)
        self.assertEqual(len(rows), 12)
        self.assertEqual([r.label for r in rows if r.highlight], ["Security"])

    def test_bars_sorted_by_value(self):
        for slug in ("adoption-by-file", "both-files", "sections-claude"):
            values = [r.values[0] for r in self.built[slug].rows if not r.highlight or slug != "sections-claude"]
            self.assertEqual(values, sorted(values, reverse=True), slug)

    def test_text_stays_inside_the_canvas(self):
        for chart in self.built.values():
            d = charts.layout(chart, self.label_w, with_source=True)
            for s in d.shapes:
                if isinstance(s, charts.Text):
                    self.assertLessEqual(s.x + charts.text_width(s.text, s.role), charts.WIDTH + 0.5, (chart.slug, s.text))

    def test_every_chart_shares_the_label_column(self):
        for chart in self.built.values():
            d = charts.layout(chart, self.label_w, with_source=False)
            starts = {round(s.x, 1) for s in d.shapes if isinstance(s, charts.Bar) and s.w != 10}
            self.assertEqual(starts, {round(self.label_w, 1)}, chart.slug)

    def test_post_figure_has_no_blank_lines(self):
        for chart in self.built.values():
            self.assertNotIn("\n\n", charts.figure(chart, self.label_w))
