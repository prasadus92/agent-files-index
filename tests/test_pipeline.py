import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import github, paths_from_argv

try:
    import pandas as pd

    from pipeline.export import opted_out, publishable_headings, without_opted_out
except ImportError:
    pd = None


@unittest.skipUnless(pd, "export tests need pandas")
class PublishableHeadingTests(unittest.TestCase):
    def published(self, heading: str, repos: int = 5) -> str:
        df = pd.DataFrame({"repo": [f"o/r{i}" for i in range(repos)], "heading": [heading] * repos})
        return publishable_headings(df).heading.iloc[0]

    def test_common_short_heading_is_published(self):
        self.assertEqual(self.published("testing"), "testing")

    def test_heading_shared_by_too_few_repos_is_blanked(self):
        self.assertEqual(self.published("testing", repos=4), "")

    def test_long_heading_is_blanked(self):
        self.assertEqual(self.published("step 1: spawn all runs with skill and baseline together"), "")

    def test_heading_with_url_or_email_is_blanked(self):
        self.assertEqual(self.published("see https://example.org"), "")
        self.assertEqual(self.published("mail dev@example.org"), "")


@unittest.skipUnless(pd, "export tests need pandas")
class OptOutTests(unittest.TestCase):
    def test_opt_out_list_ignores_comments_blanks_and_case(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "opt_out.txt"
            path.write_text("# header\n\nOwner/Repo  # asked 2026-11-20\n")
            self.assertEqual(opted_out(path), {"owner/repo"})

    def test_opted_out_repo_is_dropped_whatever_its_case(self):
        repos = {"Owner/Repo": {}, "other/repo": {}}
        self.assertEqual(list(without_opted_out(repos, {"owner/repo"})), ["other/repo"])


class ArgvTests(unittest.TestCase):
    def test_paths_are_returned_in_order(self):
        with mock.patch.object(sys, "argv", ["pipeline/export.py", "raw", "data"]):
            self.assertEqual(paths_from_argv("RAW_DIR", "OUT_DIR"), [Path("raw"), Path("data")])

    def test_missing_argument_exits_with_usage(self):
        with mock.patch.object(sys, "argv", ["pipeline/export.py", "raw"]), self.assertRaises(SystemExit) as exit:
            paths_from_argv("RAW_DIR", "OUT_DIR")
        self.assertEqual(str(exit.exception.code), "usage: python -m pipeline.export RAW_DIR OUT_DIR")


class TokenTests(unittest.TestCase):
    def tearDown(self):
        github.token.cache_clear()

    def test_environment_token_wins_over_gh(self):
        github.token.cache_clear()
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"}), mock.patch.object(github.subprocess, "check_output") as gh:
            self.assertEqual(github.token(), "env-token")
        gh.assert_not_called()

    def test_gh_is_used_without_environment_token(self):
        github.token.cache_clear()
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(github.subprocess, "check_output", return_value="gh-token\n"):
            self.assertEqual(github.token(), "gh-token")


if __name__ == "__main__":
    unittest.main()
