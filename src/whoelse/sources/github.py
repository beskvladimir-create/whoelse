"""GitHub REST API (public endpoints). A token is optional and only raises rate limits.
We read: repository search, a user's public profile (name, blog, public email) and repos."""

from __future__ import annotations

import re
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
        extra={"owner": (r.get("owner") or {}).get("login") or "", "license": ((r.get("license") or {}).get("spdx_id") or ""),
               "archived": "yes" if r.get("archived") else "", "has_issues": "no" if r.get("has_issues") is False else ""},
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
    p = Person(
        name=data.get("name") or login,
        ids={"github": login},
        affiliation=(data.get("company") or "").lstrip("@"),
        contact=c,
    )
    if data.get("location"):
        p.contact.other.append(f"location: {data['location']}")
    if (data.get("type") or "") == "Organization":
        p.ids["github_org"] = login
    return p


_LOGIN = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)")


def login_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _LOGIN.search(url)
    return m.group(1) if m else None


async def user_repos(login: str, *, limit: int = 100) -> list[Asset]:
    data = await http.get_json(
        f"{BASE}/users/{login}/repos",
        {"sort": "pushed", "per_page": min(limit, 100), "type": "owner"},
        headers=_headers(),
        fixture_name=f"github_repos_{login}",
    )
    return [repo_to_asset(r) for r in (data or []) if not r.get("fork")]


async def search_users(full_name: str, *, limit: int = 3) -> list[str]:
    """Logins whose profile name matches. The caller decides whether a unique hit is trustworthy."""
    data = await http.get_json(
        f"{BASE}/search/users",
        {"q": f"{full_name} in:name", "per_page": min(limit, 10)},
        headers=_headers(),
        fixture_name=f"github_users_{full_name.lower().replace(' ', '_')[:60]}",
    )
    if not data:
        return []
    if int(data.get("total_count") or 0) != 1:
        return [i.get("login", "") for i in (data.get("items") or [])][:limit] if data.get("total_count") else []
    return [data["items"][0]["login"]]
