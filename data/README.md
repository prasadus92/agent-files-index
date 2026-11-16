---
license: cc-by-4.0
language:
  - en
pretty_name: Agent Files Index
size_categories:
  - 100K<n<1M
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

A CLAUDE.md file or AGENTS.md file is a Markdown file in a repo that a coding agent reads before it starts work. This dataset holds structural features of those files, and of `SKILL.md` files, in public GitHub repos, with flags for other agent config files (Copilot instructions, Cursor rules, `GEMINI.md`, `.mcp.json`). Snapshot taken 15 November 2026.

## Summary

| | |
| --- | --- |
| Repos in the frame | 38,272 with 1,000+ stars (census); 7,912 with 100 to 999 stars (sample) |
| Agent files | 7,502 `AGENTS.md`, 5,252 `CLAUDE.md`, 29,352 `SKILL.md` |
| Headings | 474,609 (text published for short headings shared by 5 or more repos) |
| Repos with an `AGENTS.md` or `CLAUDE.md` | 21.3% of the census, 15.2% of the sample |
| Snapshot | 2026-11-15 |

## Who made it and why

Prasad Subrahmanya ([prasad.tech](https://prasad.tech)) built it to answer practical questions about these files with counts: how long they are, what sections they have, whether they tell the agent how to run the tests, and how often they point at files that no longer exist. The same extractor powers the `agentfiles` checker in this repo.

## Sampling frame

- **Stratum A, census:** every public, non-fork, non-archived repo with 1,000 or more stars and a push on or after 15 November 2025.
- **Stratum B, sample:** the same filters with 100 to 999 stars, limited to repos created on 345 days drawn at random from the 6,893 days between 1 January 2008 and 14 November 2026 (seed `20261115`). Each repo in B had the same chance of selection, so B is self-weighting. To estimate the whole 100 to 999 star population, weight each B row by `B_weight` in `summary.json`.

Full method, including the reason for repository search over code search: [`../docs/method.md`](../docs/method.md).

## Files

| File | Rows | Description |
| --- | --- | --- |
| `repos` | 1 per repo in the frame | Stars, language, license, dates, head commit, and a flag per agent file location |
| `files` | 1 per agent file | Size, structure, commands, rule words, references, maintenance and lint counts |
| `headings` | 1 per heading | Level and section categories, and the normalized text when it has 8 words or fewer, 5 or more repos share it, and it holds no email address, URL, domain name or home path |
| `commands` | 1 per command | The tool (`pnpm`, `pytest`, or `./*` for a local script) and its kind; full command lines stay private |
| `lint_findings` | 1 per rule hit | Rule id and severity per file; the secret, home-path and injection rules are excluded |
| `secret_like_summary` | 1 per pattern, stratum and kind | Files matching the raw pattern and files left after filtering; no repo names |
| `risky_text_summary` | 1 per signal, stratum and kind | Files with home-directory paths or injection-like text; counts only, no repo names |
| `summary.json` | | The headline numbers in the README and the post |

Each table comes as gzipped CSV (`.csv.gz`) and Parquet with the same columns. Every table has a `snapshot` column.

### Key columns in `files`

| Column | Meaning |
| --- | --- |
| `repo`, `path`, `commit_sha`, `blob_sha` | Provenance: fetch `https://github.com/<repo>/blob/<commit_sha>/<path>` for the original |
| `stratum` | `A` (1,000+ stars, census) or `B` (100 to 999 stars, sample) |
| `kind` | `agents_md`, `claude_md` or `skill_md` |
| `is_symlink` | The file is a symlink; its features describe the link text, so filter these out for content statistics |
| `bytes`, `lines`, `nonblank_lines`, `words`, `est_tokens` | Size; `est_tokens` is characters divided by 4 |
| `n_headings`, `n_h1`, `n_h2`, `max_heading_depth` | Heading structure |
| `sec_<category>` | True if any heading falls in that category (17 keyword categories, see `agentfiles/sections.py`) |
| `n_commands`, `n_<kind>_cmds` | Commands found in shell code blocks and inline code, by kind: test, lint, format, typecheck, build, install, run; `git` and `gh` commands count toward `n_commands` only |
| `package_managers` | JS package managers used for project installs (`npm;pnpm`); global installs do not count |
| `n_must`, `n_never`, `n_emphasis_caps` | Must-style words, never-style words, all-caps emphasis words |
| `mentions_tests`, `mentions_ci`, `mentions_security` | The text mentions these anywhere |
| `n_urls`, `n_relative_links`, `n_imports`, `n_referenced_paths` | References out of the file |
| `n_paths_checked`, `n_paths_missing` | Referenced paths that could be checked, and those found nowhere in the repo tree at `commit_sha`; `n_paths_missing` stops at 20 |
| `n_commits`, `last_commit_at` | Commits that touched the file, and the date of the last one |
| `skill_*` | Skill frontmatter: present, `name` and `description` lengths, `allowed-tools` present, body length |
| `similarity_to_agents_md` | For a `CLAUDE.md` next to an `AGENTS.md`: Jaccard similarity of their non-blank lines |
| `agents_md_link` | For a `CLAUDE.md` next to an `AGENTS.md`: `symlink`, `import`, `mention` or `none` |
| `lint_errors`, `lint_warnings`, `lint_info`, `lint_rules` | `agentfiles` results, excluding AF101 (secrets), AF102 (home-directory paths) and AF103 (injection-like text) |

### Key columns in `repos`

`has_agents_md`, `has_claude_md`, `has_dot_claude_claude_md`, `claude_md_is_symlink`, `has_claude_dir`, `has_claude_settings`, `has_claude_commands`, `has_claude_agents`, `has_claude_rules`, `has_claude_skills`, `has_root_skills_dir`, `has_agents_skills`, `has_mcp_json`, `has_agent_md`, `has_gemini_md`, `has_cursorrules`, `has_cursor_rules_dir`, `has_windsurfrules`, `has_copilot_instructions`, `has_copilot_instructions_dir`, `has_github_workflows`, `n_skill_files`, `n_skill_dirs`. File names are matched in any letter case.

## What is not in the data

- **File text.** Only derived features, common headings and command tool names are published. The originals stay in their repos under their own licenses.
- **Secret values.** Secret-like strings are counted by pattern in a table with no repo names. Matched values never enter a derived file. The crawl's raw text stays on the machine that ran it.
- **Nested files.** Version 1 reads root files, `.claude/CLAUDE.md` and 1 level of skills folders. Monorepo subfolder files are not included, so adoption is a lower bound.

## Known biases and limits

- Stars measure attention. The frame over-represents AI tooling repos.
- The census ran over about an hour; star counts and pushes moved during it.
- Section categories and command kinds come from keyword rules and miss unusual wording.
- A path found nowhere in the tree may still be fine: a build output, a submodule, or a file the agent is meant to create. Placeholders and common build folders are excluded before counting, and a hand check found about 1 in 3 flagged paths stale.
- Secret-like matches are an upper bound. Placeholders, local dev credentials and low-entropy values are filtered; what is left can still be a revoked key or a test fixture.

## License and sources

Copyright Prasad Subrahmanya (https://prasad.tech). The tables, the derived features and `summary.json` are licensed CC BY 4.0 ([`LICENSE`](LICENSE)).

- **The source files are not covered.** They belong to their repos and keep their own licenses. The dataset holds no copy of their text: only counts and flags computed from it, command tool names, and headings of 8 words or fewer that 5 or more repos share.
- **Repo metadata** (stars, forks, language, license, dates, head commit) comes from the GitHub REST and GraphQL APIs.
- **`license`** is GitHub's SPDX detection for the repo at crawl time. `NOASSERTION` means GitHub found a license file it could not identify; a missing value means it found none. Repos without a license are included, because only counts, flags, tool names and short shared headings are taken from their files. Check the repo itself before reusing any of its files.
- **Provenance.** Every file row carries `repo`, `path`, `commit_sha` and `blob_sha`, so the original is at `https://github.com/<repo>/blob/<commit_sha>/<path>`.
- **Collection.** The crawl used the GitHub API. GitHub's [Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) allow research use of public information when the publications are open access, as this dataset is. The only personal detail in the tables is the account name inside each repo's `owner/name`; there are no names, email addresses or file authors. Owners can ask for [removal](#removal).

## Removal

To take a repo out of the dataset, open an issue with its `owner/name`, or use the contact form at [prasad.tech/contact](https://prasad.tech/contact/) if you'd rather not ask in public. A hash of the repo's numeric GitHub id goes into [`pipeline/opt_out.txt`](../pipeline/opt_out.txt), so the list names nobody and still matches after a rename or transfer. The repo's rows leave `data/` in the next commit and later snapshots skip it. Earlier commits and copies already downloaded keep the old rows. Corrections work the same way.

## Citation

Cite with [`../CITATION.cff`](../CITATION.cff), or as: Prasad Subrahmanya, *Agent Files Index* (snapshot 2026-11-15), https://github.com/prasadus92/agent-files-index.

## Maintenance

The plan is a quarterly snapshot, with the same scripts and the snapshot date in every row.
