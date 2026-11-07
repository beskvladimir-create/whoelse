"""arXiv: descriptive metadata only (titles, abstracts, authors, categories), which arXiv
publishes under CC0. whoelse never looks up submitter emails; arXiv's terms forbid using
them for unsolicited contact, and we don't need them."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

from ..http import http
from ..models import Asset

BASE = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    out: list[dict[str, Any]] = []
    for e in root.findall("a:entry", NS):
        link = e.findtext("a:id", default="", namespaces=NS).strip()
        out.append(
            {
                "id": link.rsplit("/abs/", 1)[-1],
                "url": link,
                "title": " ".join(e.findtext("a:title", default="", namespaces=NS).split()),
                "summary": " ".join(e.findtext("a:summary", default="", namespaces=NS).split()),
                "published": e.findtext("a:published", default="", namespaces=NS),
                "authors": [a.findtext("a:name", default="", namespaces=NS) for a in e.findall("a:author", NS)],
                "categories": [c.get("term", "") for c in e.findall("a:category", NS)],
                "comment": " ".join((e.findtext("arxiv:comment", default="", namespaces=NS) or "").split()),
            }
        )
    return out


_GH = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)(?:/([A-Za-z0-9_.-]+))?")
_HF = re.compile(r"huggingface\.co/(?:datasets/|spaces/)?([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)(?:/([A-Za-z0-9_.-]+))?")


def handles_in(text: str) -> dict[str, list[str]]:
    """GitHub and Hugging Face handles an author put in their own abstract/comment.
    Authors link their own code; this is the cheapest reliable way to join papers to repos."""
    gh = [m.group(1) for m in _GH.finditer(text or "")]
    hf = [m.group(1) for m in _HF.finditer(text or "")]
    skip = {"api", "docs", "papers", "blog", "huggingface", "github", "collections"}
    return {
        "github": sorted({g for g in gh if g.lower() not in skip}),
        "huggingface": sorted({h for h in hf if h.lower() not in skip}),
    }


def entry_to_asset(e: dict[str, Any]) -> Asset:
    links = handles_in((e.get("comment") or "") + " " + (e.get("summary") or ""))
    return Asset(
        kind="paper",
        title=e["title"],
        url=e["url"],
        date=_date(e.get("published")),
        source="arxiv",
        summary=e.get("summary", "")[:1200],
        keywords=[c.lower() for c in e.get("categories", [])],
        coauthors=e.get("authors", []),
        extra={"arxiv": e["id"], "github_handles": ",".join(links["github"]), "hf_handles": ",".join(links["huggingface"])},
    )


async def search(query: str, *, max_results: int = 50, fixture_name: str | None = None) -> list[Asset]:
    text = await http.get_json(
        BASE,
        {"search_query": query, "start": 0, "max_results": max_results, "sortBy": "submittedDate", "sortOrder": "descending"},
        accept="application/atom+xml",
        fixture_name=fixture_name or f"arxiv_{query.lower().replace(' ', '_').replace(':', '-')[:60]}",
    )
    if not text:
        return []
    return [entry_to_asset(e) for e in parse_feed(text)]


async def by_author(name: str, *, max_results: int = 50) -> list[Asset]:
    q = 'au:"' + name.replace('"', "") + '"'
    return await search(q, max_results=max_results, fixture_name=f"arxiv_au_{name.lower().replace(' ', '_')}")


async def by_keywords(keywords: list[str], *, max_results: int = 50) -> list[Asset]:
    q = " AND ".join(f'all:"{k}"' for k in keywords[:3])
    return await search(q, max_results=max_results)
