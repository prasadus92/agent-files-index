"""The private raw store: crawl output with full file text. Nothing in it is published as is."""
from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path

from agentfiles import paths
from agentfiles.paths import PathExists


class RawStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, name: str) -> Path:
        return self.root / name

    def load_json(self, name: str, default):
        p = self.path(name)
        return json.loads(p.read_text()) if p.exists() else default

    def save_json(self, name: str, value) -> None:
        self.path(name).write_text(json.dumps(value))

    def append(self, name: str, rows: Iterable[dict]) -> None:
        with self._lock, self.path(name).open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    def read_jsonl(self, pattern: str) -> Iterator[dict]:
        for p in sorted(self.root.glob(pattern)):
            with p.open() as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def repos(self) -> dict[str, dict]:
        """Enumerated repos, first record wins when parallel workers wrote the same repo twice."""
        out: dict[str, dict] = {}
        for r in self.read_jsonl("repos_*.jsonl"):
            if r.get("head_sha"):
                out.setdefault(r["repo"], r)
        return out

    def files(self) -> Iterator[dict]:
        seen: set[tuple[str, str]] = set()
        for row in self.read_jsonl("files.jsonl"):
            key = (row["repo"], row["path"])
            if key not in seen:
                seen.add(key)
                yield row

    def checkpoint(self, name: str) -> Checkpoint:
        return Checkpoint(self.path(name), self._lock)


class Checkpoint:
    """A set of finished work keys, persisted one per line so an interrupted step can resume."""

    def __init__(self, path: Path, lock: threading.Lock):
        self.path, self._lock = path, lock
        self.done = set(path.read_text().splitlines()) if path.exists() else set()

    def __contains__(self, key: str) -> bool:
        return key in self.done

    def add(self, keys: Iterable[str]) -> None:
        keys = list(keys)
        with self._lock, self.path.open("a") as f:
            f.writelines(k + "\n" for k in keys)
        self.done.update(keys)


def path_key(repo: str, sha: str, path: str) -> str:
    return f"{repo}|{sha}|{path}"


class PathEvidence:
    """What the crawl learned about referenced paths: direct lookups at the commit, then whole-tree suffix matches."""

    def __init__(self, store: RawStore):
        self.checks: dict[str, bool] = store.load_json("path_checks.json", {})
        self.resolution: dict[str, str] = store.load_json("path_resolution.json", {})

    def exists_for(self, repo: str, sha: str, file_path: str) -> PathExists:
        def exists(ref: str) -> bool | None:
            keys = [path_key(repo, sha, c) for c in paths.candidates(ref, file_path)]
            if any(self.checks.get(k) is True or self.resolution.get(k) in ("exact", "suffix") for k in keys):
                return True
            return False if any(self.resolution.get(k) == "missing" for k in keys) else None
        return exists
