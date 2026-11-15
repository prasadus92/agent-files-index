# Method

Snapshot: 15 November 2026. Everything below can be rerun with the scripts in `scripts/`.

## Sampling frame

Two strata of public GitHub repos. Both use the same search filters: `is:public archived:false fork:false pushed:>=2025-11-15`.

| Stratum | Who is in it | How it was drawn |
| --- | --- | --- |
| A, census | Every repo with 1,000 or more stars | GitHub repository search, split into star ranges of at most 950 results each so no slice hits the 1,000-result cap |
| B, sample | Repos with 100 to 999 stars | Every repo created on a 5% random sample of calendar days from 1 January 2008 to the snapshot date (seed `20261115`) |

Every repo in stratum B has the same chance of selection (the share of days sampled), so the sample is self-weighting. Estimates for "all repos with 100 or more stars" weight each B repo by the number of days in the window divided by the number of days sampled. A and B are reported separately everywhere else.

Why not code search? On the snapshot date, GitHub code search returned 1,353,728 hits for `filename:AGENTS.md`, 1,067,008 for `filename:CLAUDE.md` and 7,733,248 for `filename:SKILL.md`. It caps every query at 1,000 results, allows 10 queries a minute, and ranks by relevance. There is no defined population behind a page of code search results. A star-based frame gives a population you can name, and a census of it can be repeated.

## What counts as an agent file

Version 1 looks in fixed places at the default branch head:

- `AGENTS.md` and `CLAUDE.md` at the repo root (any letter case)
- `.claude/CLAUDE.md`
- `SKILL.md` one folder below `skills/`, `.claude/skills/` or `.agents/skills/`, capped at 50 skills per repo
- Presence only, no text: `.github/copilot-instructions.md`, `.github/instructions/`, `.cursorrules`, `.cursor/rules/`, `GEMINI.md`, `AGENT.md`, `.windsurfrules`, `.mcp.json`, and the `.claude/` folders `commands`, `agents`, `rules`, `skills` and `settings.json`

Nested files in monorepo subfolders (for example `packages/api/AGENTS.md`) and skills inside plugin folders are out of scope for version 1. Adoption numbers are therefore a lower bound on "has an agent file anywhere".

## Collection

1. `scripts/enumerate_repos.py` lists every repo in the frame through the GraphQL search API. In the same query it records the root tree and the `.claude`, `.github`, `skills`, `.agents` and `.cursor` folders, pinned to the head commit SHA.
2. `scripts/fetch_files.py` fetches each candidate file at that commit SHA, plus the number of commits that touched it and the date of the last one.
3. `scripts/check_paths.py` checks whether each path a file mentions exists at that commit, from the repo root and from the file's folder.
4. `scripts/resolve_paths.py` fetches the full tree for repos with unresolved paths. A path counts as found if any file or folder in the repo ends with it, because files are often described relative to a package folder.
5. `scripts/build_dataset.py` parses each file with the same code the checker uses (`agentfiles/parse.py`) and writes the published tables. File text never leaves the machine that ran the crawl.
6. `scripts/analyze.py` and `scripts/make_charts.py` produce `summary.json` and the charts.

All API calls are authenticated, run at most 3 at a time, and back off when the GraphQL points budget runs low.

## Features

The parser is plain Python with no model in the loop. It reads Markdown structure, not meaning.

- **Size.** Bytes, lines, non-blank lines, words, and an estimated token count (characters divided by 4).
- **Headings.** Every heading, lower-cased with numbering, emoji and Markdown stripped, then matched against 17 keyword categories (`agentfiles/parse.py`, `SECTION_CATEGORIES`). A heading can fall in more than one category.
- **Commands.** Lines in shell code blocks and inline code spans whose first word is a known tool (`npm`, `pytest`, `cargo`, `make`, `./gradlew` and about 120 more), including commands after `cd dir &&`. Each command is tagged test, lint, format, typecheck, build, install or run by keyword.
- **Rules.** Counts of must-style words (must, always, required) and never-style words (never, do not, avoid), and of all-caps emphasis (IMPORTANT, NEVER).
- **References.** URLs, relative Markdown links, `@path` imports, and inline code that looks like a repo path.
- **Mentions.** Whether the file mentions tests, CI or security anywhere.
- **Skills.** Frontmatter present, `name` and `description` lengths, `allowed-tools` present, body length.
- **Maintenance.** Commits touching the file and the last commit date.

## Secret-like strings

The parser looks for 11 patterns: cloud and API key formats (AWS, GitHub, OpenAI, Anthropic, Slack, Google, Stripe live keys), private key headers, JWTs, connection strings with an inline password, and `password = "..."` style assignments. Obvious placeholders (`your_api_key`, `xxxx`, `<token>`, `changeme`, `example`) are skipped.

Matched values are never stored. The published data has only counts by pattern, stratum and file kind, with no repo names. A match means "looks like a secret", not "is a live secret": some are revoked keys, test fixtures or documentation examples the placeholder filter missed.

## Checks on the checker

- Unit tests in `tests/` cover every rule with a passing and a failing case. Each rule was removed once to confirm a test fails without it.
- Stale paths were hand-checked on a random sample of 30: 11 were stale (deleted or moved files, broken links); 19 were build output, placeholders, files in other repos or files the agent is told to create. Treat `n_paths_missing` as "worth a look", with about 1 in 3 confirmed stale.
- Secret-like strings were hand-checked: every match left after filtering was read (masked) and none was a usable credential on its own.
- Prompt-injection-like phrases were hand-checked on 20 hits from an earlier, broader rule. That rule caught harmless lines such as "never tell the user to restart", so version 1 counts only override phrases and explicit concealment outside code blocks and quotes.
- Prompt-injection-like phrases inside quotes or backticks are not counted, because files that discuss injection quote the attack text.

## Known biases

- Stars measure attention, not engineering quality. The frame over-represents AI tooling repos, which gained stars quickly in 2025 and 2026.
- Search results drift by a few repos between calls, and star counts change during a crawl that takes about an hour.
- Repos that block indexing, are very large, or time out on the GraphQL API can be missing. The counts of what was enumerated against what search reported are in `summary.json`.
- Heading categories and command detection are keyword rules. They miss sections with unusual titles and commands from tools not on the list.
- A path that cannot be found is not always stale. It can be generated at build time, live in a submodule, or name a file the agent is told to create.
