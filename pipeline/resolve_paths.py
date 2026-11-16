"""Step 4: for paths not found from the repo root or the file's folder, search the whole tree for a suffix match.

Writes RAW_DIR/path_resolution.json mapping "repo|sha|path" to exact, suffix, missing or unknown.
Usage: python -m pipeline.resolve_paths RAW_DIR
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import paths_from_argv
from .github import MAX_WORKERS, git_tree, log
from .store import RawStore, path_key


def resolve(job: tuple[str, str, list[str]]) -> dict[str, str]:
    repo, sha, unresolved = job
    tree, truncated = git_tree(repo, sha)
    if tree is None:
        return {path_key(repo, sha, p): "unknown" for p in unresolved}
    exact = set(tree)
    out = {}
    for p in unresolved:
        if p in exact:
            verdict = "exact"
        elif any(t.endswith("/" + p) for t in tree):
            verdict = "suffix"
        else:
            verdict = "unknown" if truncated else "missing"
        out[path_key(repo, sha, p)] = verdict
    return out


def main() -> None:
    (raw,) = paths_from_argv("RAW_DIR")
    store = RawStore(raw)
    checks: dict[str, bool] = store.load_json("path_checks.json", {})
    results: dict[str, str] = store.load_json("path_resolution.json", {})
    by_repo: dict[tuple[str, str], list[str]] = {}
    for key, found in checks.items():
        if not found and key not in results:
            repo, sha, p = key.split("|", 2)
            by_repo.setdefault((repo, sha), []).append(p)
    jobs = [(repo, sha, ps) for (repo, sha), ps in by_repo.items()]
    log(f"{len(jobs)} repos with unresolved paths")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for n, found in enumerate(pool.map(resolve, jobs), 1):
            results.update(found)
            if n % 50 == 0:
                store.save_json("path_resolution.json", results)
                log(f"{n}/{len(jobs)} repos")
    store.save_json("path_resolution.json", results)


if __name__ == "__main__":
    main()
