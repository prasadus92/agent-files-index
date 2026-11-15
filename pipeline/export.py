"""Step 5: build the published tables from the raw store. File text, secret values and rare headings stay out.

Usage: python -m pipeline.export RAW_DIR OUT_DIR
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from agentfiles import commands, secrets
from agentfiles.features import HOME_PATH_RE, Features, extract
from agentfiles.relations import agents_md_link, similarity
from agentfiles.rules import CLAUDE, SKILL, lint
from agentfiles.sections import SECTION_CATEGORIES, classify_heading

from . import frame
from .github import SYMLINK_MODE
from .store import PathEvidence, RawStore

AGGREGATE_ONLY_RULES = {"AF101", "AF102", "AF103"}
MIN_REPOS_PER_HEADING = 5
UNSAFE_HEADING_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://|www\.|\b[\w-]+\.(?:com|io|dev|org|net|ai|app|co|so|sh|me|tech)\b", re.I)
COMMAND_KINDS = ("test", "lint", "format", "typecheck", "build", "install", "run")


def names(entries: list[dict] | None, entry_type: str | None = None) -> set[str]:
    return {e["name"].lower() for e in entries or [] if entry_type is None or e["type"] == entry_type}


def repo_row(r: dict) -> dict:
    root_blobs, root_trees = names(r["root"], "blob"), names(r["root"], "tree")
    dotclaude, dotgithub = names(r["dotclaude"]), names(r["dotgithub"])
    claude_md = next((e for e in r["root"] or [] if e["name"].lower() == "claude.md"), None)
    return {
        **{k: r[k] for k in ("repo", "repo_id", "stratum", "stars", "forks", "language", "license", "created_at",
                             "pushed_at", "is_template", "disk_kb", "head_sha")},
        "has_agents_md": "agents.md" in root_blobs,
        "has_claude_md": "claude.md" in root_blobs,
        "claude_md_is_symlink": bool(claude_md and claude_md["mode"] == SYMLINK_MODE),
        "has_dot_claude_claude_md": "claude.md" in dotclaude,
        "has_claude_dir": ".claude" in root_trees,
        "has_claude_settings": "settings.json" in dotclaude,
        "has_claude_commands": "commands" in dotclaude,
        "has_claude_agents": "agents" in dotclaude,
        "has_claude_rules": "rules" in dotclaude,
        "has_claude_skills": "skills" in dotclaude,
        "has_root_skills_dir": "skills" in root_trees,
        "has_agents_skills": "skills" in names(r["dotagents"]),
        "has_mcp_json": ".mcp.json" in root_blobs,
        "has_agent_md": "agent.md" in root_blobs,
        "has_gemini_md": "gemini.md" in root_blobs,
        "has_cursorrules": ".cursorrules" in root_blobs,
        "has_cursor_rules_dir": "rules" in names(r["dotcursor"]),
        "has_windsurfrules": ".windsurfrules" in root_blobs,
        "has_copilot_instructions": "copilot-instructions.md" in dotgithub,
        "has_copilot_instructions_dir": "instructions" in dotgithub,
        "has_github_workflows": "workflows" in dotgithub,
    }


def skill_fields(kind: str, f: Features) -> dict:
    fm = f.frontmatter or {}
    is_skill = kind == SKILL
    return {
        "skill_has_frontmatter": f.frontmatter is not None if is_skill else None,
        "skill_name_len": len(fm.get("name", "")) if is_skill else None,
        "skill_description_len": len(fm.get("description", "")) if is_skill else None,
        "skill_has_allowed_tools": "allowed-tools" in fm if is_skill else None,
        "skill_body_lines": f.body_lines if is_skill else None,
    }


def sibling_agents_md(row: dict, texts: dict[tuple[str, str], str]) -> str | None:
    folder = row["path"].rsplit("/", 1)[0] if "/" in row["path"] else ""
    base = "" if folder in ("", ".claude") else folder + "/"
    return texts.get((row["repo"], base + "agents.md"))


@dataclass
class Tables:
    files: list[dict] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    secrets_raw: Counter = field(default_factory=Counter)
    secrets_filtered: Counter = field(default_factory=Counter)
    secret_matches: Counter = field(default_factory=Counter)
    risky: Counter = field(default_factory=Counter)

    def add_file(self, row: dict, repo: dict, evidence: PathEvidence, agents_text: str | None) -> None:
        text, kind, stratum = row["text"] or "", row["kind"], repo["stratum"]
        f = extract(text)
        exists = evidence.exists_for(row["repo"], row["head_sha"], row["path"]) if kind != SKILL else None
        siblings = {"agents.md": agents_text} if kind == CLAUDE and agents_text is not None else {}
        found = [] if row["is_symlink"] else lint(text, kind, row["path"], exists=exists, siblings=siblings, features=f)
        public = [x for x in found if x.id not in AGGREGATE_ONLY_RULES]
        self._count_private(f, text, (stratum, kind))
        kinds = f.command_kinds()
        self.files.append({
            "repo": row["repo"], "stratum": stratum, "stars": repo["stars"], "language": repo["language"],
            "license": repo["license"], "kind": kind, "path": row["path"], "commit_sha": row["head_sha"],
            "blob_sha": row["blob_sha"], "is_symlink": row["is_symlink"], "is_truncated": row["is_truncated"],
            "n_commits": row["n_commits"], "last_commit_at": row["last_commit_at"],
            "bytes": f.bytes, "lines": f.lines, "nonblank_lines": f.nonblank_lines, "words": f.words,
            "est_tokens": f.est_tokens, "n_headings": len(f.headings),
            "n_h1": sum(1 for lvl, _ in f.headings if lvl == 1), "n_h2": sum(1 for lvl, _ in f.headings if lvl == 2),
            "max_heading_depth": max((lvl for lvl, _ in f.headings), default=0),
            "n_code_blocks": f.n_code_blocks, "n_bullets": f.n_bullets, "n_commands": len(f.commands),
            **{f"n_{k}_cmds": kinds.get(k, 0) for k in COMMAND_KINDS},
            "package_managers": ";".join(sorted(f.install_package_managers)),
            **{f"sec_{c}": c in f.section_categories for c in SECTION_CATEGORIES},
            "n_must": f.n_must, "n_never": f.n_never, "n_emphasis_caps": f.n_emphasis_caps,
            "mentions_tests": f.mentions_tests, "mentions_ci": f.mentions_ci, "mentions_security": f.mentions_security,
            "n_urls": len(f.urls), "n_relative_links": len(f.relative_links), "n_imports": len(f.imports),
            "n_referenced_paths": len(f.referenced_paths),
            "n_paths_checked": sum(1 for p in f.referenced_paths if exists(p) is not None) if exists else None,
            "n_paths_missing": sum(1 for x in found if x.id == "AF401") if exists else None,
            "n_vague_phrases": f.vague_phrases, "n_pipe_to_shell": f.pipe_shell_hits,
            **skill_fields(kind, f),
            "similarity_to_agents_md": round(similarity(text, agents_text), 3) if siblings and not row["is_symlink"] else None,
            "agents_md_link": self._agents_md_link(row, text, siblings),
            "lint_errors": sum(1 for x in public if x.severity == "error"),
            "lint_warnings": sum(1 for x in public if x.severity == "warning"),
            "lint_info": sum(1 for x in public if x.severity == "info"),
            "lint_rules": ";".join(sorted({x.id for x in public})),
        })
        ident = {"repo": row["repo"], "path": row["path"], "kind": kind}
        self.headings += [{**ident, "level": lvl, "heading": h, "categories": ";".join(sorted(classify_heading(h)))}
                          for lvl, h in f.headings]
        self.commands += [{**ident, "head": _public_head(c.head), "command_kinds": ";".join(c.kinds)} for c in f.commands]
        self.findings += [{**ident, "rule": x.id, "severity": x.severity} for x in public]

    @staticmethod
    def _agents_md_link(row: dict, text: str, siblings: dict) -> str | None:
        if row["kind"] != CLAUDE:
            return None
        if row["is_symlink"]:
            return "symlink" if "agents.md" in text.lower() else "symlink_other"
        return agents_md_link(text) if siblings else None

    def _count_private(self, f: Features, text: str, key: tuple[str, str]) -> None:
        for name in secrets.scan_raw(text):
            self.secrets_raw[(*key, name)] += 1
        for name, n in f.secret_hits.items():
            self.secrets_filtered[(*key, name)] += 1
            self.secret_matches[(*key, name)] += n
        if f.injection_hits:
            self.risky[(*key, "prompt_injection_like")] += 1
        if f.home_paths:
            self.risky[(*key, "home_directory_path")] += 1


def _public_head(head: str) -> str:
    """Local script names can carry repo-specific text, so only known tools keep their name."""
    return "./*" if head.startswith("./") and head not in commands.COMMAND_HEADS else head


def publishable_headings(headings: pd.DataFrame) -> pd.DataFrame:
    """Keep heading text only when at least 5 repos share it and it holds no address, URL or home path."""
    repos_per_heading = headings.groupby("heading").repo.nunique()
    common = headings.heading.map(repos_per_heading) >= MIN_REPOS_PER_HEADING
    unsafe = headings.heading.str.contains(UNSAFE_HEADING_RE) | headings.heading.str.contains(HOME_PATH_RE.pattern, case=False)
    return headings.assign(heading=headings.heading.where(common & ~unsafe, ""))


def private_summaries(t: Tables) -> dict[str, pd.DataFrame]:
    return {
        "secret_like_summary": pd.DataFrame(
            [{"stratum": s, "kind": k, "pattern": p, "files_raw_regex": n,
              "files_after_filters": t.secrets_filtered.get((s, k, p), 0),
              "matches_after_filters": t.secret_matches.get((s, k, p), 0)}
             for (s, k, p), n in sorted(t.secrets_raw.items())]),
        "risky_text_summary": pd.DataFrame(
            [{"stratum": s, "kind": k, "signal": p, "files": n} for (s, k, p), n in sorted(t.risky.items())]),
    }


def write(out: Path, name: str, df: pd.DataFrame) -> None:
    df.insert(0, "snapshot", frame.SNAPSHOT.isoformat())
    df.to_csv(out / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    df.to_parquet(out / f"{name}.parquet", index=False)
    print(f"{name}: {len(df):,} rows")


def main() -> None:
    store, out = RawStore(Path(sys.argv[1])), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    repos = store.repos()
    evidence = PathEvidence(store)
    files = [row for row in store.files() if row["repo"] in repos]
    texts = {(r["repo"], r["path"].lower()): r["text"] or "" for r in files}
    tables = Tables()
    for row in files:
        tables.add_file(row, repos[row["repo"]], evidence, sibling_agents_md(row, texts))

    skill_files = Counter(r["repo"] for r in tables.files if r["kind"] == SKILL)
    skill_dirs = store.load_json("skill_dirs_total.json", {})
    repo_rows = [{**repo_row(r), "n_skill_files": skill_files.get(r["repo"], 0), "n_skill_dirs": skill_dirs.get(r["repo"], 0)}
                 for r in repos.values()]
    published = {
        "repos": pd.DataFrame(repo_rows),
        "files": pd.DataFrame(tables.files),
        "headings": publishable_headings(pd.DataFrame(tables.headings)),
        "commands": pd.DataFrame(tables.commands),
        "lint_findings": pd.DataFrame(tables.findings),
        **private_summaries(tables),
    }
    for name, df in published.items():
        write(out, name, df)


if __name__ == "__main__":
    main()
