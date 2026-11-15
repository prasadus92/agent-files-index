"""Pass 4: turn raw pass 1 to 3 output into the published tables. No file text leaves this step.

Usage: python scripts/build_dataset.py RAW_DIR OUT_DIR
"""
from __future__ import annotations

import json
import posixpath
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentfiles.parse import COMMAND_HEADS, SECTION_CATEGORIES, parse, scan_secrets_raw  # noqa: E402
from agentfiles.rules import agents_md_link, lint, similarity  # noqa: E402

PRIVATE_RULES = {"AF101", "AF103"}  # reported only as aggregates, never per repo
SNAPSHOT = "2026-11-15"


def names(entries, kind=None):
    return {e["name"].lower() for e in (entries or []) if kind is None or e["type"] == kind}


def load_repos(raw: Path) -> dict[str, dict]:
    repos: dict[str, dict] = {}
    for p in sorted(raw.glob("repos_*.jsonl")):
        for line in p.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r["repo"] not in repos:
                repos[r["repo"]] = r
    return repos


def repo_row(r: dict) -> dict:
    root_blobs, root_trees = names(r["root"], "blob"), names(r["root"], "tree")
    dc, gh, cur = names(r["dotclaude"]), names(r["dotgithub"]), names(r["dotcursor"])
    claude_md = next((e for e in (r["root"] or []) if e["name"].lower() == "claude.md"), None)
    return {
        "repo": r["repo"], "repo_id": r["repo_id"], "stratum": r["stratum"], "stars": r["stars"], "forks": r["forks"],
        "language": r["language"], "license": r["license"], "created_at": r["created_at"], "pushed_at": r["pushed_at"],
        "is_template": r["is_template"], "disk_kb": r["disk_kb"], "head_sha": r["head_sha"],
        "has_agents_md": "agents.md" in root_blobs,
        "has_claude_md": "claude.md" in root_blobs,
        "claude_md_is_symlink": bool(claude_md and claude_md["mode"] == 40960),
        "has_dot_claude_claude_md": "claude.md" in dc,
        "has_claude_dir": ".claude" in root_trees,
        "has_claude_settings": "settings.json" in dc,
        "has_claude_commands": "commands" in dc,
        "has_claude_agents": "agents" in dc,
        "has_claude_rules": "rules" in dc,
        "has_claude_skills": "skills" in dc,
        "has_root_skills_dir": "skills" in root_trees,
        "has_agents_skills": "skills" in names(r["dotagents"]),
        "has_mcp_json": ".mcp.json" in root_blobs,
        "has_agent_md": "agent.md" in root_blobs,
        "has_gemini_md": "gemini.md" in root_blobs,
        "has_cursorrules": ".cursorrules" in root_blobs,
        "has_cursor_rules_dir": "rules" in cur,
        "has_windsurfrules": ".windsurfrules" in root_blobs,
        "has_copilot_instructions": "copilot-instructions.md" in gh,
        "has_copilot_instructions_dir": "instructions" in gh,
        "has_github_workflows": "workflows" in gh,
    }


def main() -> None:
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    repos = load_repos(raw)
    path_checks: dict[str, bool] = json.loads((raw / "path_checks.json").read_text()) if (raw / "path_checks.json").exists() else {}
    resolution: dict[str, str] = json.loads((raw / "path_resolution.json").read_text()) if (raw / "path_resolution.json").exists() else {}
    skill_totals = json.loads((raw / "skill_dirs_total.json").read_text()) if (raw / "skill_dirs_total.json").exists() else {}

    files = []
    seen = set()
    for line in (raw / "files.jsonl").open():
        row = json.loads(line)
        key = (row["repo"], row["path"])
        if key in seen or row["repo"] not in repos:
            continue
        seen.add(key)
        files.append(row)
    texts = {(f["repo"], f["path"].lower()): f["text"] or "" for f in files}

    file_rows, heading_rows, command_rows, finding_rows = [], [], [], []
    secret_agg: Counter = Counter()
    private_agg: Counter = Counter()
    files_with_secret: Counter = Counter()
    raw_secret_files: Counter = Counter()
    for row in files:
        text = row["text"] or ""
        repo = repos[row["repo"]]
        f = parse(text)
        folder = posixpath.dirname(row["path"])
        sha = row["head_sha"]

        def exists(p, _repo=row["repo"], _sha=sha, _folder=folder):
            clean = p.split("?")[0].split("#")[0].rstrip("/")
            clean = clean[2:] if clean.startswith("./") else clean
            keys = [f"{_repo}|{_sha}|{posixpath.normpath(posixpath.join(b, clean))}" for b in {"", _folder}]
            if any(path_checks.get(k) is True or resolution.get(k) in ("exact", "suffix") for k in keys):
                return True
            return False if any(resolution.get(k) == "missing" for k in keys) else None

        siblings = {}
        if row["kind"] == "claude_md":
            agents = texts.get((row["repo"], posixpath.join(folder if folder != ".claude" else "", "agents.md").lower()))
            if agents is not None:
                siblings["agents.md"] = agents
        findings = lint(text, row["kind"], row["path"], exists=exists if row["kind"] != "skill_md" else None,
                        siblings=siblings, features=f) if not row["is_symlink"] else []
        public = [x for x in findings if x.rule not in PRIVATE_RULES]
        for name, n in f.secret_hits.items():
            secret_agg[(repo["stratum"], row["kind"], name)] += n
            files_with_secret[(repo["stratum"], row["kind"], name)] += 1
        for name in scan_secrets_raw(text):
            raw_secret_files[(repo["stratum"], row["kind"], name)] += 1
        if f.injection_hits:
            private_agg[(repo["stratum"], row["kind"], "prompt_injection_like")] += 1
        n_checked = sum(1 for p in f.referenced_paths if exists(p) is not None) if row["kind"] != "skill_md" else None
        n_missing = sum(1 for x in findings if x.rule == "AF401")
        kinds = f.command_kinds()
        fm = f.frontmatter or {}
        file_rows.append({
            "repo": row["repo"], "stratum": repo["stratum"], "stars": repo["stars"], "language": repo["language"],
            "license": repo["license"], "kind": row["kind"], "path": row["path"], "commit_sha": sha,
            "blob_sha": row["blob_sha"], "is_symlink": row["is_symlink"], "is_truncated": row["is_truncated"],
            "n_commits": row["n_commits"], "last_commit_at": row["last_commit_at"],
            "bytes": f.bytes, "lines": f.lines, "nonblank_lines": f.nonblank_lines, "words": f.words,
            "est_tokens": f.est_tokens, "n_headings": len(f.headings),
            "n_h1": sum(1 for lvl, _ in f.headings if lvl == 1), "n_h2": sum(1 for lvl, _ in f.headings if lvl == 2),
            "max_heading_depth": max((lvl for lvl, _ in f.headings), default=0),
            "n_code_blocks": f.n_code_blocks, "n_bullets": f.n_bullets, "n_commands": len(f.commands),
            **{f"n_{k}_cmds": kinds.get(k, 0) for k in ("test", "lint", "format", "typecheck", "build", "install", "run")},
            "package_managers": ";".join(sorted(f.package_managers)),
            **{f"sec_{k}": k in f.section_categories for k in SECTION_CATEGORIES},
            "n_must": f.n_must, "n_never": f.n_never, "n_emphasis_caps": f.n_emphasis_caps,
            "mentions_tests": f.mentions_tests, "mentions_ci": f.mentions_ci, "mentions_security": f.mentions_security,
            "n_urls": len(f.urls), "n_relative_links": len(f.relative_links), "n_imports": len(f.imports),
            "n_referenced_paths": len(f.referenced_paths), "n_paths_checked": n_checked, "n_paths_missing": n_missing if row["kind"] != "skill_md" else None,
            "n_vague_phrases": f.vague_phrases, "n_home_paths": f.home_paths, "n_pipe_to_shell": f.pipe_shell_hits,
            "skill_has_frontmatter": f.frontmatter is not None if row["kind"] == "skill_md" else None,
            "skill_name_len": len(fm.get("name", "")) if row["kind"] == "skill_md" else None,
            "skill_description_len": len(fm.get("description", "")) if row["kind"] == "skill_md" else None,
            "skill_has_allowed_tools": "allowed-tools" in fm if row["kind"] == "skill_md" else None,
            "skill_body_lines": f.body_lines if row["kind"] == "skill_md" else None,
            "similarity_to_agents_md": None,
            "agents_md_link": None,
            "lint_errors": sum(1 for x in public if x.severity == "error"),
            "lint_warnings": sum(1 for x in public if x.severity == "warning"),
            "lint_info": sum(1 for x in public if x.severity == "info"),
            "lint_rules": ";".join(sorted({x.rule for x in public})),
        })
        if row["kind"] == "claude_md" and row["is_symlink"]:
            file_rows[-1]["agents_md_link"] = "symlink" if "agents.md" in text.lower() else "symlink_other"
        elif siblings:
            file_rows[-1]["similarity_to_agents_md"] = round(similarity(text, siblings["agents.md"]), 3)
            file_rows[-1]["agents_md_link"] = agents_md_link(text)
        for lvl, h in f.headings:
            heading_rows.append({"repo": row["repo"], "path": row["path"], "kind": row["kind"], "level": lvl,
                                 "heading": h[:80], "categories": ";".join(sorted(_cats(h)))})
        for c in f.commands:
            command_rows.append({"repo": row["repo"], "path": row["path"], "kind": row["kind"], "head": "./*" if c.head.startswith("./") and c.head not in COMMAND_HEADS else c.head,
                                 "command_kinds": ";".join(c.kinds)})
        for x in public:
            finding_rows.append({"repo": row["repo"], "path": row["path"], "kind": row["kind"], "rule": x.rule,
                                 "severity": x.severity})

    skills_by_repo = Counter(r["repo"] for r in file_rows if r["kind"] == "skill_md")
    repo_rows = []
    for r in repos.values():
        rr = repo_row(r)
        rr["n_skill_files"] = skills_by_repo.get(r["repo"], 0)
        rr["n_skill_dirs"] = skill_totals.get(r["repo"], 0)
        repo_rows.append(rr)

    tables = {
        "repos": pd.DataFrame(repo_rows),
        "files": pd.DataFrame(file_rows),
        "headings": pd.DataFrame(heading_rows),
        "commands": pd.DataFrame(command_rows),
        "lint_findings": pd.DataFrame(finding_rows),
        "secret_like_summary": pd.DataFrame(
            [{"stratum": s, "kind": k, "pattern": p, "files_raw_regex": raw_secret_files[(s, k, p)],
              "files_after_filters": files_with_secret.get((s, k, p), 0), "matches_after_filters": secret_agg.get((s, k, p), 0)}
             for (s, k, p) in sorted(raw_secret_files)]),
        "risky_text_summary": pd.DataFrame(
            [{"stratum": s, "kind": k, "signal": p, "files": n} for (s, k, p), n in sorted(private_agg.items())]),
    }
    for name, df in tables.items():
        df.insert(0, "snapshot", SNAPSHOT)
        df.to_csv(out / f"{name}.csv", index=False)
        df.to_parquet(out / f"{name}.parquet", index=False)
        print(f"{name}: {len(df):,} rows")


def _cats(h: str) -> set[str]:
    return {k for k, rx in SECTION_CATEGORIES.items() if rx.search(h)}


if __name__ == "__main__":
    main()
