"""Step 6: compute the headline numbers in summary.json from the published tables.

Stratum A is a census, so its shares are exact for that frame. Stratum B is a self-weighting sample; the
`all_100plus` figures weight each B repo by `frame.sample_weight()`. File-level figures are per stratum.
Usage: python -m pipeline.analyze DATA_DIR RAW_DIR
"""
from __future__ import annotations

import json

import pandas as pd

from agentfiles.rules import AGENTS_MAX_BYTES, CLAUDE_MAX_LINES, SKILL_MAX_BODY_LINES

from . import frame, paths_from_argv
from .store import RawStore

STAR_BUCKETS = [(1000, 1999), (2000, 4999), (5000, 9999), (10000, 49999), (50000, None)]
KINDS = ("agents_md", "claude_md", "skill_md")
ADOPTION_FLAGS = ["has_agents_md", "has_claude_any", "has_either", "has_both", "has_skills", "has_claude_dir",
                  "has_mcp_json", "has_copilot", "has_cursor", "has_gemini_md", "has_agent_md", "has_windsurfrules",
                  "has_any_agent_file"]
MIN_LANGUAGE_REPOS = 400
MIN_YEAR_REPOS = 200


def pct(x: float) -> float:
    return round(100 * float(x), 1)


def share(df: pd.DataFrame, col: str, weights: pd.Series | None = None) -> float | None:
    if df.empty:
        return None
    return pct(df[col].mean()) if weights is None else pct((df[col] * weights).sum() / weights.sum())


def with_flags(repos: pd.DataFrame) -> pd.DataFrame:
    r = repos.assign(has_claude_any=repos.has_claude_md | repos.has_dot_claude_claude_md)
    r = r.assign(has_either=r.has_agents_md | r.has_claude_any, has_both=r.has_agents_md & r.has_claude_any,
                 has_skills=r.n_skill_files > 0, has_cursor=r.has_cursorrules | r.has_cursor_rules_dir,
                 has_copilot=r.has_copilot_instructions | r.has_copilot_instructions_dir)
    others = ["has_either", "has_skills", "has_cursor", "has_copilot", "has_gemini_md", "has_agent_md", "has_windsurfrules"]
    return r.assign(has_any_agent_file=r[others].any(axis=1), w=r.stratum.map({"A": 1.0, "B": frame.sample_weight()}))


def adoption(repos: pd.DataFrame) -> dict:
    a = repos[repos.stratum == "A"]
    years = a.assign(year=pd.to_datetime(a.created_at).dt.year)
    return {
        "A": {c: share(a, c) for c in ADOPTION_FLAGS},
        "B": {c: share(repos[repos.stratum == "B"], c) for c in ADOPTION_FLAGS},
        "all_100plus": {c: share(repos, c, repos.w) for c in ADOPTION_FLAGS},
        "by_stars_A": {
            f"{lo}-{hi or 'max'}": {"n": len(s), **{c: share(s, c) for c in ("has_agents_md", "has_claude_any", "has_either", "has_skills")}}
            for lo, hi in STAR_BUCKETS for s in [a[(a.stars >= lo) & (a.stars <= (hi or a.stars.max()))]]
        },
        "by_language_A": {
            lang: {"n": int(n), **{c: share(a[a.language == lang], c) for c in ("has_agents_md", "has_claude_any", "has_either")}}
            for lang, n in a.language.value_counts().items() if n >= MIN_LANGUAGE_REPOS
        },
        "by_created_year_A": {int(y): {"n": len(s), "has_either": share(s, "has_either")}
                              for y, s in years.groupby("year") if len(s) >= MIN_YEAR_REPOS},
    }


def describe(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    out: dict = {"n": len(df)}
    for col in ("lines", "bytes", "est_tokens", "n_headings", "n_commands", "n_never", "n_must"):
        out[col] = {"median": float(df[col].median()), "p90": float(df[col].quantile(0.9)), "max": int(df[col].max())}
    for col in ("mentions_tests", "mentions_ci", "mentions_security"):
        out[col] = pct(df[col].mean())
    out["has_any_command"] = pct((df.n_commands > 0).mean())
    out.update({f"has_{k}_cmd": pct((df[f"n_{k}_cmds"] > 0).mean()) for k in ("test", "lint", "build", "typecheck", "format", "install")})
    out["sections"] = {c[4:]: pct(df[c].mean()) for c in df.columns if c.startswith("sec_")}
    if df.n_commits.notna().any():
        out["single_commit"] = pct((df.n_commits == 1).mean())
        out["commits_median"] = float(df.n_commits.median())
    if df.has_init_line.notna().any():
        init = df.has_init_line.fillna(False).astype(bool)
        out["init_line"] = pct(init.mean())
        out["single_commit_with_init_line"] = pct((df[init].n_commits == 1).mean())
        out["single_commit_without_init_line"] = pct((df[~init].n_commits == 1).mean())
    checked = df[df.n_paths_checked.fillna(0) > 0]
    if not checked.empty:
        out["files_with_checked_paths"] = len(checked)
        out["files_with_missing_path"] = pct((checked.n_paths_missing > 0).mean())
    out["any_lint_warning_or_error"] = pct(((df.lint_errors + df.lint_warnings) > 0).mean())
    out["over_200_lines"] = pct((df.lines > CLAUDE_MAX_LINES).mean())
    out["over_32kib"] = pct((df.bytes > AGENTS_MAX_BYTES).mean())
    return out


def both_files(repos: pd.DataFrame, files: pd.DataFrame) -> dict:
    a = repos[repos.stratum == "A"]
    both = a[a.has_agents_md & a.has_claude_md]
    claude = files[(files.kind == "claude_md") & (files.path.str.lower() == "claude.md") & files.repo.isin(both.repo)]
    copies = claude[~claude.is_symlink]
    return {
        "repos_A": len(both),
        "link_share": {k: pct(v) for k, v in claude.agents_md_link.fillna("unknown").value_counts(normalize=True).items()},
        "near_duplicate": pct(copies.lint_rules.fillna("").str.contains("AF602").mean()) if len(copies) else None,
    }


def skills(files: pd.DataFrame, findings: pd.DataFrame) -> dict:
    s = files[(files.kind == "skill_md") & ~files.is_symlink]
    hits = findings[findings.kind == "skill_md"].drop_duplicates(["repo", "path", "rule"]).groupby("rule").size()
    return {
        "files": len(s), "repos": int(s.repo.nunique()), "repos_A": int(s[s.stratum == "A"].repo.nunique()),
        "has_frontmatter": pct(s.skill_has_frontmatter.mean()), "has_allowed_tools": pct(s.skill_has_allowed_tools.mean()),
        "description_len_median": float(s.skill_description_len.median()),
        "body_over_500_lines": pct((s.skill_body_lines > SKILL_MAX_BODY_LINES).mean()),
        "files_with_rule": {rule: pct(n / len(s)) for rule, n in hits.items()},
    }


def lint_shares(files: pd.DataFrame, findings: pd.DataFrame) -> dict:
    out = {}
    for kind in KINDS:
        n = len(files[(files.kind == kind) & ~files.is_symlink])
        hits = findings[findings.kind == kind].drop_duplicates(["repo", "path", "rule"]).groupby("rule").size()
        out[kind] = {rule: pct(c / n) for rule, c in hits.items()}
    return out


def top_headings(headings: pd.DataFrame, n_files: int) -> dict:
    h = headings[headings.kind.isin(["agents_md", "claude_md"]) & (headings.level <= 3) & (headings.heading != "")]
    counts = h.drop_duplicates(["repo", "path", "heading"]).heading.value_counts().head(40)
    return {k: {"files": int(v), "share": pct(v / n_files)} for k, v in counts.items()}


def main() -> None:
    data, raw = paths_from_argv("DATA_DIR", "RAW_DIR")
    store = RawStore(raw)
    read = lambda name: pd.read_parquet(data / f"{name}.parquet")  # noqa: E731
    repos, files, findings = with_flags(read("repos")), read("files"), read("lint_findings")
    secret_summary, risky = read("secret_like_summary"), read("risky_text_summary")
    real = files[~files.is_symlink]
    agent_files_a = real[real.kind.isin(["agents_md", "claude_md"]) & (real.stratum == "A")]
    summary = {
        "frame": {
            "snapshot": frame.SNAPSHOT.isoformat(),
            "A_repos": int((repos.stratum == "A").sum()),
            "A_reported_by_search": sum(n for _, n in store.load_json("slices_A.json", [])),
            "B_repos": int((repos.stratum == "B").sum()),
            "B_days_sampled": len(frame.sampled_days()), "B_days_total": len(frame.candidate_days()),
            "B_weight": round(frame.sample_weight(), 2),
            "B_population_estimate": int(round((repos.stratum == "B").sum() * frame.sample_weight())),
            "files": len(files), "files_by_kind": files.kind.value_counts().to_dict(),
            "files_by_kind_A": files[files.stratum == "A"].kind.value_counts().to_dict(),
        },
        "adoption": adoption(repos),
        "files_A": {k: describe(real[(real.kind == k) & (real.stratum == "A")]) for k in KINDS},
        "files_B": {k: describe(real[(real.kind == k) & (real.stratum == "B")]) for k in KINDS},
        "both_files": both_files(repos, files),
        "skills": skills(files, findings),
        "lint_rule_share": lint_shares(files, findings),
        "top_headings_A": top_headings(read("headings").merge(files[["repo", "path", "stratum"]], on=["repo", "path"])
                                       .query("stratum == 'A'"), len(agent_files_a)),
        "secret_like": {
            "file_pattern_pairs_raw_regex": int(secret_summary.files_raw_regex.sum()),
            "file_pattern_pairs_after_filters": int(secret_summary.files_after_filters.sum()),
            "after_filters_by_pattern": secret_summary.groupby("pattern").files_after_filters.sum().loc[lambda s: s > 0].to_dict(),
        },
        "risky_text_files": risky.groupby("signal").files.sum().to_dict() if len(risky) else {},
        "pipe_to_shell_files": int((real.n_pipe_to_shell > 0).sum()),
    }
    (data / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(json.dumps({k: summary[k] for k in ("frame", "both_files")}, indent=1, default=float))


if __name__ == "__main__":
    main()
