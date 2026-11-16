"""Repos left out of every snapshot at their owners' request. Run: python -m pipeline.opt_out DATA_DIR OWNER/NAME"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
from pathlib import Path

OPT_OUT_FILE = Path(__file__).with_name("opt_out.txt")


def digest(repo_id: int) -> str:
    """The list holds hashes of numeric repo ids, so it names nobody and survives renames and transfers."""
    return hashlib.sha256(str(repo_id).encode()).hexdigest()


def load(path: Path = OPT_OUT_FILE) -> set[str]:
    if not path.exists():
        return set()
    lines = (line.split("#", 1)[0].strip().lower() for line in path.read_text().splitlines())
    return {line for line in lines if line}


def keep(repos: dict[str, dict], excluded: set[str]) -> dict[str, dict]:
    return {name: r for name, r in repos.items() if digest(r["repo_id"]) not in excluded}


def repo_id(data: Path, repo: str) -> int:
    with gzip.open(data / "repos.csv.gz", "rt", newline="") as f:
        for row in csv.DictReader(f):
            if row["repo"].lower() == repo.lower():
                return int(row["repo_id"])
    raise SystemExit(f"{repo} is not in {data / 'repos.csv.gz'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("repo")
    args = parser.parse_args()
    entry = digest(repo_id(args.data, args.repo))
    if entry not in load():
        with OPT_OUT_FILE.open("a") as f:
            f.write(entry + "\n")
    print(f"{args.repo} opted out; rerun pipeline.export, pipeline.analyze and pipeline.charts")


if __name__ == "__main__":
    main()
