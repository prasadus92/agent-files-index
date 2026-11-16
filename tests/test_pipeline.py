import gzip
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import github, opt_out, paths_from_argv

try:
    import pandas as pd

    from pipeline.export import build, publishable_headings
    from pipeline.store import RawStore
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

    def test_heading_of_exactly_eight_words_is_published(self):
        self.assertEqual(self.published("keep it simple and match what is there"), "keep it simple and match what is there")

    def test_long_heading_is_blanked(self):
        self.assertEqual(self.published("step 1: spawn all runs with skill and baseline together"), "")

    def test_heading_with_url_or_email_is_blanked(self):
        self.assertEqual(self.published("see https://example.org"), "")
        self.assertEqual(self.published("mail dev@example.org"), "")


class OptOutListTests(unittest.TestCase):
    def test_list_ignores_comments_blanks_and_case(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "opt_out.txt"
            path.write_text(f"# header\n\n{opt_out.digest(42).upper()}  # 2026-11-20\n")
            self.assertEqual(opt_out.load(path), {opt_out.digest(42)})

    def test_repo_is_matched_by_id_whatever_its_current_name(self):
        repos = {"new-owner/renamed": {"repo_id": 42}, "other/repo": {"repo_id": 7}}
        self.assertEqual(list(opt_out.keep(repos, {opt_out.digest(42)})), ["other/repo"])

    def test_repo_id_is_found_by_name_in_any_case(self):
        with tempfile.TemporaryDirectory() as d:
            with gzip.open(Path(d) / "repos.csv.gz", "wt") as f:
                f.write("snapshot,repo,repo_id\n2026-11-15,Owner/Repo,42\n")
            self.assertEqual(opt_out.repo_id(Path(d), "owner/repo"), 42)
            with self.assertRaises(SystemExit):
                opt_out.repo_id(Path(d), "missing/repo")

    def test_added_entry_survives_a_missing_final_newline_and_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "opt_out.txt"
            path.write_text("# header")
            opt_out.add(opt_out.digest(42), path)
            opt_out.add(opt_out.digest(42), path)
            self.assertEqual(opt_out.load(path), {opt_out.digest(42)})
            self.assertEqual(path.read_text().count(opt_out.digest(42)), 1)

    def test_numeric_argument_is_taken_as_the_id(self):
        self.assertEqual(opt_out.repo_id(Path("unused"), "42"), 42)


AGENTS_TEXT = "# Testing\n\nRun `pytest` before you push.\n\nNotes live in /Users/alice/notes.\n"


def raw_repo(name: str, repo_id: int) -> dict:
    return {"repo": name, "repo_id": repo_id, "stratum": "A", "stars": 1000, "forks": 1, "language": "Python",
            "license": "MIT", "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2026-11-01T00:00:00Z",
            "is_template": False, "disk_kb": 1, "head_sha": "a" * 40, "root": [{"name": "AGENTS.md", "type": "blob", "mode": 33188}],
            "dotclaude": None, "dotgithub": None, "dotagents": None, "dotcursor": None}


def raw_file(name: str) -> dict:
    return {"repo": name, "path": "AGENTS.md", "kind": "agents_md", "text": AGENTS_TEXT, "head_sha": "a" * 40,
            "blob_sha": "b" * 40, "is_symlink": False, "is_truncated": False, "n_commits": 1,
            "last_commit_at": "2026-11-01T00:00:00Z"}


@unittest.skipUnless(pd, "export tests need pandas")
class OptOutExportTests(unittest.TestCase):
    def test_opted_out_repo_is_absent_from_every_table(self):
        with tempfile.TemporaryDirectory() as d:
            store = RawStore(Path(d))
            store.append("repos_A.jsonl", [raw_repo("keep/me", 1), raw_repo("drop/me", 2)])
            store.append("files.jsonl", [raw_file("keep/me"), raw_file("drop/me")])
            tables = build(store, {opt_out.digest(2)})
        for name in ("repos", "files", "headings", "commands", "lint_findings"):
            self.assertEqual(set(tables[name].repo), {"keep/me"}, name)
        self.assertEqual(tables["risky_text_summary"].files.tolist(), [1])


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
