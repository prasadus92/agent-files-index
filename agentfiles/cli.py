"""agentfiles: lint AGENTS.md, CLAUDE.md and SKILL.md files.

Usage:
  agentfiles lint [PATH ...] [--format text|json] [--min-severity info|warning|error] [--strict]
  agentfiles rules

With no PATH, it finds agent files in the current repo: AGENTS.md and CLAUDE.md at any depth,
.claude/CLAUDE.md, and SKILL.md under skills folders. Exit code 1 means an error was found
(or a warning, with --strict).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .rules import RULES, SEVERITY_ORDER, kind_for, lint

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist", "build", "target", "__pycache__", ".next", ".tox"}


def discover(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if kind_for(name):
                found.append(Path(dirpath) / name)
    return sorted(found)


_TREES: dict[Path, list[str]] = {}


def tree_paths(root: Path) -> list[str]:
    """Every file and folder path under root, so a path written relative to a package folder still resolves."""
    if root not in _TREES:
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel = Path(dirpath).relative_to(root).as_posix()
            prefix = "" if rel == "." else rel + "/"
            paths.extend(prefix + n for n in dirnames + filenames)
        _TREES[root] = ["/" + p for p in paths]
    return _TREES[root]


def repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return start


def lint_file(path: Path, root: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    kind = kind_for(path.name)
    folder = path.parent

    def exists(rel: str) -> bool:
        rel = rel.split("?")[0].split("#")[0].rstrip("/")
        if any((base / rel).exists() for base in (root, folder)):
            return True
        suffix = "/" + rel.lstrip("./")
        return any(t.endswith(suffix) for t in tree_paths(root))

    siblings = {}
    if kind == "claude_md":
        for cand in (folder / "AGENTS.md", folder.parent / "AGENTS.md" if folder.name == ".claude" else None):
            if cand and cand.exists():
                siblings["agents.md"] = cand.read_text(encoding="utf-8", errors="replace")
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    return [
        {"file": str(rel), "rule": f.rule, "severity": f.severity, "title": f.title, "message": f.message, "line": f.line}
        for f in lint(text, kind, str(rel), exists=exists, siblings=siblings)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentfiles", description="Lint AGENTS.md, CLAUDE.md and SKILL.md files.")
    ap.add_argument("--version", action="version", version=f"agentfiles {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("lint", help="lint agent files")
    lp.add_argument("paths", nargs="*", help="files or folders (default: current folder)")
    lp.add_argument("--format", choices=["text", "json"], default="text")
    lp.add_argument("--min-severity", choices=list(SEVERITY_ORDER), default="info")
    lp.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    sub.add_parser("rules", help="list rules and their sources")
    args = ap.parse_args(argv)

    if args.cmd == "rules":
        for rid, (sev, title, source) in RULES.items():
            print(f"{rid}  {sev:<7}  {title}\n         {source}")
        return 0

    targets: list[Path] = []
    for p in [Path(x) for x in (args.paths or ["."])]:
        if p.is_dir():
            targets.extend(discover(p))
        elif p.exists():
            targets.append(p)
        else:
            print(f"agentfiles: {p}: no such file", file=sys.stderr)
            return 2
    if not targets:
        print("agentfiles: no AGENTS.md, CLAUDE.md or SKILL.md found", file=sys.stderr)
        return 0

    floor = SEVERITY_ORDER[args.min_severity]
    results = []
    for t in targets:
        t = t.resolve()
        results.extend(r for r in lint_file(t, repo_root(t.parent)) if SEVERITY_ORDER[r["severity"]] >= floor)

    if args.format == "json":
        print(json.dumps({"files": [str(t) for t in targets], "findings": results}, indent=2))
    else:
        for r in results:
            loc = f"{r['file']}:{r['line']}" if r["line"] else r["file"]
            print(f"{loc}: {r['severity']} {r['rule']} {r['title']}: {r['message']}")
        counts = {s: sum(1 for r in results if r["severity"] == s) for s in ("error", "warning", "info")}
        print(f"\n{len(targets)} file(s): {counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info")

    worst = max((SEVERITY_ORDER[r["severity"]] for r in results), default=-1)
    return 1 if worst >= SEVERITY_ORDER["error"] or (args.strict and worst >= SEVERITY_ORDER["warning"]) else 0


if __name__ == "__main__":
    sys.exit(main())
