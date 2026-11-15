"""Lint rules for AGENTS.md, CLAUDE.md and SKILL.md. Every rule names the guidance or data it comes from."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from . import paths
from .features import Features, extract
from .relations import agents_md_link, similarity

ERROR, WARN, INFO = "error", "warning", "info"
SEVERITY_ORDER = {INFO: 0, WARN: 1, ERROR: 2}
AGENTS, CLAUDE, SKILL = "agents_md", "claude_md", "skill_md"
KIND_BY_NAME = {"agents.md": AGENTS, "claude.md": CLAUDE, "skill.md": SKILL}

CLAUDE_MAX_LINES = 200
AGENTS_MAX_BYTES = 32 * 1024
SKILL_MAX_BODY_LINES = 500
SKILL_NAME_MAX = 64
SKILL_DESCRIPTION_MAX = 1024
SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$|^[a-z0-9]$")
FIRST_PERSON_RE = re.compile(r"(?i)\s*(i can|i will|i'll|you can|you should|use me)\b")
RESERVED_SKILL_WORDS_RE = re.compile(r"anthropic|claude")
EMPHASIS_LIMIT = 10
HEADINGLESS_LIMIT = 30
DUPLICATE_THRESHOLD = 0.9
MAX_PATH_FINDINGS = 20


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    title: str
    source: str


@dataclass(frozen=True)
class Finding:
    rule: Rule
    message: str
    line: int | None = None

    @property
    def id(self) -> str:
        return self.rule.id

    @property
    def severity(self) -> str:
        return self.rule.severity


@dataclass
class Context:
    """Everything a check may look at.

    `exists` resolves a referenced path from the repo root or the file's folder; `import_exists` resolves an @import
    from the file's folder only. Both answer True, False or None (unknown).
    """
    text: str
    kind: str
    path: str
    features: Features
    exists: paths.PathExists | None = None
    import_exists: paths.PathExists | None = None
    siblings: dict[str, str] = field(default_factory=dict)

    def line_of(self, needle: str) -> int | None:
        idx = self.text.find(needle)
        return self.text.count("\n", 0, idx) + 1 if idx >= 0 else None


Check = Callable[[Context], Iterator[tuple[str, str] | tuple[str, str, int | None]]]
RULES: dict[str, Rule] = {}
CHECKS: list[Check] = []


def rule(*definitions: tuple[str, str, str, str]) -> Callable[[Check], Check]:
    """Register a check and the rules (id, severity, title, source) it can emit."""
    def register(check: Check) -> Check:
        for rid, severity, title, source in definitions:
            RULES[rid] = Rule(rid, severity, title, source)
        CHECKS.append(check)
        return check
    return register


def kind_for(path: str) -> str | None:
    return KIND_BY_NAME.get(path.replace("\\", "/").rsplit("/", 1)[-1].lower())


def lint(text: str, kind: str, path: str = "", exists: paths.PathExists | None = None,
         import_exists: paths.PathExists | None = None, siblings: dict[str, str] | None = None,
         features: Features | None = None) -> list[Finding]:
    ctx = Context(text, kind, path.replace("\\", "/"), features or extract(text), exists, import_exists, siblings or {})
    return [Finding(RULES[rid], *rest) for check in CHECKS for rid, *rest in check(ctx)]


def _hands_off(f: Features) -> bool:
    """A file that imports or links to another file can leave the commands to that file."""
    return bool(f.imports) or (f.nonblank_lines <= 5 and bool(f.relative_links or "agents.md" in " ".join(f.referenced_paths).lower()))


@rule(("AF101", ERROR, "secret-like string", "GitHub blog, agents.md lessons from 2,500 repos: never commit secrets"))
def secret_strings(ctx: Context):
    for name, n in sorted(ctx.features.secret_hits.items()):
        yield "AF101", f"{n} {name.replace('_', ' ')} match(es); remove and rotate if real"


@rule(("AF102", WARN, "absolute home-directory path", "data: paths like /Users/<name>/ only work on 1 machine"),
      ("AF103", WARN, "prompt-injection-like text", "data: unquoted text telling the agent to ignore instructions or hide actions from the user"),
      ("AF104", INFO, "pipes a downloaded script into a shell", "data: curl | sh runs remote code the agent cannot inspect first"))
def risky_text(ctx: Context):
    f = ctx.features
    if f.home_paths:
        yield "AF102", f"{f.home_paths} absolute home-directory path(s); use repo-relative paths"
    if f.injection_hits:
        yield "AF103", f"{f.injection_hits} phrase(s) tell the agent to ignore instructions or keep something from the user"
    if f.pipe_shell_hits:
        yield "AF104", f"{f.pipe_shell_hits} curl or wget piped into a shell; pin a version or point to the install docs"


@rule(("AF201", WARN, "CLAUDE.md longer than 200 lines", "code.claude.com/docs/en/memory: target under 200 lines per CLAUDE.md"),
      ("AF202", ERROR, "AGENTS.md larger than 32 KiB", "Codex AGENTS.md docs: project_doc_max_bytes defaults to 32 KiB; the rest is dropped"),
      ("AF203", WARN, "SKILL.md body longer than 500 lines", "agentskills.io specification: keep SKILL.md under 500 lines"),
      ("AF204", WARN, "file is empty", "Codex AGENTS.md docs: empty files are skipped"))
def size(ctx: Context):
    f = ctx.features
    if f.nonblank_lines == 0:
        yield "AF204", "the file has no content"
    if ctx.kind == CLAUDE and f.lines > CLAUDE_MAX_LINES:
        yield "AF201", f"{f.lines} lines; move task-specific detail into skills or .claude/rules/"
    if ctx.kind == AGENTS and f.bytes > AGENTS_MAX_BYTES:
        yield "AF202", f"{f.bytes:,} bytes; Codex drops everything after {AGENTS_MAX_BYTES:,}"
    if ctx.kind == SKILL and f.body_lines > SKILL_MAX_BODY_LINES:
        yield "AF203", f"body is {f.body_lines} lines; move reference material into separate files"


@rule(("AF301", WARN, "no test command", "agents.md, Claude Code best practices: list the exact test command"),
      ("AF302", INFO, "no build, lint or typecheck command", "Claude Code best practices: exact build, typecheck and lint commands"),
      ("AF303", WARN, "install commands use more than 1 JS package manager", "data: mixed npm, pnpm, yarn and bun installs give the agent 2 answers"))
def commands_given(ctx: Context):
    f = ctx.features
    if ctx.kind not in (AGENTS, CLAUDE) or f.nonblank_lines < 3:
        return
    if not _hands_off(f):
        kinds = f.command_kinds()
        if not kinds.get("test"):
            yield "AF301", "no test command found in a code block or inline code"
        if not (kinds.get("build") or kinds.get("lint") or kinds.get("typecheck")):
            yield "AF302", "no build, lint or typecheck command found"
    if len(f.install_package_managers) > 1:
        yield "AF303", "install commands use " + ", ".join(sorted(f.install_package_managers))


@rule(("AF304", WARN, "long file without headings", "code.claude.com/docs/en/memory: group instructions under markdown headers"),
      ("AF305", INFO, "vague instruction", "code.claude.com/docs/en/memory: write verifiable instructions"),
      ("AF306", INFO, "heavy use of emphasis words", "Claude Code best practices: IMPORTANT on an ignored rule rarely fixes it"))
def structure(ctx: Context):
    f = ctx.features
    if f.nonblank_lines > HEADINGLESS_LIMIT and not f.headings:
        yield "AF304", f"{f.nonblank_lines} non-blank lines and no markdown headings"
    if f.vague_phrases:
        yield "AF305", f"{f.vague_phrases} vague phrase(s) such as 'follow best practices'; say the exact rule"
    if f.n_emphasis_caps > EMPHASIS_LIMIT:
        yield "AF306", f"{f.n_emphasis_caps} uses of IMPORTANT, MUST, NEVER, ALWAYS or CRITICAL"


@rule(("AF401", WARN, "referenced path does not exist", "data: stale paths send the agent to files that are gone"),
      ("AF402", ERROR, "@import target does not exist", "code.claude.com/docs/en/memory: @path imports resolve from the importing file"),
      ("AF403", INFO, "@import syntax in AGENTS.md", "agents.md: plain Markdown, no import syntax; only Claude Code expands @path"))
def references(ctx: Context):
    f = ctx.features
    if ctx.exists is not None and ctx.kind != SKILL:
        for ref in paths.missing(f.referenced_paths, set(f.relative_links), ctx.exists)[:MAX_PATH_FINDINGS]:
            yield "AF401", f"`{ref}` not found", ctx.line_of(ref)
    if ctx.import_exists is not None and ctx.kind == CLAUDE:
        for imp in f.imports:
            if not imp.startswith("~") and ctx.import_exists(imp) is False:
                yield "AF402", f"@{imp} not found", ctx.line_of("@" + imp)
    if ctx.kind == AGENTS and f.imports:
        yield "AF403", f"{len(f.imports)} @path line(s); other AGENTS.md readers see them as plain text"


@rule(("AF501", ERROR, "SKILL.md has no YAML frontmatter", "agentskills.io specification: name and description are required"),
      ("AF502", ERROR, "invalid skill name", "agentskills.io specification: 1 to 64 lowercase letters, digits, hyphens; matches folder"),
      ("AF503", ERROR, "missing or over-long skill description", "agentskills.io specification: description is required, at most 1,024 characters"),
      ("AF504", WARN, "skill description in first or second person", "Anthropic skill authoring best practices: write the description in third person"),
      ("AF505", WARN, "reserved word in skill name", "Anthropic skill authoring best practices: name must not contain anthropic or claude"))
def skill_frontmatter(ctx: Context):
    if ctx.kind != SKILL:
        return
    fm = ctx.features.frontmatter
    if fm is None:
        yield "AF501", "add a --- block with name and description"
        return
    name, desc = fm.get("name", ""), fm.get("description", "")
    parts = ctx.path.rstrip("/").split("/")
    folder = parts[-2] if len(parts) >= 2 else None
    if not name:
        yield "AF502", "name is missing"
    elif len(name) > SKILL_NAME_MAX or not SKILL_NAME_RE.match(name):
        yield "AF502", f"name '{name[:70]}' must be 1 to 64 lowercase letters, digits or single hyphens"
    elif folder and folder != name:
        yield "AF502", f"name '{name}' does not match folder '{folder}'"
    if name and RESERVED_SKILL_WORDS_RE.search(name):
        yield "AF505", f"name '{name}' contains a reserved word"
    if not desc:
        yield "AF503", "description is missing"
    elif len(desc) > SKILL_DESCRIPTION_MAX:
        yield "AF503", f"description is {len(desc):,} characters; the limit is 1,024"
    if FIRST_PERSON_RE.match(desc):
        yield "AF504", "start with what the skill does, for example 'Extracts tables from PDFs'"


@rule(("AF601", WARN, "CLAUDE.md never mentions AGENTS.md", "code.claude.com/docs/en/memory: Claude reads AGENTS.md only when no CLAUDE.md exists"),
      ("AF602", INFO, "CLAUDE.md duplicates AGENTS.md", "data: copies drift; a symlink or @AGENTS.md keeps 1 source"))
def claude_and_agents(ctx: Context):
    agents_text = ctx.siblings.get("agents.md")
    if ctx.kind != CLAUDE or agents_text is None:
        return
    if agents_md_link(ctx.text) == "none":
        yield "AF601", "AGENTS.md sits next to this file and is never mentioned; add @AGENTS.md or symlink CLAUDE.md to it"
    if similarity(ctx.text, agents_text) >= DUPLICATE_THRESHOLD:
        yield "AF602", "content is at least 90% the same as AGENTS.md"
