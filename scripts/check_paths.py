"""Pass 3: check whether paths referenced in AGENTS.md and CLAUDE.md exist at the recorded commit.

Writes RAW_DIR/path_checks.json: {"repo|sha|path": true|false}.
Usage: python scripts/check_paths.py RAW_DIR
"""
from __future__ import annotations

import json
import posixpath
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentfiles.parse import parse  # noqa: E402
from agentfiles.rules import checkable_path  # noqa: E402
from ghgql import GatewayTimeout, log, query  # noqa: E402

MAX_PATHS_PER_FILE = 25
PER_QUERY = 120


def candidates(row: dict) -> list[str]:
    f = parse(row["text"])
    links = set(f.relative_links)
    folder = posixpath.dirname(row["path"])
    out = []
    for p in f.referenced_paths:
        if not checkable_path(p, p in links):
            continue
        clean = p.split("?")[0].split("#")[0].rstrip("/")
        clean = clean[2:] if clean.startswith("./") else clean
        for base in {"", folder}:
            full = posixpath.normpath(posixpath.join(base, clean))
            if not full.startswith(".."):
                out.append(full)
    return sorted(set(out))[:MAX_PATHS_PER_FILE * 2]


def check(items: list[tuple[str, str, str]]) -> dict[str, bool]:
    by_repo: dict[tuple[str, str], list[str]] = {}
    for repo, sha, p in items:
        by_repo.setdefault((repo, sha), []).append(p)
    parts, keys = [], []
    for i, ((repo, sha), paths) in enumerate(by_repo.items()):
        owner, name = repo.split("/", 1)
        objs = []
        for j, p in enumerate(paths):
            objs.append(f"p{j}: object(expression:{json.dumps(sha + ':' + p)}){{__typename}}")
            keys.append((f"r{i}", f"p{j}", f"{repo}|{sha}|{p}"))
        parts.append(f"r{i}: repository(owner:{json.dumps(owner)},name:{json.dumps(name)}){{{' '.join(objs)}}}")
    try:
        data = query("{" + " ".join(parts) + "}", shrink_on_502=True)["data"]
    except GatewayTimeout:
        if len(items) == 1:
            return {}
        mid = len(items) // 2
        return {**check(items[:mid]), **check(items[mid:])}
    out = {}
    for r, pj, key in keys:
        node = data.get(r)
        if node is None:
            continue
        out[key] = node.get(pj) is not None
    return out


def main() -> None:
    raw = Path(sys.argv[1])
    out_path = raw / "path_checks.json"
    results: dict[str, bool] = json.loads(out_path.read_text()) if out_path.exists() else {}
    items = []
    for line in (raw / "files.jsonl").open():
        row = json.loads(line)
        if row["kind"] == "skill_md" or row["is_symlink"] or not row["text"]:
            continue
        for p in candidates(row):
            key = f"{row['repo']}|{row['head_sha']}|{p}"
            if key not in results:
                items.append((row["repo"], row["head_sha"], p))
    items = sorted(set(items))
    log(f"{len(items)} paths to check")
    batches = [items[k:k + PER_QUERY] for k in range(0, len(items), PER_QUERY)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for n, res in enumerate(pool.map(check, batches), 1):
            results.update(res)
            if n % 25 == 0 or n == len(batches):
                out_path.write_text(json.dumps(results))
                log(f"{n}/{len(batches)} batches")
    out_path.write_text(json.dumps(results))


if __name__ == "__main__":
    main()
