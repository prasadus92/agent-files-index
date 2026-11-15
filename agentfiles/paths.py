"""Which referenced paths are worth checking, and how a reference maps to repo-relative paths."""
from __future__ import annotations

import posixpath
import re
from collections.abc import Callable

PathExists = Callable[[str], "bool | None"]

PATHLIKE_RE = re.compile(r"^(?:\./)?(?:[\w.\-]+/)+[\w.\-]*$|^[\w.\-]+\.(?:md|ts|tsx|js|jsx|py|go|rs|java|kt|toml|json|ya?ml|sh|rb|cs|cpp|h|swift|sql|lock|cfg|ini|txt)$")
CHECKABLE_PREFIXES = ("src/", "lib/", "app/", "apps/", "packages/", "docs/", "test/", "tests/", "scripts/", "cmd/",
                      "internal/", "pkg/", ".github/", ".claude/", "crates/", "services/", "server/", "client/", "web/")
CHECKABLE_EXT_RE = re.compile(r"\.(?:md|mdx|ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|toml|json|ya?ml|sh|rb|cs|swift|sql|cfg|ini|txt|lock)$")
PLACEHOLDER_PATH_RE = re.compile(r"(?i)\.\.\./|yyyy|mmdd|x{3,}|x\.y\.z|\byour[-_]|example|\bfoo\b|\bbar\b|\bmy[-_]|\.env|\.local\.|\*")
GENERATED_DIRS = {"dist", "build", "out", "target", "node_modules", ".next", "coverage", ".venv", "venv", "tmp", ".cache",
                  "logs", "bin", "obj", "__pycache__", ".turbo", ".output"}
NON_PATH_PREFIXES = ("http", "mailto:", "#", "@", "-", "~", "$")


def looks_like_path(code: str) -> bool:
    return bool(PATHLIKE_RE.match(code)) and "://" not in code and not code.startswith(("/", "~")) and "*" not in code


def checkable(ref: str, explicit_link: bool = False) -> bool:
    """Bare file names in inline code could live anywhere, so inline references need a folder part to be checked."""
    ref = ref.split("?")[0]
    if not ref or ref.startswith(NON_PATH_PREFIXES) or any(c in ref for c in "{<%"):
        return False
    if PLACEHOLDER_PATH_RE.search(ref) or ref.removeprefix("./").split("/")[0] in GENERATED_DIRS:
        return False
    if explicit_link:
        return True
    if "/" not in ref.rstrip("/"):
        return False
    if ref.endswith("/"):
        return ref.startswith(CHECKABLE_PREFIXES)
    return bool(CHECKABLE_EXT_RE.search(ref)) or ref.startswith(("./", "../") + CHECKABLE_PREFIXES)


def normalize_ref(ref: str) -> str:
    ref = ref.split("?")[0].split("#")[0].rstrip("/")
    return ref[2:] if ref.startswith("./") else ref


def candidates(ref: str, file_path: str) -> set[str]:
    """A reference may be relative to the repo root or to the folder of the file that mentions it."""
    clean = normalize_ref(ref)
    folder = posixpath.dirname(file_path)
    out = {posixpath.normpath(posixpath.join(base, clean)) for base in {"", folder}}
    return {p for p in out if not p.startswith("..")}


def missing(references: list[str], explicit_links: set[str], exists: PathExists) -> list[str]:
    return [r for r in references if checkable(r, r in explicit_links) and exists(r) is False]
