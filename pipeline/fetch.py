"""Step 2: fetch each candidate agent file at the recorded head commit, with its commit count and last edit.

Writes RAW_DIR/files.jsonl with full text, which stays private.
Usage: python -m pipeline.fetch RAW_DIR
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from agentfiles.rules import AGENTS, CLAUDE, SKILL

from .github import SYMLINK_MODE, GatewayTimeout, graphql, log, quote
from .store import RawStore

ROOT_KINDS = {"agents.md": AGENTS, "claude.md": CLAUDE}
LISTED_SKILL_FOLDERS = {"dotclaude": ".claude/skills", "dotagents": ".agents/skills"}
MAX_SKILLS_PER_REPO = 50
REPOS_PER_QUERY = 8
LISTINGS_PER_QUERY = 25


@dataclass(frozen=True)
class Target:
    path: str
    kind: str
    is_symlink: bool = False
    with_history: bool = True


def entries(repo: dict, folder: str) -> list[dict]:
    return repo.get(folder) or []


def subfolders(repo: dict, folder: str) -> list[str]:
    return [e["name"] for e in entries(repo, folder) if e["type"] == "tree"]


def needs_skill_listing(repo: dict) -> bool:
    """Pass 1 recorded `.claude` and `.agents` one level deep, so their skills folders still need listing."""
    return any("skills" in subfolders(repo, folder) for folder in LISTED_SKILL_FOLDERS)


def list_skill_folders(batch: list[dict]) -> dict[str, dict[str, list[str]]]:
    tree = "... on Tree{entries{name type}}"
    parts = []
    for i, r in enumerate(batch):
        owner, name = r["repo"].split("/", 1)
        objects = " ".join(f'{alias}: object(expression:{quote(r["head_sha"] + ":" + path)}){{{tree}}}'
                           for alias, path in LISTED_SKILL_FOLDERS.items())
        parts.append(f"r{i}: repository(owner:{quote(owner)},name:{quote(name)}){{{objects}}}")
    data = graphql("{" + " ".join(parts) + "}")["data"]
    return {
        r["repo"]: {path: [e["name"] for e in ((data.get(f"r{i}") or {}).get(alias) or {}).get("entries") or []
                           if e["type"] == "tree"]
                    for alias, path in LISTED_SKILL_FOLDERS.items()}
        for i, r in enumerate(batch)
    }


def skill_paths(repo: dict, listed: dict[str, list[str]]) -> list[str]:
    folders = {"skills": subfolders(repo, "skills"), **listed}
    return [f"{parent}/{name}/SKILL.md" for parent, names in folders.items() for name in names]


def targets_for(repo: dict, skills: list[str]) -> list[Target]:
    out = [Target(e["name"], ROOT_KINDS[e["name"].lower()], e["mode"] == SYMLINK_MODE)
           for e in entries(repo, "root") if e["type"] == "blob" and e["name"].lower() in ROOT_KINDS]
    out += [Target(f".claude/{e['name']}", CLAUDE, e["mode"] == SYMLINK_MODE)
            for e in entries(repo, "dotclaude") if e["type"] == "blob" and e["name"].lower() == "claude.md"]
    out += [Target(p, SKILL, with_history=False) for p in skills[:MAX_SKILLS_PER_REPO]]
    return out


def build_query(batch: list[tuple[dict, list[Target]]], with_history: bool) -> str:
    blob = "... on Blob{oid byteSize isBinary isTruncated text}"
    parts = []
    for i, (r, targets) in enumerate(batch):
        owner, name, sha = *r["repo"].split("/", 1), r["head_sha"]
        files = [f"f{j}: object(expression:{quote(sha + ':' + t.path)}){{{blob}}}" for j, t in enumerate(targets)]
        history = [f"h{j}: history(path:{quote(t.path)},first:1){{totalCount nodes{{committedDate}}}}"
                   for j, t in enumerate(targets) if with_history and t.with_history]
        commit = f"c: object(oid:{quote(sha)}){{... on Commit{{{' '.join(history)}}}}}" if history else ""
        parts.append(f"r{i}: repository(owner:{quote(owner)},name:{quote(name)}){{{' '.join(files)} {commit}}}")
    return "{" + " ".join(parts) + "}"


def fetch_batch(batch: list[tuple[dict, list[Target]]], with_history: bool = True) -> list[dict]:
    data = graphql(build_query(batch, with_history), split_on_timeout=True)["data"]
    rows = []
    for i, (r, targets) in enumerate(batch):
        node = data.get(f"r{i}") or {}
        commit = node.get("c") or {}
        for j, t in enumerate(targets):
            if not (blob := node.get(f"f{j}")):
                continue
            history = commit.get(f"h{j}") or {}
            last = (history.get("nodes") or [{}])[0].get("committedDate")
            rows.append({
                "repo": r["repo"], "stratum": r["stratum"], "head_sha": r["head_sha"], "path": t.path, "kind": t.kind,
                "is_symlink": t.is_symlink, "blob_sha": blob["oid"], "bytes": blob["byteSize"],
                "is_binary": blob["isBinary"], "is_truncated": blob["isTruncated"], "text": blob["text"],
                "n_commits": history.get("totalCount"), "last_commit_at": last,
            })
    return rows


def fetch_with_split(batch: list[tuple[dict, list[Target]]], with_history: bool = True) -> list[dict]:
    """Halve the batch on timeouts; a single repo that still times out is fetched without commit history."""
    try:
        return fetch_batch(batch, with_history)
    except GatewayTimeout:
        if len(batch) > 1:
            mid = len(batch) // 2
            return fetch_with_split(batch[:mid], with_history) + fetch_with_split(batch[mid:], with_history)
        if with_history:
            return fetch_with_split(batch, with_history=False)
        log(f"giving up on {batch[0][0]['repo']}")
        return []


def main() -> None:
    store = RawStore(Path(sys.argv[1]))
    repos = list(store.repos().values())
    listings: dict[str, dict[str, list[str]]] = store.load_json("skill_dirs.json", {})
    pending = [r for r in repos if needs_skill_listing(r) and r["repo"] not in listings]
    for k in range(0, len(pending), LISTINGS_PER_QUERY):
        listings.update(list_skill_folders(pending[k:k + LISTINGS_PER_QUERY]))
    store.save_json("skill_dirs.json", listings)

    skills = {r["repo"]: skill_paths(r, listings.get(r["repo"], {})) for r in repos}
    store.save_json("skill_dirs_total.json", {repo: len(p) for repo, p in skills.items() if p})
    done = store.checkpoint("files.done")
    work = [(r, t) for r in repos if (t := targets_for(r, skills[r["repo"]])) and f"{r['repo']}|{r['stratum']}" not in done]
    batches = [work[k:k + REPOS_PER_QUERY] for k in range(0, len(work), REPOS_PER_QUERY)]
    log(f"{len(work)} repos to fetch in {len(batches)} batches")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_with_split, b): b for b in batches}
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                store.append("files.jsonl", fut.result())
            except RuntimeError as e:
                log(f"batch failed: {e}")
                continue
            done.add(f"{r['repo']}|{r['stratum']}" for r, _ in futures[fut])
            if n % 50 == 0:
                log(f"{n}/{len(batches)} batches")


if __name__ == "__main__":
    main()
