"""Minimal GitHub GraphQL client with retry and rate-limit backoff (stdlib only)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.github.com/graphql"
_TOKEN: str | None = None


def token() -> str:
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    return _TOKEN


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


class GatewayTimeout(RuntimeError):
    """GitHub returned 502/504: the query was too heavy; callers should shrink it."""


def query(q: str, variables: dict | None = None, attempts: int = 6, shrink_on_502: bool = False) -> dict:
    body = json.dumps({"query": q, "variables": variables or {}}).encode()
    delay = 5.0
    last_err = ""
    for attempt in range(attempts):
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={
                "Authorization": f"bearer {token()}",
                "Content-Type": "application/json",
                "User-Agent": "agent-files-index",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read())
                remaining = resp.headers.get("x-ratelimit-remaining")
                reset = resp.headers.get("x-ratelimit-reset")
            if remaining is not None and int(remaining) < 200:
                wait = max(0, int(reset) - int(time.time())) + 5
                log(f"graphql budget low ({remaining}); sleeping {wait}s")
                time.sleep(wait)
            errors = payload.get("errors") or []
            fatal = [e for e in errors if e.get("type") not in ("NOT_FOUND",)]
            if fatal and not payload.get("data"):
                last_err = json.dumps(fatal)[:500]
                if any(e.get("type") == "RATE_LIMITED" for e in fatal):
                    log("rate limited; sleeping 60s")
                    time.sleep(60)
                    continue
                raise RuntimeError(last_err)
            return payload
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read()[:120]!r}"
            if e.code in (502, 504) and shrink_on_502:
                raise GatewayTimeout(last_err) from e
            retry_after = e.headers.get("retry-after")
            wait = float(retry_after) if retry_after else delay
            if e.code in (403, 429):
                wait = max(wait, 60)
            log(f"{last_err}; retry in {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 120)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = repr(e)
            log(f"{last_err}; retry in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError(f"query failed after {attempts} attempts: {last_err}")
