# Agent Files Index

An open dataset of `AGENTS.md`, `CLAUDE.md` and `SKILL.md` files in public GitHub repos, and `agentfiles`, the checker built from it.

## Commands

```bash
python -m unittest discover -s tests -t .
python -m tests.ablate
python -m agentfiles lint . --min-severity warning
uv sync --group data
```

The first 3 need only Python 3.11+. `uv sync --group data` installs pandas, pyarrow, fonttools and resvg-py for the pipeline. Chart tests need fonttools and skip without it.

## Layout

- `agentfiles/`: the checker, standard library only. `features.py` extracts features, `rules.py` holds 1 registered check per group of rules, `cli.py` is the command line.
- `pipeline/`: the crawl and build steps, run as `python -m pipeline.<step>` in the order listed in `README.md`. `frame.py` defines the sample; changing it changes the dataset.
- `data/`: published tables and the data card. Regenerate with `pipeline.export`, `pipeline.analyze` and `pipeline.charts`; do not edit by hand.
- `docs/method.md`: how every number is measured. Update it in the same PR as any change to the frame, the features or a rule.

## Rules for changes

- A new or changed lint rule needs a source in its `@rule(...)` entry, a test where it fires, a test where it does not, and a passing `python -m tests.ablate`.
- `agentfiles/` must not import anything outside the standard library.
- Never write file text, secret values, or heading text that fewer than 5 repos share or that runs over 8 words into `data/`. Repos in `pipeline/opt_out.txt` (hashed repo ids, added with `python -m pipeline.opt_out DATA_DIR OWNER/NAME_OR_ID`) stay out of every table. The raw crawl folder stays outside the repo.
- Data is CC BY 4.0 and code is MIT. Do not add data under another license.
- Comments say what the code cannot: a source, a non-obvious rule, or the reason for a choice.
- Writing in docs and the data card: plain sentences, digits for numbers, sentence-case headings, American spelling, no em dashes.

## Pull requests

- Branch from `main` and open a PR; nothing is pushed to `main` directly.
- The PR body says what changed, why, how it was verified, and what was refactored.
- CI must pass: unit tests on Python 3.11 and 3.14, the ablation check, and the repo's own lint.
