# Agent Files Index

Dataset of agent instruction file features, plus the `agentfiles` lint CLI.

## Commands

```bash
python -m unittest discover -s tests -t .
python scripts/ablate.py
python -m agentfiles lint .
uv sync --group data
```

## Layout

- `agentfiles/parse.py`: the parser used by both the dataset build and the checker.
- `agentfiles/rules.py`: lint rules; each entry in `RULES` names its source.
- `scripts/`: the crawl and build pipeline, run in the order listed in `README.md`.
- `data/`: published tables (CC BY 4.0) and the data card.

## Rules

- The CLI stays standard-library only; pandas and pyarrow are for `scripts/` only.
- Every new lint rule gets a test that fails when the rule is removed (`scripts/ablate.py` checks this).
- Never write file text or secret values into `data/`. The raw crawl lives outside the repo.
- Writing in docs and data card: plain sentences, digits for numbers, sentence-case headings, no em dashes.
