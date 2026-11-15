"""Step 1: list every repo in the frame, with the root tree and agent folders at the head commit.

Usage: python -m pipeline.enumerate RAW_DIR [--stratum A|B|both] [--reverse]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import frame
from .github import GatewayTimeout, graphql, log
from .store import RawStore

SEARCH_CAP = 1000
SLICE_TARGET = SEARCH_CAP - 50
FOLDERS = {"root": "", "dotclaude": ".claude", "dotgithub": ".github", "skills": "skills", "dotagents": ".agents",
           "dotcursor": ".cursor"}
TREE = "... on Tree{entries{name type mode}}"
REPO_FIELDS = (
    "nameWithOwner databaseId stargazerCount forkCount createdAt pushedAt isTemplate diskUsage "
    "primaryLanguage{name} licenseInfo{spdxId} defaultBranchRef{name target{oid}} "
    + " ".join(f'{alias}: object(expression:"HEAD:{folder}"){{{TREE}}}' for alias, folder in FOLDERS.items())
)
SEARCH = ("query($q:String!,$first:Int!,$after:String){search(query:$q,type:REPOSITORY,first:$first,after:$after)"
          "{pageInfo{hasNextPage endCursor} nodes{... on Repository{" + REPO_FIELDS + "}}}}")
COUNT = "query($q:String!){search(query:$q,type:REPOSITORY,first:1){repositoryCount}}"
MAX_PAGE, MIN_PAGE = 25, 5


def count(q: str) -> int:
    return graphql(COUNT, {"q": q})["data"]["search"]["repositoryCount"]


def star_slices(lo: int, hi: int | None) -> list[tuple[str, int]]:
    """Split a star range until each slice fits under GitHub search's 1,000-result cap."""
    q = f"{frame.FILTERS} stars:{lo}..{hi}" if hi is not None else f"{frame.FILTERS} stars:>={lo}"
    n = count(q)
    if n <= SLICE_TARGET or (hi is not None and lo == hi):
        if n > SEARCH_CAP:
            log(f"slice {q} has {n} repos; only {SEARCH_CAP} are reachable")
        return [(q, n)]
    if hi is None:
        return star_slices(lo, lo * 4) + star_slices(lo * 4 + 1, None)
    mid = (lo + hi) // 2
    return star_slices(lo, mid) + star_slices(mid + 1, hi)


def day_slices() -> list[tuple[str, int]]:
    lo, hi = frame.SAMPLE_STARS
    queries = [f"{frame.FILTERS} stars:{lo}..{hi} created:{d.isoformat()}" for d in frame.sampled_days()]
    return [(q, count(q)) for q in queries]


def to_record(node: dict) -> dict:
    ref = node.get("defaultBranchRef") or {}
    record = {
        "repo": node["nameWithOwner"], "repo_id": node["databaseId"], "stars": node["stargazerCount"],
        "forks": node["forkCount"], "created_at": node["createdAt"], "pushed_at": node["pushedAt"],
        "is_template": node["isTemplate"], "disk_kb": node["diskUsage"],
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "license": (node.get("licenseInfo") or {}).get("spdxId"),
        "default_branch": ref.get("name"), "head_sha": (ref.get("target") or {}).get("oid"),
    }
    for alias in FOLDERS:
        tree = node.get(alias)
        record[alias] = [{k: e[k] for k in ("name", "type", "mode")} for e in tree["entries"]] if tree else None
    return record


def fetch_slice(q: str) -> list[dict]:
    """Page through 1 slice. Pages shrink when GitHub times out and grow back after 4 good pages."""
    out, after, first, good = [], None, MAX_PAGE, 0
    while True:
        try:
            data = graphql(SEARCH, {"q": q, "first": first, "after": after}, split_on_timeout=first > MIN_PAGE)
        except GatewayTimeout:
            first, good = max(MIN_PAGE, first // 2), 0
            continue
        search = data["data"]["search"]
        good += 1
        if good >= 4 and first < MAX_PAGE:
            first, good = min(MAX_PAGE, first * 2), 0
        out += [to_record(n) for n in search["nodes"] if n and n.get("nameWithOwner")]
        if not search["pageInfo"]["hasNextPage"] or len(out) >= SEARCH_CAP:
            return out
        after = search["pageInfo"]["endCursor"]


def run(store: RawStore, stratum: str, slices: list[tuple[str, int]], reverse: bool) -> None:
    out_name = f"repos_{stratum}{'_rev' if reverse else ''}.jsonl"
    done = store.checkpoint(f"repos_{stratum}.done")
    todo = [s for s in slices if s[0] not in done][:: -1 if reverse else 1]
    log(f"stratum {stratum}: {len(todo)} of {len(slices)} slices to do")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_slice, q): q for q, _ in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            q = futures[fut]
            try:
                rows = fut.result()
            except RuntimeError as e:
                log(f"slice failed: {q}: {e}")
                continue
            store.append(out_name, ({**r, "stratum": stratum, "slice": q} for r in rows))
            done.add([q])
            log(f"stratum {stratum}: {i}/{len(todo)} slices")


def cached_slices(store: RawStore, name: str, build) -> list[tuple[str, int]]:
    slices = store.load_json(name, None)
    if slices is None:
        slices = build()
        store.save_json(name, slices)
    return [tuple(s) for s in slices]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir", type=Path)
    ap.add_argument("--stratum", default="both", choices=["A", "B", "both"])
    ap.add_argument("--reverse", action="store_true", help="work slices from the end, for a second worker process")
    args = ap.parse_args()
    store = RawStore(args.raw_dir)
    if args.stratum in ("A", "both"):
        slices = cached_slices(store, "slices_A.json", lambda: star_slices(frame.CENSUS_MIN_STARS, None))
        run(store, "A", slices, args.reverse)
    if args.stratum in ("B", "both"):
        run(store, "B", cached_slices(store, "slices_B.json", day_slices), args.reverse)


if __name__ == "__main__":
    main()
