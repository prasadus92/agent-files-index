"""Lint rules for AGENTS.md, CLAUDE.md and SKILL.md. Each rule cites its source in RULES."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .parse import Features, parse

ERROR, WARN, INFO = "error", "warning", "info"
SEVERITY_ORDER = {INFO: 0, WARN: 1, ERROR: 2}

# id -> (severity, short title, source). Thresholds marked "data" come from the Agent Files Index sample.
RULES: dict[str, tuple[str, str, str]] = {
    "AF101": (ERROR, "secret-like string", "GitHub blog, agents.md lessons from 2,500 repos: never commit secrets"),
    "AF102": (WARN, "absolute home-directory path", "data: paths like /Users/<name>/ only work on one machine"),
    "AF103": (WARN, "prompt-injection-like text", "data: unquoted text telling the agent to ignore instructions or hide actions from the user"),
    "AF104": (INFO, "pipes a downloaded script into a shell", "data: curl | sh runs remote code the agent cannot inspect first"),
    "AF201": (WARN, "CLAUDE.md longer than 200 lines", "code.claude.com/docs/en/memory: target under 200 lines per CLAUDE.md"),
    "AF202": (ERROR, "AGENTS.md larger than 32 KiB", "Codex AGENTS.md docs: project_doc_max_bytes defaults to 32 KiB; the rest is dropped"),
    "AF203": (WARN, "SKILL.md body longer than 500 lines", "agentskills.io specification: keep SKILL.md under 500 lines"),
    "AF204": (WARN, "file is empty or nearly empty", "Codex AGENTS.md docs: empty files are skipped"),
    "AF301": (WARN, "no test command", "agents.md, Claude Code best practices: list the exact test command"),
    "AF302": (INFO, "no build, lint or typecheck command", "Claude Code best practices: exact build, typecheck and lint commands"),
    "AF303": (WARN, "install commands use more than one JS package manager", "data: mixed npm, pnpm, yarn and bun installs give the agent two answers"),
    "AF304": (WARN, "long file without headings", "code.claude.com/docs/en/memory: group instructions under markdown headers"),
    "AF305": (INFO, "vague instruction", "code.claude.com/docs/en/memory: write verifiable instructions"),
    "AF306": (INFO, "heavy use of emphasis words", "Claude Code best practices: IMPORTANT on an ignored rule rarely fixes it"),
    "AF401": (WARN, "referenced path does not exist", "data: stale paths send the agent to files that are gone"),
    "AF402": (ERROR, "@import target does not exist", "code.claude.com/docs/en/memory: @path imports load the file into context"),
    "AF403": (INFO, "@import syntax in AGENTS.md", "agents.md: plain Markdown, no import syntax; only Claude Code expands @path"),
    "AF501": (ERROR, "SKILL.md has no YAML frontmatter", "agentskills.io specification: name and description are required"),
    "AF502": (ERROR, "invalid skill name", "agentskills.io specification: 1 to 64 lowercase letters, digits, hyphens; matches folder"),
    "AF503": (ERROR, "missing or over-long skill description", "agentskills.io specification: description is required, at most 1,024 characters"),
    "AF504": (WARN, "skill description in first or second person", "Anthropic skill authoring best practices: write the description in third person"),
    "AF505": (WARN, "reserved word in skill name", "Anthropic skill authoring best practices: name must not contain anthropic or claude"),
    "AF601": (WARN, "CLAUDE.md never mentions AGENTS.md", "code.claude.com/docs/en/memory: Claude reads AGENTS.md only when no CLAUDE.md exists"),
    "AF602": (INFO, "CLAUDE.md duplicates AGENTS.md", "data: copies drift; a symlink or @AGENTS.md keeps one source"),
}

CLAUDE_MAX_LINES = 200
AGENTS_MAX_BYTES = 32 * 1024
SKILL_MAX_BODY_LINES = 500
SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$|^[a-z0-9]$")
EMPHASIS_LIMIT = 10
HEADINGLESS_LIMIT = 30
CHECKABLE_PREFIXES = ("src/", "lib/", "app/", "apps/", "packages/", "docs/", "test/", "tests/", "scripts/", "cmd/",
                      "internal/", "pkg/", ".github/", ".claude/", "crates/", "services/", "server/", "client/", "web/")
PLACEHOLDER_PATH_RE = re.compile(r"(?i)\.\.\./|yyyy|mmdd|x{3,}|x\.y\.z|\byour[-_]|example|\bfoo\b|\bbar\b|\bmy[-_]|\.env|\.local\.|\*")
GENERATED_DIRS = {"dist", "build", "out", "target", "node_modules", ".next", "coverage", ".venv", "venv", "tmp", ".cache",
                  "logs", "bin", "obj", "__pycache__", ".turbo", ".output"}
CHECKABLE_EXT_RE = re.compile(r"\.(?:md|mdx|ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|toml|json|ya?ml|sh|rb|cs|swift|sql|cfg|ini|txt|lock)$")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    line: int | None = None

    @property
    def title(self) -> str:
        return RULES[self.rule][1]


def kind_for(path: str) -> str | None:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return {"agents.md": "agents_md", "claude.md": "claude_md", "skill.md": "skill_md"}.get(name)


def checkable_path(p: str, explicit_link: bool = False) -> bool:
    """Bare file names in inline code are ambiguous (they may live anywhere), so inline paths need a folder part."""
    p = p.split("?")[0]
    if not p or p.startswith(("http", "mailto:", "#", "@", "-", "~", "$")) or "{" in p or "<" in p or "%" in p:
        return False
    if PLACEHOLDER_PATH_RE.search(p) or p.lstrip("./").split("/")[0] in GENERATED_DIRS:
        return False
    if explicit_link:
        return True
    if "/" not in p.rstrip("/"):
        return False
    if p.endswith("/"):
        return p.startswith(CHECKABLE_PREFIXES)
    return bool(CHECKABLE_EXT_RE.search(p)) or p.startswith(("./", "../") + CHECKABLE_PREFIXES)


def missing_paths(f: Features, exists: Callable[[str], bool | None]) -> list[str]:
    links = set(f.relative_links)
    return [p for p in f.referenced_paths if checkable_path(p, p in links) and exists(p) is False]


def _line_of(text: str, needle: str) -> int | None:
    idx = text.find(needle)
    return text.count("\n", 0, idx) + 1 if idx >= 0 else None


def lint(
    text: str,
    kind: str,
    path: str = "",
    exists: Callable[[str], bool | None] | None = None,
    siblings: dict[str, str] | None = None,
    features: Features | None = None,
) -> list[Finding]:
    """Lint one file.

    exists(path) resolves a repo-relative path and returns True, False or None (unknown).
    siblings maps other agent files in the same folder (by lower-case name) to their text.
    """
    f = features or parse(text)
    out: list[Finding] = []
    add = lambda rule, msg, line=None: out.append(Finding(rule, RULES[rule][0], msg, line))  # noqa: E731

    for name, n in sorted(f.secret_hits.items()):
        add("AF101", f"{n} {name.replace('_', ' ')} match(es); remove and rotate if real")
    if f.home_paths:
        add("AF102", f"{f.home_paths} absolute home-directory path(s); use repo-relative paths")
    if f.injection_hits:
        add("AF103", f"{f.injection_hits} phrase(s) tell the agent to ignore instructions or keep something from the user")
    if f.pipe_shell_hits:
        add("AF104", f"{f.pipe_shell_hits} curl or wget piped into a shell; pin a version or point to the install docs")

    if f.nonblank_lines < 3 and not f.imports and kind != "skill_md":
        add("AF204", f"only {f.nonblank_lines} non-blank line(s)")
    if kind == "claude_md" and f.lines > CLAUDE_MAX_LINES:
        add("AF201", f"{f.lines} lines; move task-specific detail into skills or .claude/rules/")
    if kind == "agents_md" and f.bytes > AGENTS_MAX_BYTES:
        add("AF202", f"{f.bytes:,} bytes; Codex drops everything after {AGENTS_MAX_BYTES:,}")
    if kind == "skill_md" and f.body_lines > SKILL_MAX_BODY_LINES:
        add("AF203", f"body is {f.body_lines} lines; move reference material into separate files")

    if kind in ("agents_md", "claude_md") and f.nonblank_lines >= 3 and not _is_pointer(f):
        kinds = f.command_kinds()
        if not kinds.get("test"):
            add("AF301", "no test command found in a code block or inline code")
        if not (kinds.get("build") or kinds.get("lint") or kinds.get("typecheck")):
            add("AF302", "no build, lint or typecheck command found")
        if len(f.package_managers) > 1:
            add("AF303", "commands use " + ", ".join(sorted(f.package_managers)))
    if f.nonblank_lines > HEADINGLESS_LIMIT and not f.headings:
        add("AF304", f"{f.nonblank_lines} non-blank lines and no markdown headings")
    if f.vague_phrases:
        add("AF305", f"{f.vague_phrases} vague phrase(s) such as 'follow best practices'; say the exact rule")
    if f.n_emphasis_caps > EMPHASIS_LIMIT:
        add("AF306", f"{f.n_emphasis_caps} uses of IMPORTANT, MUST, NEVER, ALWAYS or CRITICAL")

    if exists is not None and kind != "skill_md":
        for p in missing_paths(f, exists)[:20]:
            add("AF401", f"`{p}` not found", _line_of(text, p))
        if kind == "claude_md":
            for imp in f.imports:
                if exists(imp.lstrip("./") if imp.startswith("./") else imp) is False and not imp.startswith("~"):
                    add("AF402", f"@{imp} not found", _line_of(text, "@" + imp))
    if kind == "agents_md" and f.imports:
        add("AF403", f"{len(f.imports)} @path line(s); other AGENTS.md readers see them as plain text")

    if kind == "skill_md":
        out.extend(_lint_skill(f, path, add))

    if kind == "claude_md" and siblings and "agents.md" in siblings:
        if agents_md_link(text) == "none":
            add("AF601", "AGENTS.md sits next to this file and is never mentioned; add @AGENTS.md or symlink CLAUDE.md to it")
        if similarity(text, siblings["agents.md"]) >= 0.9:
            add("AF602", "content is at least 90% the same as AGENTS.md")
    return out


def _is_pointer(f: Features) -> bool:
    """A short file that hands off to another file (for example 'See AGENTS.md' or '@AGENTS.md')."""
    return f.nonblank_lines <= 5 and (bool(f.imports) or bool(f.relative_links) or "agents.md" in " ".join(f.referenced_paths).lower())


def agents_md_link(text: str) -> str:
    """How a CLAUDE.md connects to a sibling AGENTS.md: import, mention, or none."""
    if re.search(r"(?im)^\s*@\.?/?AGENTS\.md\b", text) or text.strip().lower() in ("agents.md", "./agents.md"):
        return "import"
    if re.search(r"(?i)agents\.md", text):
        return "mention"
    return "none"


def _lint_skill(f: Features, path: str, add) -> list[Finding]:
    fm = f.frontmatter
    if fm is None:
        add("AF501", "add a --- block with name and description")
        return []
    name = fm.get("name", "")
    folder = path.replace("\\", "/").rstrip("/").rsplit("/", 2)[-2] if path.count("/") >= 1 else None
    if not name:
        add("AF502", "name is missing")
    elif len(name) > 64 or not SKILL_NAME_RE.match(name):
        add("AF502", f"name '{name[:70]}' must be 1 to 64 lowercase letters, digits or single hyphens")
    elif folder and folder != name:
        add("AF502", f"name '{name}' does not match folder '{folder}'")
    if name and re.search(r"anthropic|claude", name):
        add("AF505", f"name '{name}' contains a reserved word")
    desc = fm.get("description", "")
    if not desc:
        add("AF503", "description is missing")
    elif len(desc) > 1024:
        add("AF503", f"description is {len(desc):,} characters; the limit is 1,024")
    if re.match(r"(?i)\s*(i can|i will|i'll|you can|you should|use me)\b", desc):
        add("AF504", "start with what the skill does, for example 'Extracts tables from PDFs'")
    return []


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of the sets of non-blank, whitespace-normalised lines."""
    norm = lambda t: {re.sub(r"\s+", " ", ln.strip()) for ln in t.splitlines() if ln.strip()}  # noqa: E731
    sa, sb = norm(a), norm(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
