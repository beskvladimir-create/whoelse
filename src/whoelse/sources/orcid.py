"""ORCID public API. Returns only what the researcher chose to make public on their own
record: public emails, researcher URLs (personal site, GitHub, Scholar). Keyless."""

from __future__ import annotations

import xml.etree.ElementTree as ET
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


_NS = {
    "email": "http://www.orcid.org/ns/email",
    "ru": "http://www.orcid.org/ns/researcher-url",
    "common": "http://www.orcid.org/ns/common",
}


def _from_xml(text: str) -> dict[str, Any]:
    """ORCID answers XML when content negotiation fails. Convert the two bits we use."""
    root = ET.fromstring(text)
    emails = []
    for e in root.iter(f"{{{_NS['email']}}}email"):
        # ORCID nests <email:email visibility=".."><email:email>addr</email:email></email:email>;
        # only the outer element carries visibility, only the inner carries text.
        val = e.findtext(f"{{{_NS['email']}}}email", default="")
        if val:
            emails.append({"email": val.strip(), "visibility": e.get("visibility", "")})
    urls = []
    for r in root.iter(f"{{{_NS['ru']}}}researcher-url"):
        val = r.findtext(f"{{{_NS['ru']}}}url", default="")
        urls.append({"url": {"value": val}})
    return {"emails": {"email": emails}, "researcher-urls": {"researcher-url": urls}}


async def person(orcid: str) -> Contact:
    c = Contact(orcid=f"https://orcid.org/{orcid}")
    c.provenance["orcid"] = "orcid"
    raw = await http.get_json(
        f"{BASE}/{orcid}/person",
        headers={"Accept": "application/vnd.orcid+json"},
        fixture_name=f"orcid_person_{orcid}",
        accept="application/vnd.orcid+json",
    )
    data: dict[str, Any] | None
    if isinstance(raw, str):
        txt = raw.lstrip()
        if txt.startswith("<"):
            try:
                data = _from_xml(txt)
            except ET.ParseError:
                data = None
        else:
            import json as _json
            try:
                data = _json.loads(txt)
            except ValueError:
                data = None
    else:
        data = raw
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
