"""Hugging Face Hub public API: models, datasets, spaces, by search or by author. Keyless."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..http import http
from ..models import Asset

BASE = "https://huggingface.co/api"


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _to_asset(kind: str, r: dict[str, Any]) -> Asset:
    rid = r.get("id") or r.get("modelId") or ""
    path = {"model": "", "dataset": "datasets/", "space": "spaces/"}[kind]
    tags = [t.lower() for t in (r.get("tags") or []) if ":" not in t][:30]
    stats = {}
    for k in ("downloads", "likes"):
        if r.get(k) is not None:
            stats[k] = int(r[k])
    card = r.get("cardData") or {}
    summary = ""
    if isinstance(card, dict):
        summary = str(card.get("description") or card.get("model_description") or "")[:600]
    return Asset(
        kind=kind,  # type: ignore[arg-type]
        title=rid,
        url=f"https://huggingface.co/{path}{rid}",
        date=_date(r.get("lastModified") or r.get("createdAt")),
        source="huggingface",
        summary=summary,
        keywords=tags,
        stats=stats,
        coauthors=[r.get("author") or rid.split("/")[0]],
        extra={"author": r.get("author") or rid.split("/")[0], "pipeline": str(r.get("pipeline_tag") or "")},
    )


async def _list(kind: str, params: dict[str, Any], fixture_name: str) -> list[Asset]:
    endpoint = {"model": "models", "dataset": "datasets", "space": "spaces"}[kind]
    data = await http.get_json(f"{BASE}/{endpoint}", params, fixture_name=fixture_name)
    return [_to_asset(kind, r) for r in (data or [])]


async def search(query: str, *, kind: str = "model", limit: int = 30) -> list[Asset]:
    return await _list(
        kind,
        {"search": query, "sort": "downloads", "direction": -1, "limit": min(limit, 100), "full": "true"},
        fixture_name=f"hf_{kind}_search_{query.lower().replace(' ', '_')[:60]}",
    )


async def by_author(author: str, *, kind: str = "model", limit: int = 100) -> list[Asset]:
    return await _list(
        kind,
        {"author": author, "sort": "lastModified", "direction": -1, "limit": min(limit, 100), "full": "true"},
        fixture_name=f"hf_{kind}_author_{author}",
    )
