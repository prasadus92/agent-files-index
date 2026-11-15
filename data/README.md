---
license: cc-by-4.0
language:
  - en
pretty_name: Agent Files Index
size_categories:
  - 10K<n<100K
tags:
  - agents-md
  - claude-md
  - skill-md
  - coding-agents
  - software-engineering
  - github
configs:
  - config_name: files
    default: true
    data_files: files.parquet
  - config_name: repos
    data_files: repos.parquet
  - config_name: headings
    data_files: headings.parquet
  - config_name: commands
    data_files: commands.parquet
  - config_name: lint_findings
    data_files: lint_findings.parquet
---

# Agent Files Index: data card

Structural features of agent instruction files (`AGENTS.md`, `CLAUDE.md`, `SKILL.md`) in public GitHub repos, with the presence of other agent config files (Copilot instructions, Cursor rules, `GEMINI.md`, `.mcp.json`). Snapshot taken 15 November 2026.

## Summary

| | |
| --- | --- |
| Repos in the frame | 38,272 with 1,000+ stars (census); 7,912 with 100 to 999 stars (sample) |
| Agent files | 7,502 `AGENTS.md`, 5,252 `CLAUDE.md`, 29,352 `SKILL.md` |
| Headings | 474,517 |
| Repos with a root `AGENTS.md` or `CLAUDE.md` | 21.3% of the census, 15.2% of the sample |
| Snapshot | 2026-11-15 |

## Who made it and why

Prasad Subrahmanya ([prasad.tech](https://prasad.tech)) built it to answer practical questions about these files with counts instead of opinions: how long they are, what sections they have, whether they tell the agent how to run the tests, and how often they point at files that no longer exist. The same parser powers the `agentfiles` checker in this repo.

## Sampling frame

- **Stratum A, census:** every public, non-fork, non-archived repo with 1,000 or more stars and a push on or after 15 November 2025.
- **Stratum B, sample:** the same filters with 100 to 999 stars, limited to repos created on a 5% random sample of calendar days since 1 January 2008 (seed `20261115`). Each repo in B had the same chance of selection, so B is self-weighting. To estimate the whole 100 to 999 star population, weight each B row by `B_weight` in `summary.json`.

Full method, including why GitHub code search was not used: [`../docs/method.md`](../docs/method.md).

## Files

| File | Rows | Description |
| --- | --- | --- |
| `repos` | one per repo in the frame | Stars, language, license, dates, head commit, and a flag per agent file location |
| `files` | one per agent file | Size, structure, commands, rule words, references, maintenance and lint counts |
| `headings` | one per heading | Normalised heading text (up to 80 characters), level and section categories |
| `commands` | one per command | First word of the command (`pnpm`, `pytest`) and its kind; the full command line is not published |
| `lint_findings` | one per rule hit | Rule id and severity per file; secret and injection rules are excluded |
| `secret_like_summary` | one per pattern, stratum and kind | Counts only, no repo names |
| `risky_text_summary` | one per signal, stratum and kind | Counts only, no repo names |
| `summary.json` | | The headline numbers in the README and the post |

Each table comes as CSV and Parquet with the same columns. Every table has a `snapshot` column.

### Key columns in `files`

| Column | Meaning |
| --- | --- |
| `repo`, `path`, `commit_sha`, `blob_sha` | Provenance: fetch `https://github.com/<repo>/blob/<commit_sha>/<path>` for the original |
| `stratum` | `A` (1,000+ stars, census) or `B` (100 to 999 stars, sample) |
| `kind` | `agents_md`, `claude_md` or `skill_md` |
| `is_symlink` | The file is a symlink; its features describe the link, not the target |
| `bytes`, `lines`, `nonblank_lines`, `words`, `est_tokens` | Size; `est_tokens` is characters divided by 4 |
| `n_headings`, `n_h1`, `n_h2`, `max_heading_depth` | Heading structure |
| `sec_<category>` | True if any heading falls in that category (17 keyword categories, see `agentfiles/parse.py`) |
| `n_commands`, `n_<kind>_cmds` | Commands found in shell code blocks and inline code, by kind: test, lint, format, typecheck, build, install, run |
| `package_managers` | JS package managers used in commands (`npm;pnpm`) |
| `n_must`, `n_never`, `n_emphasis_caps` | Must-style words, never-style words, all-caps emphasis words |
| `mentions_tests`, `mentions_ci`, `mentions_security` | The text mentions these anywhere |
| `n_urls`, `n_relative_links`, `n_imports`, `n_referenced_paths` | References out of the file |
| `n_paths_checked`, `n_paths_missing` | Referenced paths that could be checked, and those found nowhere in the repo tree at `commit_sha` |
| `n_commits`, `last_commit_at` | Commits that touched the file, and the date of the last one |
| `skill_*` | Skill frontmatter: present, `name` and `description` lengths, `allowed-tools` present, body length |
| `similarity_to_agents_md` | For a `CLAUDE.md` next to an `AGENTS.md`: Jaccard similarity of their non-blank lines |
| `lint_errors`, `lint_warnings`, `lint_info`, `lint_rules` | `agentfiles` results, excluding AF101 (secrets) and AF103 (injection-like text) |

### Key columns in `repos`

`has_agents_md`, `has_claude_md`, `has_dot_claude_claude_md`, `claude_md_is_symlink`, `has_claude_dir`, `has_claude_settings`, `has_claude_commands`, `has_claude_agents`, `has_claude_rules`, `has_claude_skills`, `has_root_skills_dir`, `has_agents_skills`, `has_mcp_json`, `has_agent_md`, `has_gemini_md`, `has_cursorrules`, `has_cursor_rules_dir`, `has_windsurfrules`, `has_copilot_instructions`, `has_copilot_instructions_dir`, `has_github_workflows`, `n_skill_files`, `n_skill_dirs`. File names are matched in any letter case.

## What is not in the data

- **File text.** Only derived features, short normalised headings and command tool names are published. The originals stay in their repos under their own licenses.
- **Secret values.** Secret-like strings are counted by pattern in a table with no repo names. Matched values are never stored, even on the machine that ran the crawl.
- **Nested files.** Version 1 reads root files, `.claude/CLAUDE.md` and one level of skills folders. Monorepo subfolder files are not included, so adoption is a lower bound.

## Known biases and limits

- Stars measure attention. The frame over-represents AI tooling repos.
- The census ran over about an hour; star counts and pushes moved during it.
- Section categories and command kinds come from keyword rules and miss unusual wording.
- A path found nowhere in the tree may still be fine: a build output, a submodule, or a file the agent is meant to create. Placeholders and common build folders are excluded before counting.
- Secret-like matches are an upper bound: placeholders, local dev credentials and low-entropy values are filtered, and what is left can still be a revoked key or a test fixture.

## License and citation

Copyright Prasad Subrahmanya (https://prasad.tech). Licensed CC BY 4.0. Cite with [`../CITATION.cff`](../CITATION.cff), or as: Prasad Subrahmanya, *Agent Files Index* (snapshot 2026-11-15), https://github.com/prasadus92/agent-files-index.

## Maintenance

The plan is a quarterly snapshot, with the same scripts and the snapshot date in every row. Corrections and requests to remove a repo: open an issue on the GitHub repo.
