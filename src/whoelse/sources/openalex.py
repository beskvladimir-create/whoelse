"""OpenAlex: the open index of scholarly works, authors, topics (CC0 metadata).
Docs: https://docs.openalex.org"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..config import settings
from ..http import http
from ..models import Asset, Person

BASE = "https://api.openalex.org"

WORK_FIELDS = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "publication_date",
        "abstract_inverted_index",
        "authorships",
        "topics",
        "keywords",
        "cited_by_count",
        "primary_location",
        "best_oa_location",
    ]
)


def _params(**kw: Any) -> dict[str, Any]:
    p = {k: v for k, v in kw.items() if v is not None}
    if settings().mailto:
        p["mailto"] = settings().mailto
    if settings().openalex_key:
        p["api_key"] = settings().openalex_key
    return p


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def abstract_from_inverted(idx: dict[str, list[int]] | None, limit: int = 1200) -> str:
    if not idx:
        return ""
    positions: list[tuple[int, str]] = []
    for word, pos in idx.items():
        for p in pos:
            positions.append((p, word))
    positions.sort()
    text = " ".join(w for _, w in positions)
    return text[:limit]


def _short_id(openalex_id: str | None) -> str:
    return (openalex_id or "").rsplit("/", 1)[-1]


def work_to_asset(w: dict[str, Any]) -> Asset:
    loc = w.get("best_oa_location") or w.get("primary_location") or {}
    url = (loc.get("landing_page_url") or w.get("doi") or w.get("id") or "").strip()
    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    topics = [t for t in (w.get("topics") or []) if isinstance(t, dict) and t.get("id") and t.get("display_name")]
    return Asset(
        kind="paper",
        title=w.get("display_name") or "(untitled)",
        url=url,
        date=_date(w.get("publication_date")),
        source="openalex",
        summary=abstract_from_inverted(w.get("abstract_inverted_index")),
        keywords=[k.get("display_name", "").lower() for k in (w.get("keywords") or []) if k.get("display_name")],
        keyword_ids=[(k.get("id") or "").split("openalex.org/")[-1] for k in (w.get("keywords") or []) if k.get("id")],
        topics=[t["display_name"] for t in topics],
        topic_ids=[_short_id(t["id"]) for t in topics],
        stats={"citations": int(w.get("cited_by_count") or 0)},
        coauthors=[((a or {}).get("author") or {}).get("display_name", "") for a in (w.get("authorships") or []) if isinstance(a, dict)],
        extra={"venue": venue, "openalex": _short_id(w.get("id")), "doi": w.get("doi") or ""},
    )


def authorship_to_person(a: dict[str, Any]) -> Person | None:
    if not isinstance(a, dict):
        return None
    au = a.get("author") or {}
    name = au.get("display_name") if isinstance(au, dict) else None
    if not name:
        return None
    insts = [i for i in (a.get("institutions") or []) if isinstance(i, dict)]
    inst = insts[0] if insts else {}
    ids: dict[str, str] = {}
    if au.get("id"):
        ids["openalex"] = _short_id(au["id"])
    if au.get("orcid"):
        ids["orcid"] = au["orcid"].rsplit("/", 1)[-1]
    if not ids:
        return None  # nothing stable to merge on
    p = Person(name=name, ids=ids, affiliation=inst.get("display_name", "") or "", country=inst.get("country_code", "") or "")
    if ids.get("orcid"):
        p.contact.orcid = f"https://orcid.org/{ids['orcid']}"
        p.contact.provenance["orcid"] = "openalex authorship"
    return p


async def search_authors(name: str, *, limit: int = 10) -> list[dict[str, Any]]:
    data = await http.get_json(
        f"{BASE}/authors",
        _params(search=name, **{"per-page": limit}),
        fixture_name=f"openalex_authors_{name.lower().replace(' ', '_')}",
    )
    return (data or {}).get("results", [])


async def author_by_orcid(orcid: str) -> dict[str, Any] | None:
    data = await http.get_json(f"{BASE}/authors/orcid:{orcid}", _params(), fixture_name=f"openalex_author_orcid_{orcid}")
    return data


async def works_of_author(author_id: str, *, since: date | None = None, limit: int = 100) -> list[Asset]:
    flt = f"authorships.author.id:{author_id}"
    if since:
        flt += f",from_publication_date:{since.isoformat()}"
    data = await http.get_json(
        f"{BASE}/works",
        _params(filter=flt, select=WORK_FIELDS, sort="publication_date:desc", **{"per-page": min(limit, 200)}),
        fixture_name=f"openalex_works_author_{author_id}",
    )
    return [work_to_asset(w) for w in (data or {}).get("results", [])]


async def works_by_topic(topic_id: str, *, since: date, limit: int = 100, page: int = 1) -> list[dict[str, Any]]:
    """Raw works (we need authorships) for one OpenAlex topic, recent first by attention."""
    data = await http.get_json(
        f"{BASE}/works",
        _params(
            filter=f"topics.id:{topic_id},from_publication_date:{since.isoformat()},type:article|preprint",
            select=WORK_FIELDS,
            sort="cited_by_count:desc",
            page=page,
            **{"per-page": min(limit, 200)},
        ),
        fixture_name=f"openalex_works_topic_{topic_id}_p{page}",
    )
    return (data or {}).get("results", [])


async def works_by_keyword(keyword_id: str, *, since: date, limit: int = 100, page: int = 1) -> list[dict[str, Any]]:
    """Raw works carrying one OpenAlex keyword (e.g. keywords/text-to-sql). Much sharper than topics."""
    data = await http.get_json(
        f"{BASE}/works",
        _params(
            filter=f"keywords.id:{keyword_id},from_publication_date:{since.isoformat()},type:article|preprint",
            select=WORK_FIELDS,
            sort="cited_by_count:desc",
            page=page,
            **{"per-page": min(limit, 200)},
        ),
        fixture_name=f"openalex_works_kw_{keyword_id.split('/')[-1]}_p{page}",
    )
    return (data or {}).get("results", [])


async def works_search(query: str, *, since: date, limit: int = 50) -> list[dict[str, Any]]:
    data = await http.get_json(
        f"{BASE}/works",
        _params(
            search=query,
            filter=f"from_publication_date:{since.isoformat()},type:article|preprint",
            select=WORK_FIELDS,
            sort="relevance_score:desc",
            **{"per-page": min(limit, 200)},
        ),
        fixture_name=f"openalex_works_search_{query.lower().replace(' ', '_')[:60]}",
    )
    return (data or {}).get("results", [])
