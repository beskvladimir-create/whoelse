"""The network: an open registry of people who are waiting to work with someone.

One JSON file per person in a public GitHub repository (default: beskvladimir-create/whoelse-network,
folder `people/`). Reading needs no account. Writing is a pull request that the user's own agent
opens with the user's GitHub token; without a token, whoelse writes the file locally and tells the
user exactly where to put it. The registry holds requests, not profiles: what the person wants to
build, with whom, by when.

A request:
{
  "name": "Ada Example",
  "contact": "ada@example.org",             # where the start-of-work link goes
  "site": "https://ada.example",            # optional; /.well-known/whoelse.json lives there
  "ids": {"orcid": "...", "github": "adax"},
  "working_on": ["text-to-SQL on open-weight models"],
  "keywords": ["text-to-sql", "schema linking"],
  "wants": [{"format": "compare_note", "topic": "text-to-SQL on closed data", "by": "2026-12-01"}],
  "has": ["paper", "repo"],
  "open_to_strangers": true,
  "languages": ["en"],
  "published": "2026-11-08",
  "expires": "2027-02-08"
}
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import settings
from .http import SourceError, http
from .models import Profile
from .profile import fold, slug

DEFAULT_REGISTRY = "beskvladimir-create/whoelse-network"
RAW = "https://raw.githubusercontent.com/{repo}/main/{path}"
API = "https://api.github.com"


def registry_repo() -> str:
    import os
    return os.environ.get("WHOELSE_REGISTRY", DEFAULT_REGISTRY)


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings().github_token:
        h["Authorization"] = f"Bearer {settings().github_token}"
    return h


# ---------- building a request

def make_request(
    prof: Profile,
    *,
    contact: str,
    wants: list[dict[str, str]],
    site: str = "",
    languages: list[str] | None = None,
    months_valid: int = 3,
) -> dict[str, Any]:
    kinds = sorted({a.kind for a in prof.assets})
    return {
        "name": prof.name,
        "contact": contact,
        "site": site,
        "ids": {k: v for k, v in prof.ids.items() if k in ("orcid", "github", "huggingface", "openalex")},
        "working_on": [t for t in list(prof.topics)[:5]],
        "keywords": [k for k in list(prof.keywords)[:12]],
        "wants": wants,
        "has": kinds,
        "open_to_strangers": True,
        "languages": languages or ["en"],
        "published": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=30 * months_valid)).isoformat(),
        "spec": "https://github.com/beskvladimir-create/whoelse#the-network",
    }


def request_path(name: str) -> str:
    return f"people/{slug(name)}.json"


def save_request_locally(req: dict[str, Any]) -> Path:
    d = settings().home / "network"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{slug(req['name'])}.json"
    p.write_text(json.dumps(req, indent=2, ensure_ascii=False))
    return p


# ---------- reading the registry

async def list_requests() -> list[dict[str, Any]]:
    """All current requests. Reads the public tree; no token needed."""
    repo = registry_repo()
    try:
        tree = await http.get_json(
            f"{API}/repos/{repo}/git/trees/main", {"recursive": "1"}, headers=_gh_headers(),
            fixture_name=f"network_tree_{repo.replace('/', '_')}",
        )
    except SourceError as e:
        raise SourceError(f"registry {repo} unreadable: {e}")
    if not tree:
        return []
    paths = [t["path"] for t in tree.get("tree", []) if t.get("path", "").startswith("people/") and t["path"].endswith(".json")]
    out: list[dict[str, Any]] = []
    today = date.today().isoformat()
    for p in paths:
        try:
            req = await http.get_json(RAW.format(repo=repo, path=p), fixture_name=f"network_{Path(p).stem}")
        except SourceError:
            continue
        if isinstance(req, dict) and req.get("name") and (req.get("expires") or "9999") >= today:
            out.append(req)
    return out


# ---------- matching requests against each other

GENERIC = {"large language models", "deep learning", "machine learning", "artificial intelligence", "nlp", "benchmark", "dataset"}


def _kw(req: dict[str, Any]) -> set[str]:
    """Real keywords: the person's own, plus multi-word phrases from their stated topic."""
    out = set()
    for k in req.get("keywords", []) + req.get("working_on", []):
        k = fold(str(k)).strip()
        if k and k not in GENERIC:
            out.add(k)
    return out


def _topic_tokens(req: dict[str, Any]) -> set[str]:
    out = set()
    for w in req.get("wants", []):
        for tok in re.findall(r"[a-z0-9][a-z0-9-]{3,}", fold(str(w.get("topic", "")))):
            if tok not in {"data", "with", "from", "using", "based", "model", "models", "closed", "open"}:
                out.add(tok)
    return out


def match_requests(mine: dict[str, Any], others: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mutual matches: overlapping subject, compatible wants, and they are strangers (no shared id,
    not the same person). Ranked by overlap, then by complementary assets."""
    my_kw = _kw(mine)
    my_ids = {f"{k}:{v}" for k, v in (mine.get("ids") or {}).items() if v}
    my_has = set(mine.get("has", []))
    my_formats = {w.get("format") for w in mine.get("wants", [])}
    out = []
    for o in others:
        if fold(o.get("name", "")) == fold(mine.get("name", "")):
            continue
        if my_ids & {f"{k}:{v}" for k, v in (o.get("ids") or {}).items() if v}:
            continue
        shared = my_kw & _kw(o)
        topic_shared = (_topic_tokens(mine) & (_kw(o) | _topic_tokens(o))) | (_topic_tokens(o) & my_kw)
        if not shared and not topic_shared:
            continue
        shared = shared or topic_shared
        their_formats = {w.get("format") for w in o.get("wants", [])}
        common_formats = sorted((my_formats & their_formats) - {None})
        complement = sorted(set(o.get("has", [])) - my_has)
        score = len(shared) + (1.0 if common_formats else 0.0) + 0.5 * len(complement)
        out.append({
            "request": o,
            "shared": sorted(shared),
            "common_formats": common_formats,
            "they_have_you_dont": complement,
            "score": round(score, 2),
        })
    out.sort(key=lambda m: -m["score"])
    return out


# ---------- writing: a pull request with the user's token

async def publish_via_pr(req: dict[str, Any]) -> dict[str, Any]:
    """Open a PR adding people/<slug>.json to the registry. Requires GITHUB_TOKEN with repo scope.
    Returns {"pr": url} or raises SourceError with the reason."""
    import base64

    if settings().fixtures_dir:
        raise SourceError("offline mode (WHOELSE_FIXTURES set); cannot open a pull request")
    if not settings().github_token:
        raise SourceError("no GITHUB_TOKEN; cannot open a pull request")
    repo = registry_repo()
    owner, name = repo.split("/", 1)
    client = await http._get_client()
    h = _gh_headers()

    # 1. fork (idempotent)
    r = await client.post(f"{API}/repos/{repo}/forks", headers=h)
    if r.status_code not in (200, 202):
        raise SourceError(f"fork failed: HTTP {r.status_code} {r.text[:200]}")
    fork_full = r.json().get("full_name")
    # 2. main sha
    r = await client.get(f"{API}/repos/{repo}/git/ref/heads/main", headers=h)
    r.raise_for_status()
    base_sha = r.json()["object"]["sha"]
    # 3. branch on fork
    branch = f"whoelse/{slug(req['name'])}-{date.today().isoformat()}"
    r = await client.post(f"{API}/repos/{fork_full}/git/refs", headers=h, json={"ref": f"refs/heads/{branch}", "sha": base_sha})
    if r.status_code not in (201, 422):
        raise SourceError(f"branch failed: HTTP {r.status_code} {r.text[:200]}")
    # 4. put file
    path = request_path(req["name"])
    content = base64.b64encode(json.dumps(req, indent=2, ensure_ascii=False).encode()).decode()
    existing = await client.get(f"{API}/repos/{fork_full}/contents/{path}", headers=h, params={"ref": branch})
    body: dict[str, Any] = {"message": f"whoelse: request from {req['name']}", "content": content, "branch": branch}
    if existing.status_code == 200:
        body["sha"] = existing.json()["sha"]
    r = await client.put(f"{API}/repos/{fork_full}/contents/{path}", headers=h, json=body)
    if r.status_code not in (200, 201):
        raise SourceError(f"commit failed: HTTP {r.status_code} {r.text[:200]}")
    # 5. PR
    fork_owner = fork_full.split("/")[0]
    r = await client.post(
        f"{API}/repos/{repo}/pulls", headers=h,
        json={"title": f"{req['name']}: {', '.join(w.get('topic', '') for w in req['wants'][:1])}",
              "head": f"{fork_owner}:{branch}", "base": "main",
              "body": "Open request published by whoelse. Merging makes this person visible to everyone running whoelse."},
    )
    if r.status_code == 422 and "already exists" in r.text:
        return {"pr": "already open", "path": path}
    if r.status_code != 201:
        raise SourceError(f"pull request failed: HTTP {r.status_code} {r.text[:200]}")
    return {"pr": r.json().get("html_url"), "path": path}


def waiting_text(req: dict[str, Any], network_size: int, matches: int, contact: str) -> str:
    topic = (req.get("wants") or [{}])[0].get("topic") or ", ".join(req.get("keywords", [])[:2])
    if matches:
        return f"{matches} people in the network want what you want ({topic}). Joint work can start now."
    if network_size == 0:
        return (f"Your request is published. You are the first person in the network on {topic}. "
                f"When someone with the same problem joins, the work starts by itself and a link goes to {contact}. "
                f"Nothing to do; just don't remove whoelse.")
    return (f"Your request is published. {network_size} people are waiting in the network, none on {topic} yet. "
            f"When one joins, the work starts by itself and a link goes to {contact}. Nothing to do; just don't remove whoelse.")
