"""Pass 1: enumerate the sampling frame and record which agent files each repo has.

Stratum A (census): every public, non-fork, non-archived repo with >= 1,000 stars
pushed on or after the cutoff date.
Stratum B (sample): every repo with 100 to 999 stars (same filters) created on a
uniformly drawn 5% of calendar days since 2008-01-01. Every repo in the stratum has
the same inclusion probability, so stratum B is self-weighting.

Usage: python scripts/enumerate_repos.py OUT_DIR [--cutoff 2025-11-15] [--stratum A|B|both]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ghgql import GatewayTimeout, log, query

SEED = 20261115
SAMPLE_FRACTION = 0.05
FIRST_DAY = dt.date(2008, 1, 1)
CAP = 1000

ENTRY = "entries{name type mode}"
REPO_FIELDS = f"""
  nameWithOwner databaseId stargazerCount forkCount createdAt pushedAt
  isArchived isFork isTemplate diskUsage
  primaryLanguage{{name}} licenseInfo{{spdxId}}
  defaultBranchRef{{name target{{oid}}}}
  root: object(expression:"HEAD:"){{... on Tree{{{ENTRY}}}}}
  dotclaude: object(expression:"HEAD:.claude"){{... on Tree{{{ENTRY}}}}}
  dotgithub: object(expression:"HEAD:.github"){{... on Tree{{{ENTRY}}}}}
  skills: object(expression:"HEAD:skills"){{... on Tree{{{ENTRY}}}}}
  dotagents: object(expression:"HEAD:.agents"){{... on Tree{{{ENTRY}}}}}
  dotcursor: object(expression:"HEAD:.cursor"){{... on Tree{{{ENTRY}}}}}
"""

SEARCH = (
    "query($q:String!,$first:Int!,$after:String){search(query:$q,type:REPOSITORY,first:$first,after:$after)"
    "{repositoryCount pageInfo{hasNextPage endCursor} nodes{... on Repository{" + REPO_FIELDS + "}}}}"
)
COUNT = "query($q:String!){search(query:$q,type:REPOSITORY,first:1){repositoryCount}}"


def base_filters(cutoff: str) -> str:
    return f"is:public archived:false fork:false pushed:>={cutoff}"


def count(q: str) -> int:
    return query(COUNT, {"q": q})["data"]["search"]["repositoryCount"]


def star_slices(filters: str, lo: int, hi: int | None) -> list[tuple[str, int]]:
    """Split a star range until each slice holds <= CAP repos."""
    rng = f"{lo}..{hi}" if hi is not None else f">={lo}"
    q = f"{filters} stars:{rng}"
    n = count(q)
    if n <= CAP - 50 or (hi is not None and lo == hi):
        if n > CAP:
            log(f"WARNING slice {q} has {n} > {CAP}; truncated")
        return [(q, n)]
    if hi is None:
        hi_eff = lo * 4
        return star_slices(filters, lo, hi_eff) + star_slices(filters, hi_eff + 1, None)
    mid = (lo + hi) // 2
    return star_slices(filters, lo, mid) + star_slices(filters, mid + 1, hi)


def flatten(node: dict) -> dict:
    def names(key):
        obj = node.get(key)
        return [{"name": e["name"], "type": e["type"], "mode": e["mode"]} for e in obj["entries"]] if obj else None

    ref = node.get("defaultBranchRef") or {}
    return {
        "repo": node["nameWithOwner"],
        "repo_id": node["databaseId"],
        "stars": node["stargazerCount"],
        "forks": node["forkCount"],
        "created_at": node["createdAt"],
        "pushed_at": node["pushedAt"],
        "is_template": node["isTemplate"],
        "disk_kb": node["diskUsage"],
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "license": (node.get("licenseInfo") or {}).get("spdxId"),
        "default_branch": ref.get("name"),
        "head_sha": (ref.get("target") or {}).get("oid"),
        "root": names("root"),
        "dotclaude": names("dotclaude"),
        "dotgithub": names("dotgithub"),
        "skills": names("skills"),
        "dotagents": names("dotagents"),
        "dotcursor": names("dotcursor"),
    }


def fetch_slice(q: str) -> list[dict]:
    out, after, first, ok_pages = [], None, 25, 0
    while True:
        try:
            data = query(SEARCH, {"q": q, "first": first, "after": after}, shrink_on_502=first > 5)["data"]["search"]
        except GatewayTimeout:
            first = max(5, first // 2)
            ok_pages = 0
            continue
        ok_pages += 1
        if ok_pages >= 4 and first < 25:
            first = min(25, first * 2)
            ok_pages = 0
        out.extend(flatten(n) for n in data["nodes"] if n and n.get("nameWithOwner"))
        if not data["pageInfo"]["hasNextPage"] or len(out) >= CAP:
            return out
        after = data["pageInfo"]["endCursor"]


def run(stratum: str, slices: list[tuple[str, int]], out_dir: Path, reverse: bool = False) -> None:
    out_path = out_dir / f"repos_{stratum}{'_rev' if reverse else ''}.jsonl"
    done_path = out_dir / f"repos_{stratum}.done"
    done = set(done_path.read_text().splitlines()) if done_path.exists() else set()
    todo = [s for s in slices if s[0] not in done]
    if reverse:
        todo.reverse()
    log(f"stratum {stratum}: {len(slices)} slices, {len(todo)} to do, {sum(n for _, n in todo)} repos expected")
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_slice, q): (q, n) for q, n in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            q, n = futures[fut]
            try:
                rows = fut.result()
            except Exception as e:  # noqa: BLE001
                log(f"FAILED {q}: {e}")
                continue
            with lock:
                with out_path.open("a") as f:
                    for r in rows:
                        r["stratum"] = stratum
                        r["slice"] = q
                        f.write(json.dumps(r) + "\n")
                with done_path.open("a") as f:
                    f.write(q + "\n")
            if i % 10 == 0 or i == len(todo):
                log(f"stratum {stratum}: {i}/{len(todo)} slices; last {len(rows)}/{n}")


def sample_days(cutoff: dt.date) -> list[dt.date]:
    days = [FIRST_DAY + dt.timedelta(d) for d in range((cutoff - FIRST_DAY).days + 365)]
    days = [d for d in days if d <= dt.date.today()]
    k = round(SAMPLE_FRACTION * len(days))
    return sorted(random.Random(SEED).sample(days, k))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--cutoff", default="2025-11-15")
    ap.add_argument("--stratum", default="both", choices=["A", "B", "both"])
    ap.add_argument("--reverse", action="store_true", help="work slices from the end (for a second worker process)")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filters = base_filters(args.cutoff)
    meta = {"cutoff": args.cutoff, "filters": filters, "seed": SEED, "sample_fraction": SAMPLE_FRACTION,
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    if args.stratum in ("A", "both"):
        slices_path = out_dir / "slices_A.json"
        if slices_path.exists():
            slices = json.loads(slices_path.read_text())
        else:
            slices = star_slices(filters, 1000, None)
            slices_path.write_text(json.dumps(slices))
        meta["A_expected"] = sum(n for _, n in slices)
        run("A", [tuple(s) for s in slices], out_dir, args.reverse)

    if args.stratum in ("B", "both"):
        days = sample_days(dt.date.fromisoformat(args.cutoff))
        slices_path = out_dir / "slices_B.json"
        if slices_path.exists():
            slices = json.loads(slices_path.read_text())
        else:
            slices = []
            for d in days:
                q = f"{filters} stars:100..999 created:{d.isoformat()}"
                slices.append((q, count(q)))
            slices_path.write_text(json.dumps(slices))
        meta["B_days"] = len(days)
        meta["B_expected"] = sum(n for _, n in slices)
        run("B", [tuple(s) for s in slices], out_dir)

    (out_dir / f"enumerate_meta_{args.stratum}.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
