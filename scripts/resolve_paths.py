"""Pass 3b: for paths not found from the repo root or the file's folder, look for them anywhere in the tree.

A path counts as found if some tree entry equals it or ends with "/<path>" (files are often described
relative to a package folder). Uses one REST call per repo (git trees, recursive).
Writes RAW_DIR/path_resolution.json: {"repo|sha|path": "exact"|"suffix"|"missing"|"unknown"}.
Usage: python scripts/resolve_paths.py RAW_DIR
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ghgql import log, token

CORE_FLOOR = 1500  # leave this much REST budget for other work on the same token


def fetch_tree(repo: str, sha: str) -> tuple[list[str] | None, bool]:
    url = f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1"
    for attempt in range(4):
        req = urllib.request.Request(url, headers={"Authorization": f"bearer {token()}", "User-Agent": "agent-files-index",
                                                   "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                remaining, reset = int(resp.headers["x-ratelimit-remaining"]), int(resp.headers["x-ratelimit-reset"])
                data = json.loads(resp.read())
            if remaining < CORE_FLOOR:
                wait = max(0, reset - int(time.time())) + 5
                log(f"core budget {remaining}; sleeping {wait}s")
                time.sleep(wait)
            return [e["path"] for e in data.get("tree", [])], bool(data.get("truncated"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 409, 422):
                return None, False
            wait = 60 if e.code in (403, 429) else 5 * (attempt + 1)
            log(f"HTTP {e.code} for {repo}; retry in {wait}s")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as e:
            log(f"{e!r} for {repo}; retry")
            time.sleep(5)
    return None, False


def resolve(job: tuple[str, str, list[str]]) -> dict[str, str]:
    repo, sha, paths = job
    tree, truncated = fetch_tree(repo, sha)
    out = {}
    for p in paths:
        key = f"{repo}|{sha}|{p}"
        if tree is None:
            out[key] = "unknown"
            continue
        suffix = "/" + p
        if any(t == p for t in tree):
            out[key] = "exact"
        elif any(t.endswith(suffix) for t in tree):
            out[key] = "suffix"
        else:
            out[key] = "unknown" if truncated else "missing"
    return out


def main() -> None:
    raw = Path(sys.argv[1])
    checks: dict[str, bool] = json.loads((raw / "path_checks.json").read_text())
    out_path = raw / "path_resolution.json"
    results: dict[str, str] = json.loads(out_path.read_text()) if out_path.exists() else {}
    by_repo: dict[tuple[str, str], list[str]] = {}
    for key, found in checks.items():
        if found or key in results:
            continue
        repo, sha, p = key.split("|", 2)
        by_repo.setdefault((repo, sha), []).append(p)
    jobs = [(repo, sha, paths) for (repo, sha), paths in by_repo.items()]
    log(f"{len(jobs)} repos, {sum(len(j[2]) for j in jobs)} unresolved paths")
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, res in enumerate(pool.map(resolve, jobs), 1):
            results.update(res)
            if n % 50 == 0 or n == len(jobs):
                out_path.write_text(json.dumps(results))
                log(f"{n}/{len(jobs)} repos")
    out_path.write_text(json.dumps(results))


if __name__ == "__main__":
    main()
