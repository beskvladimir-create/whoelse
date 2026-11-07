"""Your people. Once you've decided someone is one of yours, whoelse keeps an eye on what
they ship, so you can support it when it's real and fresh. Stars, shares, citations are
yours to give; this only tells you when there is something to give them for."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

from .config import settings
from .http import SourceError
from .models import Asset, Person
from .profile import dedupe_assets
from .sources import github, huggingface, openalex


def _path():
    return settings().home / "peers.json"


def load_peers() -> dict[str, dict]:
    p = _path()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_peers(peers: dict[str, dict]) -> None:
    _path().write_text(json.dumps(peers, indent=2, default=str))


def add_peer(person: Person, note: str = "") -> dict:
    peers = load_peers()
    key = person.ids.get("openalex") or person.ids.get("github") or person.ids.get("huggingface") or person.name
    peers[key] = {
        "name": person.name,
        "ids": person.ids,
        "affiliation": person.affiliation,
        "contact": {k: v for k, v in person.contact.model_dump().items() if v and k != "provenance"},
        "note": note,
        "added": date.today().isoformat(),
        "last_checked": None,
    }
    save_peers(peers)
    return peers[key]


def remove_peer(key_or_name: str) -> bool:
    peers = load_peers()
    for k in list(peers):
        if k == key_or_name or peers[k]["name"].lower() == key_or_name.lower():
            del peers[k]
            save_peers(peers)
            return True
    return False


async def _fresh_assets(peer: dict, since: date) -> list[Asset]:
    ids = peer.get("ids", {})
    out: list[Asset] = []

    async def oa() -> None:
        if ids.get("openalex"):
            try:
                out.extend(await openalex.works_of_author(ids["openalex"], since=since, limit=20))
            except SourceError:
                pass

    async def gh() -> None:
        if ids.get("github"):
            try:
                out.extend([r for r in await github.user_repos(ids["github"], limit=30) if r.date and r.date >= since])
            except SourceError:
                pass

    async def hf() -> None:
        if ids.get("huggingface"):
            try:
                for kind in ("model", "dataset"):
                    out.extend([m for m in await huggingface.by_author(ids["huggingface"], kind=kind, limit=30) if m.date and m.date >= since])
            except SourceError:
                pass

    await asyncio.gather(oa(), gh(), hf())
    return sorted(dedupe_assets(out), key=lambda a: a.date or date.min, reverse=True)


async def whats_new(days: int = 30) -> list[dict]:
    peers = load_peers()
    since = date.today() - timedelta(days=days)
    results = await asyncio.gather(*(_fresh_assets(p, since) for p in peers.values()))
    feed = []
    for (key, peer), assets in zip(peers.items(), results):
        if assets:
            feed.append(
                {
                    "peer": peer["name"],
                    "key": key,
                    "new": [
                        {"kind": a.kind, "title": a.title, "url": a.url, "date": a.date.isoformat() if a.date else None, "stats": a.stats}
                        for a in assets[:10]
                    ],
                    "how_you_could_support": _support_ideas(assets),
                }
            )
        peer["last_checked"] = date.today().isoformat()
    save_peers(peers)
    feed.sort(key=lambda f: f["new"][0]["date"] or "", reverse=True)
    return feed


def _support_ideas(assets: list[Asset]) -> list[str]:
    kinds = {a.kind for a in assets}
    ideas = []
    if "repo" in kinds:
        ideas.append("Try the repo; if it's useful, star it and open an issue with real feedback.")
    if "paper" in kinds:
        ideas.append("Read it; if it's relevant to your next paper, cite it. If you disagree, tell them, that's worth more.")
    if "model" in kinds or "dataset" in kinds:
        ideas.append("Run it on your data and post the result (good or bad) as a discussion on the Hub page.")
    ideas.append("Share it with the one person you know who needs exactly this.")
    return ideas
