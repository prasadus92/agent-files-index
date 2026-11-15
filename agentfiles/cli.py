"""agentfiles: lint AGENTS.md, CLAUDE.md and SKILL.md files.

Usage:
  agentfiles lint [PATH ...] [--format text|json] [--min-severity info|warning|error] [--strict]
  agentfiles rules

With no PATH it lints the current folder: AGENTS.md and CLAUDE.md at any depth and SKILL.md files.
Exit code 1 means an error was found (or a warning, with --strict); 2 means a file could not be read.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .discover import LocalRepo, discover, is_link_to_sibling_agents_md, read_text, repo_root
from .rules import RULES, SEVERITY_ORDER, kind_for, lint


def lint_file(path: Path, repo: LocalRepo) -> list[dict]:
    kind = kind_for(path.name)
    if is_link_to_sibling_agents_md(path):
        return []
    rel = repo.relative(path)
    findings = lint(
        read_text(path), kind, rel,
        exists=lambda ref: repo.reference_exists(ref, rel),
        import_exists=lambda imp: repo.import_exists(imp, rel),
        siblings=repo.siblings(path, kind),
    )
    return [{"file": rel, "rule": f.id, "severity": f.severity, "title": f.rule.title, "message": f.message, "line": f.line}
            for f in findings]


def collect_targets(args: list[str]) -> tuple[list[tuple[Path, Path]], list[str], bool]:
    """Each target is paired with the folder to treat as the repo root when there is no .git above it."""
    targets, problems, missing = [], [], False
    for p in (Path(a).absolute() for a in (args or ["."])):
        if p.is_dir():
            targets += [(f, p) for f in discover(p)]
        elif not p.exists() and not p.is_symlink():
            problems.append(f"{p}: no such file")
            missing = True
        elif kind_for(p.name) is None:
            problems.append(f"{p}: not an AGENTS.md, CLAUDE.md or SKILL.md file; skipped")
        else:
            targets.append((p, p.parent))
    return targets, problems, missing


def print_text(results: list[dict], n_files: int) -> None:
    for r in results:
        loc = f"{r['file']}:{r['line']}" if r["line"] else r["file"]
        print(f"{loc}: {r['severity']} {r['rule']} {r['title']}: {r['message']}")
    counts = {s: sum(1 for r in results if r["severity"] == s) for s in ("error", "warning", "info")}
    print(f"\n{n_files} file(s): {counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info")


def exit_code(results: list[dict], strict: bool, input_problem: bool) -> int:
    worst = max((SEVERITY_ORDER[r["severity"]] for r in results), default=-1)
    if worst >= SEVERITY_ORDER["error"] or (strict and worst >= SEVERITY_ORDER["warning"]):
        return 1
    return 2 if input_problem else 0


def run_lint(args: argparse.Namespace) -> int:
    targets, problems, missing = collect_targets(args.paths)
    floor = SEVERITY_ORDER[args.min_severity]
    results, unreadable = [], False
    repos: dict[Path, LocalRepo] = {}
    for path, fallback in targets:
        root = repo_root(path.parent, fallback)
        repo = repos.setdefault(root, LocalRepo(root))
        try:
            found = lint_file(path, repo)
        except OSError as e:
            problems.append(f"{path}: cannot read ({e.strerror or e})")
            unreadable = True
            continue
        results += [r for r in found if SEVERITY_ORDER[r["severity"]] >= floor]
    for msg in problems:
        print(f"agentfiles: {msg}", file=sys.stderr)
    if not targets and not problems:
        print("agentfiles: no AGENTS.md, CLAUDE.md or SKILL.md found", file=sys.stderr)
    if args.format == "json":
        print(json.dumps({"files": [str(t) for t, _ in targets], "findings": results}, indent=2))
    elif targets:
        print_text(results, len(targets))
    return exit_code(results, args.strict, missing or unreadable)


def run_rules() -> int:
    for r in RULES.values():
        print(f"{r.id}  {r.severity:<7}  {r.title}\n         {r.source}")
    return 0


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
    return run_rules() if args.cmd == "rules" else run_lint(args)


if __name__ == "__main__":
    sys.exit(main())
