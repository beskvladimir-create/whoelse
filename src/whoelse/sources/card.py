"""The whoelse card: a tiny JSON file a person publishes on their own site at
/.well-known/whoelse.json. If a candidate has one, they've opted in and said what they're
open to. No registry, no server, no sign-up: the web is the directory.

Example:
{
  "name": "Ada Example",
  "working_on": ["text-to-SQL on open-weight models", "schema linking"],
  "open_to": ["co-author", "joint benchmark", "talk together"],
  "contact": "ada@example.org",
  "languages": ["en", "pt"],
  "updated": "2026-11-07"
}
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlsplit

from ..http import SourceError, http
from ..models import Card

WELL_KNOWN = "/.well-known/whoelse.json"


def card_url_for(website: str) -> str | None:
    if not website:
        return None
    u = urlsplit(website if "://" in website else "https://" + website)
    if not u.netloc:
        return None
    return f"{u.scheme}://{u.netloc}{WELL_KNOWN}"


async def fetch(website: str) -> Card | None:
    url = card_url_for(website)
    if not url:
        return None
    try:
        data = await http.get_json(url, fixture_name=f"card_{urlsplit(url).netloc}")
    except SourceError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
        return None

    def strs(v: object) -> list[str]:
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(x) for x in v if isinstance(x, (str, int, float))]
        return []

    upd = None
    if data.get("updated"):
        try:
            upd = datetime.strptime(str(data["updated"])[:10], "%Y-%m-%d").date()
        except ValueError:
            upd = None
    return Card(
        name=str(data["name"]),
        working_on=strs(data.get("working_on"))[:10],
        open_to=strs(data.get("open_to"))[:10],
        contact=str(data.get("contact") or "")[:200],
        languages=strs(data.get("languages"))[:10],
        updated=upd,
        url=url,
    )


def render(name: str, working_on: list[str], open_to: list[str], contact: str, languages: list[str]) -> dict:
    return {
        "name": name,
        "working_on": working_on,
        "open_to": open_to,
        "contact": contact,
        "languages": languages,
        "updated": date.today().isoformat(),
        "spec": "https://github.com/beskvladimir-create/whoelse#the-card",
    }
