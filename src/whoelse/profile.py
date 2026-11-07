"""Build a person's profile from their public work across sources, and aggregate it into
topics and keywords with weights. Used both for the user and for candidates."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import date
from typing import Iterable

from .config import settings
from .http import SourceError
from .models import Asset, Person, Profile
from .sources import arxiv, github, huggingface, openalex, orcid

STOP_KEYWORDS = {
    "python", "jupyter notebook", "html", "shell", "javascript", "typescript", "c++", "java", "rust", "go",
    "cs.lg", "cs.cl", "cs.ai", "cs.cv", "cs.db", "cs.ir", "cs.se", "stat.ml", "cs.dl", "cs.hc", "cs.cy",
    "transformers", "pytorch", "safetensors", "endpoints_compatible", "autotrain_compatible", "region:us",
    "text-generation", "text-generation-inference", "license", "arxiv", "dataset", "model",
}

_slug_re = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    return _slug_re.sub("-", name.lower()).strip("-")


def _recency_weight(d: date | None, today: date | None = None) -> float:
    """1.0 for this year, halving every ~2.5 years; old work still counts, a little."""
    if not d:
        return 0.4
    today = today or date.today()
    years = max(0.0, (today - d).days / 365.25)
    return 0.15 + 0.85 * (0.5 ** (years / 2.5))


def _attention(a: Asset) -> float:
    s = a.stats
    n = s.get("citations", 0) + s.get("stars", 0) + s.get("likes", 0) * 2 + s.get("downloads", 0) / 1000
    return 1.0 + math.log1p(n)


def dedupe_assets(assets: Iterable[Asset]) -> list[Asset]:
    seen: dict[str, Asset] = {}
    for a in assets:
        key = re.sub(r"\W+", " ", a.title.lower()).strip()[:80]
        if key in seen:
            # keep the richer one, merge stats
            keep = seen[key]
            for k, v in a.stats.items():
                keep.stats[k] = max(keep.stats.get(k, 0), v)
            if not keep.topics and a.topics:
                keep.topics, keep.topic_ids = a.topics, a.topic_ids
            if not keep.summary and a.summary:
                keep.summary = a.summary
            continue
        seen[key] = a
    return list(seen.values())


def aggregate(person: Person) -> None:
    """Fill person.topics / topic_ids / keywords / last_active from person.assets."""
    topics: dict[str, float] = {}
    topic_ids: dict[str, float] = {}
    keywords: dict[str, float] = {}
    last: date | None = None
    for a in person.assets:
        w = _recency_weight(a.date) * _attention(a)
        for t, tid in zip(a.topics, a.topic_ids or [""] * len(a.topics)):
            topics[t] = topics.get(t, 0.0) + w
            if tid:
                topic_ids[tid] = topic_ids.get(tid, 0.0) + w
        for k in a.keywords:
            k = k.strip().lower()
            if len(k) < 3 or k in STOP_KEYWORDS:
                continue
            keywords[k] = keywords.get(k, 0.0) + w
        if a.date and (last is None or a.date > last):
            last = a.date
    person.topics = dict(sorted(topics.items(), key=lambda x: -x[1])[:25])
    person.topic_ids = dict(sorted(topic_ids.items(), key=lambda x: -x[1])[:25])
    person.keywords = dict(sorted(keywords.items(), key=lambda x: -x[1])[:40])
    person.last_active = last


async def _openalex_author(name: str, orcid_id: str | None, affiliation_hint: str) -> dict | None:
    if orcid_id:
        au = await openalex.author_by_orcid(orcid_id)
        if au:
            return au
    results = await openalex.search_authors(name)
    if not results:
        return None
    if affiliation_hint:
        hint = affiliation_hint.lower()
        for r in results:
            insts = " ".join(i.get("display_name", "") for i in (r.get("affiliations") or [{}]) for i in [i.get("institution") or {}])
            if hint in insts.lower():
                return r
    # Otherwise the most productive match. The user can override with an ORCID.
    return max(results, key=lambda r: r.get("works_count", 0))


async def build_profile(
    name: str,
    *,
    orcid_id: str | None = None,
    github_login: str | None = None,
    huggingface_user: str | None = None,
    affiliation_hint: str = "",
    years: int = 10,
) -> Profile:
    prof = Profile(name=name, built_at=date.today())
    since = date(date.today().year - years, 1, 1)
    assets: list[Asset] = []

    async def do_openalex() -> None:
        try:
            au = await _openalex_author(name, orcid_id, affiliation_hint)
            if not au:
                prof.notes.append("OpenAlex: no author record found for that name; add an ORCID to pin it down.")
                return
            aid = au.get("id", "").rsplit("/", 1)[-1]
            prof.ids["openalex"] = aid
            if au.get("orcid") and not prof.ids.get("orcid"):
                prof.ids["orcid"] = au["orcid"].rsplit("/", 1)[-1]
            inst = ((au.get("last_known_institutions") or [{}])[0]) if au.get("last_known_institutions") else {}
            prof.affiliation = prof.affiliation or inst.get("display_name", "") or ""
            prof.country = prof.country or inst.get("country_code", "") or ""
            works = await openalex.works_of_author(aid, since=since)
            assets.extend(works)
            prof.sources_used.append(f"openalex ({len(works)} works)")
        except SourceError as e:
            prof.notes.append(f"OpenAlex unavailable: {e}")

    async def do_arxiv() -> None:
        try:
            papers = await arxiv.by_author(name)
            assets.extend(papers)
            prof.sources_used.append(f"arxiv ({len(papers)} preprints)")
        except SourceError as e:
            prof.notes.append(f"arXiv unavailable: {e}")

    async def do_github() -> None:
        if not github_login:
            return
        try:
            u = await github.user(github_login)
            if u:
                prof.ids["github"] = github_login
                if u.contact.email and not prof.contact.email:
                    prof.contact.email = u.contact.email
                    prof.contact.provenance["email"] = u.contact.provenance.get("email", "github")
                if u.contact.website and not prof.contact.website:
                    prof.contact.website = u.contact.website
                    prof.contact.provenance["website"] = "github profile"
                prof.contact.github = u.contact.github
            repos = await github.user_repos(github_login)
            assets.extend(repos)
            prof.sources_used.append(f"github ({len(repos)} repos)")
        except SourceError as e:
            prof.notes.append(f"GitHub unavailable: {e}")

    async def do_hf() -> None:
        if not huggingface_user:
            return
        try:
            models = await huggingface.by_author(huggingface_user, kind="model")
            datasets = await huggingface.by_author(huggingface_user, kind="dataset")
            assets.extend(models + datasets)
            prof.ids["huggingface"] = huggingface_user
            prof.contact.huggingface = f"https://huggingface.co/{huggingface_user}"
            prof.sources_used.append(f"huggingface ({len(models)} models, {len(datasets)} datasets)")
        except SourceError as e:
            prof.notes.append(f"Hugging Face unavailable: {e}")

    await asyncio.gather(do_openalex(), do_arxiv(), do_github(), do_hf())

    oid = orcid_id or prof.ids.get("orcid")
    if oid:
        prof.ids["orcid"] = oid
        try:
            c = await orcid.person(oid)
            for f in ("email", "website", "github", "huggingface", "scholar", "linkedin", "orcid"):
                if getattr(c, f) and not getattr(prof.contact, f):
                    setattr(prof.contact, f, getattr(c, f))
                    prof.contact.provenance[f] = c.provenance.get(f, "orcid")
        except SourceError as e:
            prof.notes.append(f"ORCID unavailable: {e}")

    prof.assets = sorted(dedupe_assets(assets), key=lambda a: a.date or date.min, reverse=True)
    aggregate(prof)
    return prof


def save_profile(prof: Profile) -> str:
    path = settings().profiles_dir / f"{slug(prof.name)}.json"
    path.write_text(prof.model_dump_json(indent=2))
    return str(path)


def load_profile(name: str) -> Profile | None:
    path = settings().profiles_dir / f"{slug(name)}.json"
    if not path.exists():
        return None
    return Profile.model_validate_json(path.read_text())


def list_profiles() -> list[str]:
    return sorted(p.stem for p in settings().profiles_dir.glob("*.json"))


def profile_summary(prof: Profile, *, top: int = 8) -> dict:
    kinds: dict[str, int] = {}
    for a in prof.assets:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    return {
        "name": prof.name,
        "ids": prof.ids,
        "affiliation": prof.affiliation,
        "last_active": prof.last_active.isoformat() if prof.last_active else None,
        "assets": kinds,
        "top_topics": list(prof.topics)[:top],
        "top_keywords": list(prof.keywords)[:top * 2],
        "contact": {k: v for k, v in prof.contact.model_dump().items() if v and k != "provenance"},
        "sources_used": prof.sources_used,
        "notes": prof.notes,
    }
