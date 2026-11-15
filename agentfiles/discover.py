"""Find agent files on disk and answer path questions about a local repo."""
from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path

from . import paths
from .rules import CLAUDE, kind_for

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist", "build", "target", "__pycache__", ".next", ".tox"}


def discover(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found += [Path(dirpath) / name for name in filenames if kind_for(name)]
    return sorted(found)


def repo_root(start: Path, fallback: Path) -> Path:
    """The nearest folder with a .git entry, else the folder the user asked to lint."""
    return next((p for p in [start, *start.parents] if (p / ".git").exists()), fallback)


class LocalRepo:
    def __init__(self, root: Path):
        self.root = root

    @cached_property
    def tree(self) -> list[str]:
        """Every file and folder path, so a path written relative to a package folder still resolves."""
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel = Path(dirpath).relative_to(self.root).as_posix()
            prefix = "" if rel == "." else rel + "/"
            out += ["/" + prefix + name for name in dirnames + filenames]
        return out

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else path.as_posix()

    def reference_exists(self, ref: str, file_path: str) -> bool:
        if any((self.root / c).exists() for c in paths.candidates(ref, file_path)):
            return True
        suffix = "/" + paths.normalize_ref(ref)
        return any(t.endswith(suffix) for t in self.tree)

    def import_exists(self, imp: str, file_path: str) -> bool:
        return (self.root / Path(file_path).parent / imp).exists()

    def siblings(self, path: Path, kind: str) -> dict[str, str]:
        agents = agents_md_beside(path)
        return {"agents.md": read_text(agents)} if kind == CLAUDE and agents.is_file() else {}


def agents_md_beside(path: Path) -> Path:
    """The AGENTS.md a CLAUDE.md pairs with; for .claude/CLAUDE.md that is the one in the repo folder above."""
    folder = path.parent.parent if path.parent.name == ".claude" else path.parent
    return folder.resolve() / "AGENTS.md"


def read_text(path: Path) -> str:
    """Decode from bytes so CRLF line endings survive and byte counts match the file on disk."""
    return path.read_bytes().decode("utf-8-sig", errors="replace")


def is_link_to_sibling_agents_md(path: Path) -> bool:
    if not path.is_symlink() or kind_for(path.name) != CLAUDE:
        return False
    target = path.resolve()
    return target.is_file() and target == agents_md_beside(path)
