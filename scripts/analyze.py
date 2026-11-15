"""Compute headline numbers from the published tables. Writes DATA_DIR/summary.json.

Stratum A is a census, so its shares are exact for that frame. Stratum B is a self-weighting sample;
"all_100plus" combines them with weight 1 for A and 1/sampling-fraction for B.
Usage: python scripts/analyze.py DATA_DIR RAW_DIR
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

STAR_BUCKETS = [(1000, 1999), (2000, 4999), (5000, 9999), (10000, 49999), (50000, 10**9)]


def pct(x: float) -> float:
    return round(100 * float(x), 1)


def share(df: pd.DataFrame, col: str, weights: pd.Series | None = None) -> float:
    if len(df) == 0:
        return float("nan")
    if weights is None:
        return pct(df[col].mean())
    return pct((df[col] * weights).sum() / weights.sum())


def main() -> None:
    data, raw = Path(sys.argv[1]), Path(sys.argv[2])
    repos = pd.read_parquet(data / "repos.parquet")
    files = pd.read_parquet(data / "files.parquet")
    heads = pd.read_parquet(data / "headings.parquet")
    finds = pd.read_parquet(data / "lint_findings.parquet")
    secrets = pd.read_csv(data / "secret_like_summary.csv")
    risky = pd.read_csv(data / "risky_text_summary.csv")
    meta_b = json.loads((raw / "enumerate_meta_B.json").read_text()) if (raw / "enumerate_meta_B.json").exists() else {}
    slices_b = json.loads((raw / "slices_B.json").read_text()) if (raw / "slices_B.json").exists() else []

    repos["has_claude_any"] = repos.has_claude_md | repos.has_dot_claude_claude_md
    repos["has_either"] = repos.has_agents_md | repos.has_claude_any
    repos["has_both"] = repos.has_agents_md & repos.has_claude_any
    repos["has_skills"] = repos.n_skill_files > 0
    repos["has_cursor"] = repos.has_cursorrules | repos.has_cursor_rules_dir
    repos["has_copilot"] = repos.has_copilot_instructions | repos.has_copilot_instructions_dir
    repos["has_any_agent_file"] = repos[["has_either", "has_skills", "has_cursor", "has_copilot", "has_gemini_md",
                                         "has_agent_md", "has_windsurfrules"]].any(axis=1)
    flags = ["has_agents_md", "has_claude_any", "has_either", "has_both", "has_skills", "has_claude_dir", "has_mcp_json",
             "has_copilot", "has_cursor", "has_gemini_md", "has_agent_md", "has_windsurfrules", "has_any_agent_file"]

    total_days = 0
    if slices_b:
        import datetime as dt
        total_days = (dt.date.fromisoformat(meta_b.get("started_at", "2026-11-15")[:10]) - dt.date(2008, 1, 1)).days + 1
    b_weight = total_days / len(slices_b) if slices_b else 20.0
    repos["w"] = repos.stratum.map({"A": 1.0, "B": b_weight})

    out: dict = {"frame": {
        "A_repos": int((repos.stratum == "A").sum()), "B_repos": int((repos.stratum == "B").sum()),
        "B_days_sampled": len(slices_b), "B_total_days": total_days, "B_weight": round(b_weight, 2),
        "B_population_estimate": int(round((repos.stratum == "B").sum() * b_weight)),
        "files": len(files), "files_by_kind": files.kind.value_counts().to_dict(),
    }}

    out["adoption"] = {
        "A": {c: share(repos[repos.stratum == "A"], c) for c in flags},
        "B": {c: share(repos[repos.stratum == "B"], c) for c in flags},
        "all_100plus": {c: share(repos, c, repos.w) for c in flags},
    }
    a = repos[repos.stratum == "A"]
    out["adoption_by_stars_A"] = {
        f"{lo}-{hi if hi < 10**9 else 'max'}": {"n": int(len(s)), **{c: share(s, c) for c in ("has_agents_md", "has_claude_any", "has_either", "has_skills")}}
        for lo, hi in STAR_BUCKETS for s in [a[(a.stars >= lo) & (a.stars <= hi)]]
    }
    langs = a.language.value_counts()
    out["adoption_by_language_A"] = {
        lang: {"n": int(n), **{c: share(a[a.language == lang], c) for c in ("has_agents_md", "has_claude_any", "has_either")}}
        for lang, n in langs.items() if n >= 400
    }
    a = a.assign(created_year=pd.to_datetime(a.created_at).dt.year)
    out["adoption_by_created_year_A"] = {
        int(y): {"n": int(len(s)), "has_either": share(s, "has_either")}
        for y, s in a.groupby("created_year") if len(s) >= 200
    }

    def describe(df: pd.DataFrame) -> dict:
        if not len(df):
            return {}
        d = {"n": int(len(df))}
        for col in ("lines", "bytes", "est_tokens", "n_headings", "n_commands", "n_never", "n_must"):
            d[col] = {"median": float(df[col].median()), "p90": float(df[col].quantile(0.9)), "max": int(df[col].max())}
        for col in ("mentions_tests", "mentions_ci", "mentions_security"):
            d[col] = pct(df[col].mean())
        d["has_any_command"] = pct((df.n_commands > 0).mean())
        for k in ("test", "lint", "build", "typecheck", "format", "install"):
            d[f"has_{k}_cmd"] = pct((df[f"n_{k}_cmds"] > 0).mean())
        d["sections"] = {c[4:]: pct(df[c].mean()) for c in df.columns if c.startswith("sec_")}
        d["single_commit"] = pct((df.n_commits == 1).mean()) if df.n_commits.notna().any() else None
        d["commits_median"] = float(df.n_commits.median()) if df.n_commits.notna().any() else None
        checked = df[df.n_paths_checked > 0]
        d["files_with_checked_paths"] = int(len(checked))
        d["files_with_missing_path"] = pct((checked.n_paths_missing > 0).mean()) if len(checked) else None
        d["any_lint_warning_or_error"] = pct(((df.lint_errors + df.lint_warnings) > 0).mean())
        return d

    real = files[~files.is_symlink]
    out["files"] = {kind: describe(real[real.kind == kind]) for kind in ("agents_md", "claude_md", "skill_md")}
    out["files_A"] = {kind: describe(real[(real.kind == kind) & (real.stratum == "A")]) for kind in ("agents_md", "claude_md")}
    out["files_B"] = {kind: describe(real[(real.kind == kind) & (real.stratum == "B")]) for kind in ("agents_md", "claude_md")}
    claude = real[real.kind == "claude_md"]
    agents = real[real.kind == "agents_md"]
    out["thresholds"] = {
        "claude_md_over_200_lines": pct((claude.lines > 200).mean()),
        "agents_md_over_32kib": pct((agents.bytes > 32 * 1024).mean()),
        "agents_md_over_200_lines": pct((agents.lines > 200).mean()),
    }

    # Repos with both files: how CLAUDE.md relates to AGENTS.md.
    both = repos[repos.has_agents_md & repos.has_claude_md]
    root_claude = files[(files.kind == "claude_md") & (files.path.str.lower() == "claude.md") & files.repo.isin(both.repo)]
    link = root_claude.agents_md_link.fillna("unknown")
    nonsym = root_claude[~root_claude.is_symlink]
    out["both_files"] = {
        "repos": int(len(both)),
        "claude_md_files": int(len(root_claude)),
        "link_share": {k: pct(v) for k, v in link.value_counts(normalize=True).items()},
        "near_duplicate": pct(nonsym.lint_rules.fillna("").str.contains("AF602").mean()) if len(nonsym) else None,
        "similarity_median_non_symlink": float(nonsym.similarity_to_agents_md.median()) if len(nonsym) else None,
    }

    skills = real[real.kind == "skill_md"]
    sk_rules = finds[finds.kind == "skill_md"].groupby("rule").path.count()
    out["skills"] = {
        "files": int(len(skills)), "repos": int(skills.repo.nunique()),
        "repos_A": int(skills[skills.stratum == "A"].repo.nunique()),
        "has_frontmatter": pct(skills.skill_has_frontmatter.mean()) if len(skills) else None,
        "has_allowed_tools": pct(skills.skill_has_allowed_tools.mean()) if len(skills) else None,
        "description_len_median": float(skills.skill_description_len.median()) if len(skills) else None,
        "body_over_500_lines": pct((skills.skill_body_lines > 500).mean()) if len(skills) else None,
        "files_with_rule": {r: pct(finds[(finds.kind == "skill_md") & (finds.rule == r)].drop_duplicates(["repo", "path"]).shape[0] / max(1, len(skills)))
                            for r in sk_rules.index},
    }

    out["lint_rule_share"] = {
        kind: {r: pct(g.drop_duplicates(["repo", "path"]).shape[0] / max(1, len(real[real.kind == kind])))
               for r, g in finds[finds.kind == kind].groupby("rule")}
        for kind in ("agents_md", "claude_md", "skill_md")
    }

    h = heads[heads.kind.isin(["agents_md", "claude_md"]) & (heads.level <= 3)].drop_duplicates(["repo", "path", "heading"])
    n_files = len(real[real.kind.isin(["agents_md", "claude_md"])])
    top = h.heading.value_counts().head(40)
    out["top_headings"] = {k: {"files": int(v), "share": pct(v / max(1, n_files))} for k, v in top.items()}

    out["secret_like"] = {
        "files_raw_regex_by_pattern": secrets.groupby("pattern").files_raw_regex.sum().to_dict() if len(secrets) else {},
        "files_after_filters_by_pattern": secrets.groupby("pattern").files_after_filters.sum().to_dict() if len(secrets) else {},
        "files_raw_regex_total": int(secrets.files_raw_regex.sum()) if len(secrets) else 0,
        "files_after_filters_total": int(secrets.files_after_filters.sum()) if len(secrets) else 0,
    }
    out["risky_text"] = risky.groupby("signal").files.sum().to_dict() if len(risky) else {}
    out["home_paths_files"] = int((real.n_home_paths > 0).sum())
    out["pipe_to_shell_files"] = int((real.n_pipe_to_shell > 0).sum())

    (data / "summary.json").write_text(json.dumps(out, indent=2, default=float))
    print(json.dumps({k: out[k] for k in ("frame", "adoption", "thresholds", "both_files", "skills")}, indent=1, default=float))


if __name__ == "__main__":
    main()
