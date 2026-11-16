"""Step 3: check whether each path an AGENTS.md or CLAUDE.md names exists at the recorded commit.

Writes RAW_DIR/path_checks.json mapping "repo|sha|path" to true or false.
Usage: python -m pipeline.check_paths RAW_DIR
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from agentfiles import paths
from agentfiles.features import extract

from . import paths_from_argv
from .github import MAX_WORKERS, GatewayTimeout, graphql, log, quote
from .store import RawStore, path_key

MAX_PER_FILE = 50
PER_QUERY = 120


def references(row: dict) -> set[str]:
    f = extract(row["text"])
    links = set(f.relative_links)
    out: set[str] = set()
    for ref in f.referenced_paths:
        if paths.checkable(ref, ref in links):
            out |= paths.candidates(ref, row["path"])
    return set(sorted(out)[:MAX_PER_FILE])


def check(items: list[tuple[str, str, str]]) -> dict[str, bool]:
    by_repo: dict[tuple[str, str], list[str]] = {}
    for repo, sha, p in items:
        by_repo.setdefault((repo, sha), []).append(p)
    parts, keys = [], []
    for i, ((repo, sha), repo_paths) in enumerate(by_repo.items()):
        owner, name = repo.split("/", 1)
        objects = []
        for j, p in enumerate(repo_paths):
            objects.append(f"p{j}: object(expression:{quote(sha + ':' + p)}){{__typename}}")
            keys.append((f"r{i}", f"p{j}", path_key(repo, sha, p)))
        parts.append(f"r{i}: repository(owner:{quote(owner)},name:{quote(name)}){{{' '.join(objects)}}}")
    try:
        data = graphql("{" + " ".join(parts) + "}", split_on_timeout=True)["data"]
    except GatewayTimeout:
        if len(items) == 1:
            return {}
        mid = len(items) // 2
        return {**check(items[:mid]), **check(items[mid:])}
    return {key: data[r].get(p) is not None for r, p, key in keys if data.get(r) is not None}


def main() -> None:
    (raw,) = paths_from_argv("RAW_DIR")
    store = RawStore(raw)
    results: dict[str, bool] = store.load_json("path_checks.json", {})
    items = sorted({(row["repo"], row["head_sha"], p)
                    for row in store.files()
                    if row["kind"] != "skill_md" and not row["is_symlink"] and row["text"]
                    for p in references(row)
                    if path_key(row["repo"], row["head_sha"], p) not in results})
    log(f"{len(items)} paths to check")
    batches = [items[k:k + PER_QUERY] for k in range(0, len(items), PER_QUERY)]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for n, found in enumerate(pool.map(check, batches), 1):
            results.update(found)
            if n % 25 == 0:
                store.save_json("path_checks.json", results)
                log(f"{n}/{len(batches)} batches")
    store.save_json("path_checks.json", results)


if __name__ == "__main__":
    main()
