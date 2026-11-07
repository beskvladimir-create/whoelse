"""Find the people whose current work overlaps yours, and say why.

Discovery walks three directions at once:
  papers  — OpenAlex works on your top topics (last N months), plus a keyword search
  code    — GitHub repositories matching your keywords, recently pushed
  models  — Hugging Face models/datasets matching your keywords
Then it merges people across sources, scores overlap, and enriches the top of the list with
whatever contact the person made public (ORCID, GitHub profile, their own site, a whoelse card).
"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import date, timedelta

from .config import settings
from .http import SourceError
from .models import Asset, Candidate, Overlap, Person, Profile
from .profile import aggregate, dedupe_assets
from .sources import card, github, huggingface, openalex, orcid


def _norm_name(n: str) -> str:
    n = re.sub(r"[^\w\s]", " ", n.lower())
    parts = [p for p in n.split() if len(p) > 1]
    return " ".join(parts)


def _same_person(a: str, b: str) -> bool:
    return _norm_name(a) == _norm_name(b)


class _Pool:
    """People found so far, merged by stable ids, then by exact name."""

    def __init__(self, me: Profile) -> None:
        self.me = me
        self.by_key: dict[str, Person] = {}
        self.my_names = {_norm_name(me.name)}
        self.my_coauthors = {_norm_name(c) for a in me.assets for c in a.coauthors if c}

    def _key(self, p: Person) -> str:
        for k in ("openalex", "github", "orcid", "huggingface"):
            if p.ids.get(k):
                return f"{k}:{p.ids[k]}"
        return f"name:{_norm_name(p.name)}"

    def add(self, p: Person, asset: Asset) -> None:
        if _norm_name(p.name) in self.my_names:
            return
        key = self._key(p)
        # name-level merge: a GitHub owner and an OpenAlex author with the same full name
        if key.startswith(("github:", "huggingface:")):
            for existing in self.by_key.values():
                if _same_person(existing.name, p.name) and len(p.name.split()) >= 2:
                    existing.ids.update({k: v for k, v in p.ids.items() if k not in existing.ids})
                    for f in ("github", "huggingface", "website", "email"):
                        if getattr(p.contact, f) and not getattr(existing.contact, f):
                            setattr(existing.contact, f, getattr(p.contact, f))
                            existing.contact.provenance[f] = p.contact.provenance.get(f, "")
                    existing.assets.append(asset)
                    return
        cur = self.by_key.get(key)
        if cur is None:
            p.assets = [asset]
            self.by_key[key] = p
        else:
            cur.assets.append(asset)
            if not cur.affiliation and p.affiliation:
                cur.affiliation = p.affiliation
            cur.ids.update({k: v for k, v in p.ids.items() if k not in cur.ids})


def _weighted_overlap(a: dict[str, float], b: dict[str, float]) -> tuple[float, list[str]]:
    if not a or not b:
        return 0.0, []
    shared = [k for k in a if k in b]
    num = sum(math.sqrt(a[k] * b[k]) for k in shared)
    den = math.sqrt(sum(a.values()) * sum(b.values())) or 1.0
    shared.sort(key=lambda k: -(a[k] * b[k]))
    return num / den, shared


def score(me: Profile, p: Person, *, recent_months: int) -> tuple[float, Overlap]:
    t_score, t_shared = _weighted_overlap(me.topic_ids, p.topic_ids)
    k_score, k_shared = _weighted_overlap(me.keywords, p.keywords)
    # topics are curated; keywords are noisier but cover code and models
    overlap_score = 0.65 * t_score + 0.35 * k_score

    my_kinds = {a.kind for a in me.assets}
    their_kinds = {a.kind for a in p.assets}
    they_have = sorted(their_kinds - my_kinds)
    you_have = sorted(my_kinds - their_kinds)
    complement = 0.1 * min(len(they_have) + len(you_have), 2)

    recency = 0.0
    if p.last_active:
        months = (date.today() - p.last_active).days / 30.4
        recency = max(0.0, 1.0 - months / max(recent_months, 1)) * 0.2

    already = any(_norm_name(c) == _norm_name(me.name) for a in p.assets for c in a.coauthors)
    penalty = 0.5 if already else 0.0

    topic_names = {tid: name for a in p.assets for tid, name in zip(a.topic_ids, a.topics)}
    ov = Overlap(
        shared_topics=[topic_names.get(t, t) for t in t_shared[:5]],
        shared_keywords=k_shared[:8],
        they_have=they_have,
        you_have=you_have,
        already_coauthors=already,
    )
    return max(0.0, overlap_score + complement + recency - penalty), ov


def _why(p: Person, ov: Overlap) -> str:
    bits = []
    if ov.shared_topics:
        bits.append("same topic: " + ", ".join(ov.shared_topics[:2]))
    elif ov.shared_keywords:
        bits.append("same keywords: " + ", ".join(ov.shared_keywords[:3]))
    if ov.they_have:
        bits.append("they have " + "/".join(ov.they_have) + " you don't")
    if p.last_active:
        bits.append(f"active {p.last_active.isoformat()}")
    if p.card:
        bits.append("publishes a whoelse card")
    return "; ".join(bits) or "weak overlap"


def _reachable(p: Person) -> str:
    if p.card:
        return "card"
    if p.contact.email:
        return "email"
    if p.contact.website or p.contact.github or p.contact.linkedin:
        return "website"
    return "profile_only"


async def _enrich(p: Person) -> None:
    """Add public contacts for one person. Each step is best-effort."""
    oid = p.ids.get("orcid")
    if oid:
        try:
            c = await orcid.person(oid)
            for f in ("email", "website", "github", "huggingface", "scholar", "linkedin"):
                if getattr(c, f) and not getattr(p.contact, f):
                    setattr(p.contact, f, getattr(c, f))
                    p.contact.provenance[f] = c.provenance.get(f, "orcid")
            p.contact.orcid = c.orcid
        except SourceError:
            pass
    gh = p.ids.get("github") or (p.contact.github or "").rstrip("/").rsplit("/", 1)[-1] if p.contact.github else None
    if gh:
        try:
            u = await github.user(gh)
            if u:
                p.ids.setdefault("github", gh)
                if u.name and u.name.lower() != gh.lower() and p.name.lower() == gh.lower():
                    p.name = u.name  # a handle became a person
                for f in ("email", "website"):
                    if getattr(u.contact, f) and not getattr(p.contact, f):
                        setattr(p.contact, f, getattr(u.contact, f))
                        p.contact.provenance[f] = u.contact.provenance.get(f, "github")
                p.contact.github = u.contact.github
                if not p.affiliation and u.affiliation:
                    p.affiliation = u.affiliation
        except SourceError:
            pass
    if p.contact.website:
        p.card = await card.fetch(p.contact.website)


def _merge_by_name(people: list[Person]) -> list[Person]:
    """Merge persons that share a full name (>= 2 words) once enrichment revealed real names.
    The one with scholarly ids is kept; code/model handles fold into it."""
    def rank(p: Person) -> int:
        return (2 if p.ids.get("openalex") else 0) + (1 if p.ids.get("orcid") else 0)

    by_name: dict[str, Person] = {}
    out: list[Person] = []
    for p in sorted(people, key=rank, reverse=True):
        n = _norm_name(p.name)
        if len(n.split()) >= 2 and n in by_name:
            keep = by_name[n]
            keep.assets.extend(p.assets)
            keep.ids.update({k: v for k, v in p.ids.items() if k not in keep.ids})
            for f in ("email", "website", "github", "huggingface", "scholar", "linkedin", "orcid"):
                if getattr(p.contact, f) and not getattr(keep.contact, f):
                    setattr(keep.contact, f, getattr(p.contact, f))
                    keep.contact.provenance[f] = p.contact.provenance.get(f, "")
            if p.card and not keep.card:
                keep.card = p.card
            if not keep.affiliation and p.affiliation:
                keep.affiliation = p.affiliation
            continue
        if len(n.split()) >= 2:
            by_name[n] = p
        out.append(p)
    return out


async def find_overlaps(
    me: Profile,
    *,
    limit: int = 20,
    recent_months: int | None = None,
    include_code: bool = True,
    include_models: bool = True,
    enrich_top: int = 30,
    topic_limit: int = 5,
    keyword_queries: int = 3,
) -> list[Candidate]:
    recent_months = recent_months or settings().recent_months
    since = date.today() - timedelta(days=30 * recent_months)
    pool = _Pool(me)
    errors: list[str] = []

    async def papers_by_topic(tid: str) -> None:
        try:
            for w in await openalex.works_by_topic(tid, since=since, limit=100):
                asset = openalex.work_to_asset(w)
                for a in (w.get("authorships") or []):
                    p = openalex.authorship_to_person(a)
                    if p:
                        pool.add(p, asset)
        except SourceError as e:
            errors.append(f"openalex topic {tid}: {e}")

    async def papers_by_query(q: str) -> None:
        try:
            for w in await openalex.works_search(q, since=since, limit=50):
                asset = openalex.work_to_asset(w)
                for a in (w.get("authorships") or []):
                    p = openalex.authorship_to_person(a)
                    if p:
                        pool.add(p, asset)
        except SourceError as e:
            errors.append(f"openalex search '{q}': {e}")

    async def code_by_query(q: str) -> None:
        try:
            for r in await github.search_repos(q, since=since, limit=30):
                owner = r.extra.get("owner", "")
                if owner and "/" in r.title:
                    p = Person(name=owner, ids={"github": owner})
                    p.contact.github = f"https://github.com/{owner}"
                    p.contact.provenance["github"] = "github repo owner"
                    pool.add(p, r)
        except SourceError as e:
            errors.append(f"github '{q}': {e}")

    async def models_by_query(q: str) -> None:
        try:
            for kind in ("model", "dataset"):
                for r in await huggingface.search(q, kind=kind, limit=30):
                    author = r.extra.get("author", "")
                    if author:
                        p = Person(name=author, ids={"huggingface": author})
                        p.contact.huggingface = f"https://huggingface.co/{author}"
                        p.contact.provenance["huggingface"] = "huggingface author"
                        pool.add(p, r)
        except SourceError as e:
            errors.append(f"huggingface '{q}': {e}")

    tasks = [papers_by_topic(t) for t in list(me.topic_ids)[:topic_limit]]
    queries = list(me.keywords)[:keyword_queries]
    tasks += [papers_by_query(q) for q in queries]
    if include_code:
        tasks += [code_by_query(q) for q in queries]
    if include_models:
        tasks += [models_by_query(q) for q in queries]
    await asyncio.gather(*tasks)

    scored: list[tuple[float, Person, Overlap]] = []
    for p in pool.by_key.values():
        p.assets = dedupe_assets(p.assets)
        aggregate(p)
        s, ov = score(me, p, recent_months=recent_months)
        if s > 0.02:
            scored.append((s, p, ov))
    scored.sort(key=lambda x: -x[0])

    top = [p for _, p, _ in scored[: max(limit, enrich_top)]]
    await asyncio.gather(*(_enrich(p) for p in top[:enrich_top]))

    # A GitHub login or HF handle that turned out to be the same human as an OpenAlex author:
    # merge now that we know their real name.
    merged = _merge_by_name(top)

    out: list[Candidate] = []
    for p in merged:
        p.assets = dedupe_assets(p.assets)
        aggregate(p)
        s, ov = score(me, p, recent_months=recent_months)
        s += {"card": 0.2, "email": 0.05, "website": 0.02, "profile_only": 0.0}[_reachable(p)]
        out.append(Candidate(person=p, score=round(s, 3), overlap=ov, why=_why(p, ov), reachable=_reachable(p)))  # type: ignore[arg-type]
    out.sort(key=lambda c: -c.score)
    out = out[:limit]
    if errors:
        # attach as a note on the first candidate's person? No: surface via a side channel.
        find_overlaps.last_errors = errors  # type: ignore[attr-defined]
    else:
        find_overlaps.last_errors = []  # type: ignore[attr-defined]
    return out


find_overlaps.last_errors = []  # type: ignore[attr-defined]
