"""Pass 2: fetch the agent files found in pass 1, pinned to the recorded HEAD commit.

Writes RAW_DIR/files.jsonl with full text. That file stays local and is never published;
only derived features leave this machine.

Usage: python scripts/fetch_files.py RAW_DIR
"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ghgql import GatewayTimeout, log, query

ROOT_FILES = {"agents.md": "agents_md", "claude.md": "claude_md"}
SKILL_PARENTS = [("dotclaude", ".claude/skills"), ("skills", "skills"), ("dotagents", ".agents/skills")]
MAX_SKILLS_PER_REPO = 50
SYMLINK_MODE = 40960
BATCH = 8


def q(s: str) -> str:
    return json.dumps(s)


def entries(repo: dict, key: str) -> list[dict]:
    return repo.get(key) or []


def has_tree(repo: dict, key: str, name: str) -> bool:
    return any(e["name"] == name and e["type"] == "tree" for e in entries(repo, key))


def list_skill_dirs(batch: list[dict]) -> dict[str, dict[str, list[str]]]:
    """For .claude/skills and .agents/skills we only know the folder exists; list its subfolders."""
    parts = []
    for i, r in enumerate(batch):
        owner, name = r["repo"].split("/", 1)
        sha = r["head_sha"]
        parts.append(
            f"r{i}: repository(owner:{q(owner)},name:{q(name)}){{"
            f"c: object(expression:{q(sha + ':.claude/skills')}){{... on Tree{{entries{{name type}}}}}}"
            f"a: object(expression:{q(sha + ':.agents/skills')}){{... on Tree{{entries{{name type}}}}}}}}"
        )
    data = query("{" + " ".join(parts) + "}")["data"]
    out = {}
    for i, r in enumerate(batch):
        node = data.get(f"r{i}") or {}
        out[r["repo"]] = {
            ".claude/skills": [e["name"] for e in ((node.get("c") or {}).get("entries") or []) if e["type"] == "tree"],
            ".agents/skills": [e["name"] for e in ((node.get("a") or {}).get("entries") or []) if e["type"] == "tree"],
        }
    return out


def targets_for(repo: dict, skill_dirs: dict[str, list[str]]) -> list[dict]:
    out = []
    for e in entries(repo, "root"):
        kind = ROOT_FILES.get(e["name"].lower())
        if kind and e["type"] == "blob":
            out.append({"path": e["name"], "kind": kind, "is_symlink": e["mode"] == SYMLINK_MODE})
    for e in entries(repo, "dotclaude"):
        if e["name"].lower() == "claude.md" and e["type"] == "blob":
            out.append({"path": f".claude/{e['name']}", "kind": "claude_md", "is_symlink": e["mode"] == SYMLINK_MODE})
    skills = []
    root_skill_dirs = [e["name"] for e in entries(repo, "skills") if e["type"] == "tree"]
    for parent, names in ((("skills"), root_skill_dirs), *skill_dirs.items()):
        skills.extend(f"{parent}/{n}/SKILL.md" for n in names)
    repo["skill_dirs_total"] = len(skills)
    for p in skills[:MAX_SKILLS_PER_REPO]:
        out.append({"path": p, "kind": "skill_md", "is_symlink": False, "probe": True})
    return out


def fetch_batch(batch: list[tuple[dict, list[dict]]], with_history: bool = True) -> list[dict]:
    parts = []
    for i, (r, targets) in enumerate(batch):
        owner, name = r["repo"].split("/", 1)
        sha = r["head_sha"]
        fs, hs = [], []
        for j, t in enumerate(targets):
            fs.append(f"f{j}: object(expression:{q(sha + ':' + t['path'])}){{... on Blob{{oid byteSize isBinary isTruncated text}}}}")
            if with_history and not t.get("probe"):
                hs.append(f"h{j}: history(path:{q(t['path'])},first:1){{totalCount nodes{{committedDate}}}}")
        hist = f"c: object(oid:{q(sha)}){{... on Commit{{{' '.join(hs)}}}}}" if hs else ""
        parts.append(f"r{i}: repository(owner:{q(owner)},name:{q(name)}){{{' '.join(fs)} {hist}}}")
    data = query("{" + " ".join(parts) + "}", shrink_on_502=True)["data"]
    rows = []
    for i, (r, targets) in enumerate(batch):
        node = data.get(f"r{i}") or {}
        commit = node.get("c") or {}
        for j, t in enumerate(targets):
            blob = node.get(f"f{j}")
            if not blob:
                continue
            h = commit.get(f"h{j}") or {}
            nodes = h.get("nodes") or []
            rows.append({
                "repo": r["repo"], "stratum": r["stratum"], "head_sha": r["head_sha"],
                "path": t["path"], "kind": t["kind"], "is_symlink": t["is_symlink"],
                "blob_sha": blob["oid"], "bytes": blob["byteSize"], "is_binary": blob["isBinary"],
                "is_truncated": blob["isTruncated"], "text": blob["text"],
                "n_commits": h.get("totalCount"), "last_commit_at": nodes[0]["committedDate"] if nodes else None,
            })
    return rows


def fetch_with_split(batch, with_history=True):
    try:
        return fetch_batch(batch, with_history)
    except GatewayTimeout:
        if len(batch) > 1:
            mid = len(batch) // 2
            return fetch_with_split(batch[:mid], with_history) + fetch_with_split(batch[mid:], with_history)
        if with_history:
            log(f"history too slow for {batch[0][0]['repo']}; fetching without history")
            return fetch_with_split(batch, with_history=False)
        log(f"giving up on {batch[0][0]['repo']}")
        return []


def main() -> None:
    raw = Path(sys.argv[1])
    repos, seen = [], set()
    for p in sorted(raw.glob("repos_*.jsonl")):
        for line in p.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                log(f"skipping a corrupt line in {p.name}")
                continue
            if r["repo"] in seen or not r.get("head_sha"):
                continue
            seen.add(r["repo"])
            repos.append(r)
    log(f"{len(repos)} repos loaded")

    needs_listing = [r for r in repos if has_tree(r, "dotclaude", "skills") or has_tree(r, "dotagents", "skills")]
    log(f"{len(needs_listing)} repos need skill folder listing")
    cache = raw / "skill_dirs.json"
    skill_dirs: dict[str, dict[str, list[str]]] = json.loads(cache.read_text()) if cache.exists() else {}
    pending = [r for r in needs_listing if r["repo"] not in skill_dirs]
    for k in range(0, len(pending), 25):
        skill_dirs.update(list_skill_dirs(pending[k:k + 25]))
    cache.write_text(json.dumps(skill_dirs))

    work = []
    for r in repos:
        t = targets_for(r, skill_dirs.get(r["repo"], {}))
        if t:
            work.append((r, t))
    (raw / "skill_dirs_total.json").write_text(json.dumps({r["repo"]: r.get("skill_dirs_total", 0) for r, _ in work}))
    log(f"{len(work)} repos with candidate files, {sum(len(t) for _, t in work)} candidate paths")

    out_path = raw / "files.jsonl"
    done_path = raw / "files.done"
    done = set(done_path.read_text().splitlines()) if done_path.exists() else set()
    work = [w for w in work if w[0]["repo"] + "|" + w[0]["stratum"] not in done]
    batches = [work[k:k + BATCH] for k in range(0, len(work), BATCH)]
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(fetch_with_split, b): b for b in batches}
        for n, fut in enumerate(as_completed(futs), 1):
            b = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:  # noqa: BLE001
                log(f"batch failed: {e}")
                continue
            with lock:
                with out_path.open("a") as f:
                    for row in rows:
                        f.write(json.dumps(row) + "\n")
                with done_path.open("a") as f:
                    for r, _ in b:
                        f.write(r["repo"] + "|" + r["stratum"] + "\n")
            if n % 50 == 0 or n == len(batches):
                log(f"{n}/{len(batches)} batches")


if __name__ == "__main__":
    main()
