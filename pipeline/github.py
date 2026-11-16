"""GitHub GraphQL and REST access with retry, budget-aware backoff, and a signal for queries that are too heavy."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from functools import cache

GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "agent-files-index"
GRAPHQL_FLOOR = 200
REST_FLOOR = 1500  # leaves REST budget for other work sharing the same token
SYMLINK_MODE = 40960
MAX_WORKERS = 3


class GatewayTimeout(RuntimeError):
    """GitHub returned 502 or 504, which for GraphQL means the query was too heavy and should be split."""


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


@cache
def token() -> str:
    return os.environ.get("GITHUB_TOKEN") or subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def quote(value: str) -> str:
    return json.dumps(value)


def graphql(query: str, variables: dict | None = None, attempts: int = 6, split_on_timeout: bool = False) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    delay, last_error = 5.0, ""
    for _ in range(attempts):
        try:
            payload, headers = _request(GRAPHQL_URL, body)
            _respect_budget(headers, GRAPHQL_FLOOR, "graphql")
            errors = [e for e in payload.get("errors") or [] if e.get("type") != "NOT_FOUND"]
            if errors and not payload.get("data"):
                last_error = json.dumps(errors)[:500]
                if any(e.get("type") == "RATE_LIMITED" for e in errors):
                    log("rate limited; sleeping 60s")
                    time.sleep(60)
                    continue
                raise RuntimeError(last_error)
            return payload
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.read()[:120]!r}"
            if e.code in (502, 504) and split_on_timeout:
                raise GatewayTimeout(last_error) from e
            wait = float(e.headers.get("retry-after") or delay)
            time.sleep(max(wait, 60) if e.code in (403, 429) else wait)
            delay = min(delay * 2, 120)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_error = repr(e)
            time.sleep(delay)
            delay = min(delay * 2, 120)
        log(f"{last_error}; retrying")
    raise RuntimeError(f"query failed after {attempts} attempts: {last_error}")


def git_tree(repo: str, sha: str) -> tuple[list[str] | None, bool]:
    """All paths in a commit's tree, and whether GitHub truncated the listing. None if the tree is unavailable."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1"
    for attempt in range(4):
        try:
            data, headers = _request(url)
            _respect_budget(headers, REST_FLOOR, "rest")
            return [e["path"] for e in data.get("tree", [])], bool(data.get("truncated"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 409, 422):
                return None, False
            time.sleep(60 if e.code in (403, 429) else 5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5)
    return None, False


def _request(url: str, body: bytes | None = None) -> tuple[dict, dict]:
    headers = {"Authorization": f"bearer {token()}", "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read()), dict(resp.headers)


def _respect_budget(headers: dict, floor: int, name: str) -> None:
    remaining, reset = headers.get("x-ratelimit-remaining"), headers.get("x-ratelimit-reset")
    if remaining is not None and reset is not None and int(remaining) < floor:
        wait = max(0, int(reset) - int(time.time())) + 5
        log(f"{name} budget at {remaining}; sleeping {wait}s")
        time.sleep(wait)
