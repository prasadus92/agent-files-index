"""How a CLAUDE.md relates to the AGENTS.md beside it."""
from __future__ import annotations

import re

IMPORT_LINE_RE = re.compile(r"(?im)^\s*@\.?/?AGENTS\.md\b")
MENTION_RE = re.compile(r"(?i)agents\.md")


def agents_md_link(claude_text: str) -> str:
    """One of: import (an @AGENTS.md line), mention (named in the text), none."""
    if IMPORT_LINE_RE.search(claude_text) or claude_text.strip().lower() in ("agents.md", "./agents.md"):
        return "import"
    return "mention" if MENTION_RE.search(claude_text) else "none"


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of the sets of non-blank, whitespace-normalized lines."""
    sa, sb = _line_set(a), _line_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _line_set(text: str) -> set[str]:
    return {re.sub(r"\s+", " ", ln.strip()) for ln in text.splitlines() if ln.strip()}
