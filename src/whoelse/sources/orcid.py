"""ORCID public API. Returns only what the researcher chose to make public on their own
record: public emails, researcher URLs (personal site, GitHub, Scholar). Keyless."""

from __future__ import annotations

from typing import Any

from ..http import http
from ..models import Contact

BASE = "https://pub.orcid.org/v3.0"


def _classify(url: str, c: Contact) -> None:
    u = url.lower()
    if "github.com/" in u and not c.github:
        c.github = url
        c.provenance["github"] = "orcid researcher-url"
    elif "huggingface.co/" in u and not c.huggingface:
        c.huggingface = url
        c.provenance["huggingface"] = "orcid researcher-url"
    elif "scholar.google" in u and not c.scholar:
        c.scholar = url
        c.provenance["scholar"] = "orcid researcher-url"
    elif "linkedin.com/" in u and not c.linkedin:
        c.linkedin = url
        c.provenance["linkedin"] = "orcid researcher-url"
    elif not c.website and not any(x in u for x in ("twitter.com", "x.com", "researchgate", "orcid.org")):
        c.website = url
        c.provenance["website"] = "orcid researcher-url"
    else:
        c.other.append(url)


async def person(orcid: str) -> Contact:
    data: dict[str, Any] | None = await http.get_json(
        f"{BASE}/{orcid}/person", headers={"Accept": "application/json"}, fixture_name=f"orcid_person_{orcid}"
    )
    c = Contact(orcid=f"https://orcid.org/{orcid}")
    c.provenance["orcid"] = "orcid"
    if not data:
        return c
    for e in ((data.get("emails") or {}).get("email") or []):
        if e.get("visibility") == "public" and e.get("email") and not c.email:
            c.email = e["email"]
            c.provenance["email"] = "orcid public email"
    for r in ((data.get("researcher-urls") or {}).get("researcher-url") or []):
        url = ((r.get("url") or {}).get("value") or "").strip()
        if url:
            _classify(url, c)
    return c


async def search_by_name(given: str, family: str, *, rows: int = 10) -> list[str]:
    """Candidate ORCID iDs for a name. Caller must disambiguate."""
    q = f'given-names:"{given}" AND family-name:"{family}"'
    data = await http.get_json(
        f"{BASE}/search/", {"q": q, "rows": rows}, headers={"Accept": "application/json"},
        fixture_name=f"orcid_search_{given.lower()}_{family.lower()}",
    )
    out = []
    for r in ((data or {}).get("result") or []):
        oid = ((r.get("orcid-identifier") or {}).get("path") or "").strip()
        if oid:
            out.append(oid)
    return out
