"""Repos left out of every snapshot at their owners' request. Run: python -m pipeline.opt_out DATA_DIR OWNER/NAME_OR_ID"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
from pathlib import Path

OPT_OUT_FILE = Path(__file__).with_name("opt_out.txt")


def digest(repo_id: int) -> str:
    """Numeric ids survive renames and transfers; the hash keeps names out of the file but not out of reach."""
    return hashlib.sha256(str(repo_id).encode()).hexdigest()


def load(path: Path = OPT_OUT_FILE) -> set[str]:
    if not path.exists():
        return set()
    lines = (line.split("#", 1)[0].strip().lower() for line in path.read_text().splitlines())
    return {line for line in lines if line}


def keep(repos: dict[str, dict], excluded: set[str]) -> dict[str, dict]:
    return {name: r for name, r in repos.items() if digest(r["repo_id"]) not in excluded}


def repo_id(data: Path, repo: str) -> int:
    if repo.isdigit():
        return int(repo)
    with gzip.open(data / "repos.csv.gz", "rt", newline="") as f:
        for row in csv.DictReader(f):
            if row["repo"].lower() == repo.lower():
                return int(row["repo_id"])
    raise SystemExit(f"{repo} is not in {data / 'repos.csv.gz'}")


def add(entry: str, path: Path = OPT_OUT_FILE) -> None:
    if entry in load(path):
        return
    text = path.read_text() if path.exists() else ""
    path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + entry + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("repo")
    args = parser.parse_args()
    add(digest(repo_id(args.data, args.repo)))
    print(f"{args.repo} opted out; rerun pipeline.export, pipeline.analyze and pipeline.charts")


if __name__ == "__main__":
    main()
