"""Turn the text of one agent file into structural features."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import commands, paths, secrets
from .markdown import (BULLET_RE, HEADING_RE, INLINE_CODE_RE, MD_LINK_RE, URL_RE, classify_lines, count_unquoted,
                       lines_outside_fences, parse_frontmatter)
from .sections import classify_heading, normalize_heading

IMPORT_EXTENSIONS = r"md|mdx|txt|json|ya?ml|toml"
IMPORT_RE = re.compile(rf"(?:^|\s)@((?:\.{{0,2}}/|~/)?[\w.\-/]+\.(?:{IMPORT_EXTENSIONS}))\b")
LINK_SCHEME_RE = re.compile(r"^(?:[a-z]+:|#|/)")
MUST_RE = re.compile(r"\b(must|always|required|mandatory|shall)\b", re.I)
NEVER_RE = re.compile(r"\b(never|do not|don't|must not|mustn't|should not|shouldn't|avoid|forbidden|prohibited)\b", re.I)
EMPHASIS_RE = re.compile(r"\b(IMPORTANT|CRITICAL|MUST|NEVER|ALWAYS|YOU MUST)\b")
TESTS_MENTION_RE = re.compile(r"\b(tests?|testing|unit test|integration test|test suite|coverage)\b", re.I)
CI_MENTION_RE = re.compile(r"\b(CI|CI/CD|github actions|\.github/workflows|continuous integration|pipeline|pre-commit)\b")
SECURITY_MENTION_RE = re.compile(r"\b(security|secrets?|credentials?|api keys?|tokens?|\.env|vulnerab\w*|sanitiz\w*|injection)\b", re.I)
VAGUE_RE = re.compile(
    r"\b(write (?:clean|good|high[- ]quality|readable|maintainable) code|follow best practices|use best practices|"
    r"be careful|make sure (?:everything|it) works|keep (?:the )?code clean|use common sense)\b", re.I)
HOME_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+/|/home/(?!user/|username/|runner/|<)[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+")
INJECTION_RE = re.compile(
    r"(?i)\b(?:ignore|disregard|forget) (?:all |any )?(?:of )?(?:the |your )?(?:previous|prior|above|earlier) instructions\b|"
    r"\bhide (?:this|it|these) from the user\b|"
    r"\b(?:do not|don't|never) (?:reveal|disclose|mention) (?:this|these instructions|this file|that you) to the user\b")
PIPE_SHELL_RE = re.compile(r"(?i)\b(?:curl|wget)\b[^\n|`]*https?://[^\n|`]*\|\s*(?:sudo\s+)?(?:ba|z)?sh(?:\s+-s\b|\s*(?:$|[`'\";)]))", re.M)
TRAILING_PUNCT = ".,:;"


@dataclass
class Features:
    bytes: int = 0
    lines: int = 0
    nonblank_lines: int = 0
    words: int = 0
    est_tokens: int = 0
    headings: list[tuple[int, str]] = field(default_factory=list)
    section_categories: set[str] = field(default_factory=set)
    n_code_blocks: int = 0
    n_bullets: int = 0
    commands: list[commands.Command] = field(default_factory=list)
    n_must: int = 0
    n_never: int = 0
    n_emphasis_caps: int = 0
    mentions_tests: bool = False
    mentions_ci: bool = False
    mentions_security: bool = False
    urls: list[str] = field(default_factory=list)
    relative_links: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    inline_paths: list[str] = field(default_factory=list)
    referenced_paths: list[str] = field(default_factory=list)
    vague_phrases: int = 0
    home_paths: int = 0
    secret_hits: dict[str, int] = field(default_factory=dict)
    injection_hits: int = 0
    pipe_shell_hits: int = 0
    frontmatter: dict[str, str] | None = None
    frontmatter_error: str | None = None
    body_lines: int = 0

    def command_kinds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.commands:
            for k in c.kinds:
                out[k] = out.get(k, 0) + 1
        return out

    @property
    def install_package_managers(self) -> set[str]:
        """JS package managers used for project installs; global installs such as `npm i -g pnpm` do not count."""
        return {c.head for c in self.commands
                if c.head in commands.JS_PACKAGE_MANAGERS and "install" in c.kinds and not re.search(r"\s(-g|--global)\b", c.text)}


def extract(text: str) -> Features:
    text = text.removeprefix("﻿")
    lines = text.splitlines()
    front = parse_frontmatter(text)
    f = Features(
        bytes=len(text.encode("utf-8")),
        lines=len(lines),
        nonblank_lines=sum(1 for ln in lines if ln.strip()),
        words=len(re.findall(r"\S+", text)),
        est_tokens=round(len(text) / 4),
        frontmatter=front.fields,
        frontmatter_error=front.error,
        body_lines=len(front.body.splitlines()),
    )
    _scan_lines(f, lines)
    _scan_text(f, text, "\n".join(lines_outside_fences(lines)))
    return f


def _scan_lines(f: Features, lines: list[str]) -> None:
    seen: set[str] = set()

    def add_command(raw: str) -> None:
        cmd = commands.parse_command(raw)
        if cmd and cmd.text not in seen:
            seen.add(cmd.text)
            f.commands.append(cmd)

    for line in classify_lines(lines):
        if line.role == "fence_open":
            f.n_code_blocks += 1
        elif line.role == "code" and line.fence_lang in commands.SHELL_LANGS:
            add_command(line.text)
        if line.role != "text":
            continue
        if hm := HEADING_RE.match(line.text):
            if normalized := normalize_heading(hm.group(2)):
                f.headings.append((len(hm.group(1)), normalized))
                f.section_categories |= classify_heading(normalized)
            continue
        f.n_bullets += bool(BULLET_RE.match(line.text))
        for code in INLINE_CODE_RE.findall(line.text):
            add_command(code)
            candidate = code.strip().rstrip(TRAILING_PUNCT)
            if paths.looks_like_path(candidate):
                f.inline_paths.append(candidate.removeprefix("./"))
        f.relative_links += [link.split("#")[0] for link in MD_LINK_RE.findall(line.text) if not LINK_SCHEME_RE.match(link)]
        f.imports += [imp for imp in IMPORT_RE.findall(line.text) if not re.search(r"[\w.]@" + re.escape(imp), line.text)]

    f.relative_links = sorted({p for p in f.relative_links if p})
    f.inline_paths = sorted(set(f.inline_paths))
    f.referenced_paths = sorted(set(f.inline_paths) | set(f.relative_links))


def _scan_text(f: Features, text: str, outside_code: str) -> None:
    f.n_must = len(MUST_RE.findall(text))
    f.n_never = len(NEVER_RE.findall(text))
    f.n_emphasis_caps = len(EMPHASIS_RE.findall(text))
    f.mentions_tests = bool(TESTS_MENTION_RE.search(text))
    f.mentions_ci = bool(CI_MENTION_RE.search(text))
    f.mentions_security = bool(SECURITY_MENTION_RE.search(text))
    f.urls = URL_RE.findall(text)
    f.vague_phrases = len(VAGUE_RE.findall(text))
    f.home_paths = len(HOME_PATH_RE.findall(text))
    f.injection_hits = count_unquoted(INJECTION_RE, outside_code)
    f.pipe_shell_hits = len(PIPE_SHELL_RE.findall(text))
    f.secret_hits = secrets.scan(text)
