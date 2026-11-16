# Method

Snapshot: 15 November 2026. Every step can be rerun with the `pipeline` package; the sampling frame is defined in `pipeline/frame.py`.

## Sampling frame

The frame has 2 strata of public GitHub repos. Both use the same search filters: `is:public archived:false fork:false pushed:>=2025-11-15`.

| Stratum | Who is in it | How it was drawn |
| --- | --- | --- |
| A, census | Every repo with 1,000 or more stars | GitHub repository search, split into star ranges of at most 950 results each so no slice reaches the 1,000-result cap |
| B, sample | Repos with 100 to 999 stars | Every repo created on a 5% random sample of the 6,893 calendar days from 1 January 2008 to 14 November 2026 (345 days, seed `20261115`) |

Search reported 38,274 repos for stratum A and the crawl enumerated 38,272. Stratum B has 7,912 repos.

Repos whose owners ask to leave the dataset are dropped from both strata by `pipeline.export`, using the hashed ids in `pipeline/opt_out.txt`. No repo had opted out at this snapshot.

Every repo in stratum B has the same chance of selection, so the sample is self-weighting. To estimate the whole 100 to 999 star population, weight each B repo by 6,893 / 345 = 19.98. The `all_100plus` figures in `summary.json` use that weight. Everything else reports A and B separately, and the headline file statistics are for the census.

## Repository search and code search

On the snapshot date, GitHub code search returned 1,353,728 hits for `filename:AGENTS.md`, 1,067,008 for `filename:CLAUDE.md` and 7,733,248 for `filename:SKILL.md`. It caps every query at 1,000 results, allows 10 queries a minute, and ranks by relevance, so a page of its results has no defined population behind it. A star-based frame names its population, and a census of it can be repeated.

## What counts as an agent file

Version 1 looks in fixed places at the default branch head:

- `AGENTS.md` and `CLAUDE.md` at the repo root, in any letter case
- `.claude/CLAUDE.md`
- `SKILL.md` 1 folder below `skills/`, `.claude/skills/` or `.agents/skills/`, up to 50 skills per repo
- Presence only, without text: `.github/copilot-instructions.md`, `.github/instructions/`, `.cursorrules`, `.cursor/rules/`, `GEMINI.md`, `AGENT.md`, `.windsurfrules`, `.mcp.json`, and the `.claude/` entries `commands`, `agents`, `rules`, `skills` and `settings.json`

Files in monorepo subfolders (for example `packages/api/AGENTS.md`) and skills inside plugin folders are outside version 1, so adoption figures are a lower bound.

## Collection

1. `pipeline.enumerate` lists every repo in the frame through the GraphQL search API. The same query records the root tree and the `.claude`, `.github`, `skills`, `.agents` and `.cursor` folders at the head commit.
2. `pipeline.fetch` fetches each candidate file at that commit SHA, with the number of commits that touched it and the date of the last one.
3. `pipeline.check_paths` checks whether each path a file names exists at that commit, from the repo root and from the file's folder.
4. `pipeline.resolve_paths` fetches the full tree for repos with unresolved paths. A path counts as found if any file or folder in the repo ends with it, because files often describe paths relative to a package folder.
5. `pipeline.export` extracts features with the same code the checker uses (`agentfiles.features`) and writes the published tables.
6. `pipeline.analyze` and `pipeline.charts` produce `summary.json` and the charts.

API calls are authenticated, run at most 3 at a time, and pause when the remaining GraphQL or REST budget runs low. The crawl writes full file text to a private raw folder outside the repo; only derived tables are published.

## Features

The extractor is plain Python with no model in the loop. It reads Markdown structure.

- **Size.** Bytes, lines, non-blank lines, words, and an estimated token count (characters divided by 4).
- **Headings.** Every heading, lower-cased, with numbering, emoji and Markdown removed, then matched against 17 keyword categories (`agentfiles/sections.py`). A heading can fall in more than 1 category.
- **Commands.** Lines in shell code blocks and inline code spans whose first word is a known tool (`npm`, `pytest`, `cargo`, `make`, `./gradlew` and about 120 more), including commands after `cd dir &&`. Each is tagged test, lint, format, typecheck, build, install or run by keyword. `git` and `gh` commands are tagged `vcs`, so a commit message that says "build" does not count as a build.
- **Rule words.** Counts of must-style words (must, always, required), never-style words (never, do not, avoid), and all-caps emphasis (IMPORTANT, NEVER).
- **References.** URLs, relative Markdown links, `@path` imports with a document extension, and inline code that looks like a repo path.
- **Mentions.** Whether the file mentions tests, CI or security anywhere.
- **`/init` line.** Whether a `CLAUDE.md` contains "This file provides guidance to Claude Code", the sentence Claude Code's `/init` command opens the file with. A match means the file started as `/init` output or copied text from one; a file whose opening sentence was deleted does not match.
- **Skills.** Frontmatter present, `name` and `description` lengths, `allowed-tools` present, body length.
- **Maintenance.** Commits touching the file and the last commit date.

The `@import` rule (AF402) runs in the checker, which can see the local file system. The dataset does not compute it.

## Headings published

A heading's text is published only when it has 8 words or fewer, at least 5 repos use the same normalized heading, and it contains no email address, URL, domain name (such as `example.com`) or home-directory path. Every other heading keeps its level and categories with the text left blank. This keeps the table useful for "which sections do files have" without turning it into a copy of file text.

## Secret-like strings

The extractor looks for 11 patterns: key formats for AWS, GitHub, OpenAI, Anthropic, Slack, Google and Stripe live keys, private key headers, JWTs, connection strings with an inline password, and `password = "..."` style assignments. It skips placeholders (`your_api_key`, `xxxx`, `<token>`, `changeme`, `example`), local dev credentials (`postgres:password@localhost`), values shorter than 16 characters or below 3.5 bits of entropy per character for the generic patterns, private key headers with no key material after them, and the well-known example JWTs.

Matched values never enter a derived file. The published tables hold counts by pattern, stratum and file kind, with no repo names. Home-directory paths and injection-like text are reported the same way. A remaining match looks like a secret; it can still be a revoked key or a test fixture.

## Checks on the checker

- Unit tests in `tests/` give every rule a case where it fires and a case where it does not. `python -m tests.ablate` removes each rule in turn and confirms at least 1 test fails.
- The CLI tests cover broken symlinks, a `CLAUDE.md` symlinked to `AGENTS.md`, imports resolved from the importing file, and paths found under a package folder.
- Stale paths: a random sample of 30 unresolved paths was read by hand. 11 were stale (deleted or moved files, broken links). 19 were build output, placeholders, files in other repos, or files the agent is told to create. Read `n_paths_missing` as "worth a look"; about 1 in 3 flagged paths is confirmed stale.
- Secret-like strings: every match left after filtering was read with the value masked. None is usable on its own.
- Prompt-injection-like text: 20 hits from an earlier, broader rule were read by hand. Most were harmless lines such as "never tell the user to restart", so version 1 counts only override phrases ("ignore all previous instructions") and explicit concealment, outside code blocks and quotes.

## Known biases

- Stars measure attention. The frame over-represents AI tooling repos, which gained stars quickly in 2025 and 2026.
- Search results drift by a few repos between calls, and star counts moved during the 35 minutes or so it took to list the census.
- Repos that time out on the GraphQL API can be missing; 2 of the 38,274 reported in stratum A were.
- Heading categories and command kinds come from keyword rules. They miss sections with unusual titles and commands from tools not on the list.
- A path that cannot be found is not always stale. It can be generated at build time, live in a submodule, or name a file the agent is told to create.
