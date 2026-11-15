import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentfiles.cli import main
from agentfiles.discover import is_link_to_sibling_agents_md

LONG_CLAUDE = "# Claude\n\n" + "\n".join(f"- rule {i}" for i in range(210)) + "\n"


def run(*args: str) -> tuple[int, dict]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["lint", "--format", "json", *args])
    return code, json.loads(out.getvalue() or "{}")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        return path

    def rules(self, payload: dict, file: str | None = None) -> set[str]:
        return {f["rule"] for f in payload["findings"] if file is None or f["file"] == file}

    def test_broken_symlink_does_not_crash(self):
        (self.root / "AGENTS.md").symlink_to(self.root / "missing.md")
        code, _ = run(str(self.root / "AGENTS.md"))
        self.assertEqual(code, 2)

    def test_claude_symlink_to_agents_is_not_linted_twice(self):
        self.write("AGENTS.md", LONG_CLAUDE)
        (self.root / "CLAUDE.md").symlink_to("AGENTS.md")
        _, payload = run(str(self.root))
        self.assertEqual({f["file"] for f in payload["findings"]}, {"AGENTS.md"})

    def test_claude_symlink_to_other_file_keeps_claude_kind(self):
        self.write("docs/agent-notes.md", LONG_CLAUDE)
        (self.root / "CLAUDE.md").symlink_to("docs/agent-notes.md")
        _, payload = run(str(self.root / "CLAUDE.md"))
        self.assertIn("AF201", self.rules(payload))

    def test_non_agent_file_is_skipped(self):
        self.write("README.md", "# Readme\n")
        code, payload = run(str(self.root / "README.md"))
        self.assertEqual((code, payload["findings"]), (0, []))

    def test_import_resolves_from_the_importing_file(self):
        self.write(".claude/rules/style.md", "Use tabs.\n")
        self.write("docs/rules.md", "Use tabs.\n")
        self.write(".claude/CLAUDE.md", "# Claude\n\n@rules/style.md\n@docs/rules.md\n")
        _, payload = run(str(self.root / ".claude" / "CLAUDE.md"))
        messages = [f["message"] for f in payload["findings"] if f["rule"] == "AF402"]
        self.assertEqual(messages, ["@docs/rules.md not found"])

    def test_path_found_under_a_package_folder(self):
        self.write("packages/api/src/server.ts", "")
        self.write("AGENTS.md", "# A\n\nEntry: `src/server.ts`; old: `src/legacy.ts`.\n`pnpm test` and `pnpm lint`.\n")
        _, payload = run(str(self.root))
        messages = [f["message"] for f in payload["findings"] if f["rule"] == "AF401"]
        self.assertEqual(messages, ["`src/legacy.ts` not found"])

    def test_dot_claude_symlink_to_root_agents_md(self):
        self.write("AGENTS.md", "# A\n\n`pnpm test` and `pnpm lint`.\n")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "CLAUDE.md").symlink_to("../AGENTS.md")
        self.assertTrue(is_link_to_sibling_agents_md(self.root / ".claude" / "CLAUDE.md"))
        _, payload = run(str(self.root))
        self.assertEqual({f["file"] for f in payload["findings"]} - {"AGENTS.md"}, set())

    def test_crlf_bytes_count_toward_the_32k_limit(self):
        line = "x" * 98 + "\r\n"
        self.write("AGENTS.md", "# A\r\n\r\n`pnpm test` and `pnpm lint`.\r\n" + line * 330)
        self.assertGreater((self.root / "AGENTS.md").stat().st_size, 32 * 1024)
        _, payload = run(str(self.root))
        self.assertIn("AF202", self.rules(payload))

    def test_missing_path_argument_exits_2(self):
        self.write("AGENTS.md", "# A\n\n`pnpm test` and `pnpm lint`.\n")
        code, _ = run(str(self.root / "AGENTS.md"), str(self.root / "typo" / "AGENTS.md"))
        self.assertEqual(code, 2)

    def test_folder_without_git_is_the_root(self):
        (self.root / ".git").rmdir()
        self.write("src/main.py", "")
        self.write("sub/AGENTS.md", "# A\n\nSee `src/main.py`.\n`pnpm test` and `pnpm lint`.\n")
        _, payload = run(str(self.root))
        self.assertNotIn("AF401", self.rules(payload))
        self.assertEqual({f["file"] for f in payload["findings"]}, set())

    def test_exit_code_on_error(self):
        self.write("AGENTS.md", "# A\n\nkey: AKIAZ7Q2M4N8P3R6T5W1\n`pnpm test` and `pnpm lint`.\n")
        code, _ = run(str(self.root))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
