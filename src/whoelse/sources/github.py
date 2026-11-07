"""GitHub REST API (public endpoints). A token is optional and only raises rate limits.
We read: repository search, a user's public profile (name, blog, public email) and repos."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..config import settings
from ..http import http
from ..models import Asset, Contact, Person

BASE = "https://api.github.com"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings().github_token:
        h["Authorization"] = f"Bearer {settings().github_token}"
    return h


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def repo_to_asset(r: dict[str, Any]) -> Asset:
    return Asset(
        kind="repo",
        title=r.get("full_name") or r.get("name") or "",
        url=r.get("html_url") or "",
        date=_date(r.get("pushed_at") or r.get("updated_at")),
        source="github",
        summary=(r.get("description") or "")[:600],
        keywords=[t.lower() for t in (r.get("topics") or [])] + ([str(r.get("language")).lower()] if r.get("language") else []),
        stats={"stars": int(r.get("stargazers_count") or 0), "forks": int(r.get("forks_count") or 0)},
        coauthors=[((r.get("owner") or {}).get("login") or "")],
        extra={"owner": (r.get("owner") or {}).get("login") or "", "license": ((r.get("license") or {}).get("spdx_id") or "")},
    )


async def search_repos(query: str, *, since: date | None = None, limit: int = 30) -> list[Asset]:
    q = query
    if since:
        q += f" pushed:>={since.isoformat()}"
    data = await http.get_json(
        f"{BASE}/search/repositories",
        {"q": q, "sort": "stars", "order": "desc", "per_page": min(limit, 100)},
        headers=_headers(),
        fixture_name=f"github_search_{query.lower().replace(' ', '_')[:60]}",
    )
    return [repo_to_asset(r) for r in (data or {}).get("items", [])]


async def user(login: str) -> Person | None:
    data = await http.get_json(f"{BASE}/users/{login}", headers=_headers(), fixture_name=f"github_user_{login}")
    if not data:
        return None
    c = Contact(github=data.get("html_url"))
    c.provenance["github"] = "github profile"
    if data.get("email"):
        c.email = data["email"]
        c.provenance["email"] = "github public profile email"
    blog = (data.get("blog") or "").strip()
    if blog:
        if not blog.startswith("http"):
            blog = "https://" + blog
        c.website = blog
        c.provenance["website"] = "github profile blog field"
    return Person(
        name=data.get("name") or login,
        ids={"github": login},
        affiliation=(data.get("company") or "").lstrip("@"),
        country=data.get("location") or "",
        contact=c,
    )


async def user_repos(login: str, *, limit: int = 100) -> list[Asset]:
    data = await http.get_json(
        f"{BASE}/users/{login}/repos",
        {"sort": "pushed", "per_page": min(limit, 100), "type": "owner"},
        headers=_headers(),
        fixture_name=f"github_repos_{login}",
    )
    return [repo_to_asset(r) for r in (data or []) if not r.get("fork")]
