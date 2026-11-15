"""Markdown structure: fences, headings, frontmatter and quoted spans."""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s)>\]\"'`]+")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
QUOTED_SPAN_RE = re.compile(r"\"[^\"\n]{0,200}\"|“[^”\n]{0,200}”|`[^`\n]{0,200}`")
YAML_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
BLOCK_SCALAR_MARKERS = (">", "|", ">-", "|-")


@dataclass(frozen=True)
class Line:
    text: str
    role: str
    fence_lang: str | None = None


def classify_lines(lines: Iterable[str]) -> Iterator[Line]:
    """Yield each line with its role: fence_open, fence_close, code (inside a fence, with its language) or text."""
    lang: str | None = None
    marker = ""
    for text in lines:
        m = FENCE_RE.match(text)
        if m and lang is None:
            lang, marker = m.group(2).lower(), m.group(1)[0]
            yield Line(text, "fence_open", lang)
        elif m and m.group(1)[0] == marker:
            yield Line(text, "fence_close", lang)
            lang = None
        elif lang is not None:
            yield Line(text, "code", lang)
        else:
            yield Line(text, "text")


def count_unquoted(rx: re.Pattern, text: str) -> int:
    """Quoted or backticked text is usually an example under discussion, so it does not count."""
    spans = [m.span() for m in QUOTED_SPAN_RE.finditer(text)]
    return sum(1 for m in rx.finditer(text) if not any(a <= m.start() and m.end() <= b for a, b in spans))


@dataclass(frozen=True)
class Frontmatter:
    fields: dict[str, str] | None
    error: str | None
    body: str


def parse_frontmatter(text: str) -> Frontmatter:
    """A small YAML subset: top-level string keys, folded or literal block scalars, and comments."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return Frontmatter(None, None, text)
    fields: dict[str, str] = {}
    key = None
    body = text[m.end():]
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw.startswith((" ", "\t"))
        km = YAML_KEY_RE.match(raw)
        if km and not indented:
            key = km.group(1)
            value = km.group(2).strip()
            fields[key] = "" if value in BLOCK_SCALAR_MARKERS else value.strip("\"'")
        elif key and indented:
            fields[key] = (fields[key] + " " + raw.strip()).strip()
        else:
            return Frontmatter(fields, f"unparsed frontmatter line: {raw[:40]!r}", body)
    return Frontmatter(fields, None, body)
