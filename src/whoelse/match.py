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
from .profile import aggregate, dedupe_assets, fold
from .sources import arxiv, card, github, huggingface, openalex, orcid


def _norm_name(n: str) -> str:
    n = re.sub(r"[^\w\s]", " ", fold(n), flags=re.UNICODE)
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
        self.my_ids = {f"{k}:{v}" for k, v in me.ids.items() if v} | {
            f"github:{github.login_from_url(me.contact.github)}" if me.contact.github else "",
            f"huggingface:{me.ids.get('huggingface', '')}",
        }

    def is_me(self, p: Person) -> bool:
        if _norm_name(p.name) in self.my_names:
            return True
        return any(f"{k}:{v}" in self.my_ids for k, v in p.ids.items() if v)

    def _key(self, p: Person) -> str:
        for k in ("openalex", "github", "orcid", "huggingface"):
            if p.ids.get(k):
                return f"{k}:{p.ids[k]}"
        return f"name:{_norm_name(p.name)}"

    def add(self, p: Person, asset: Asset) -> None:
        if self.is_me(p):
            return
        key = self._key(p)
        cur = self.by_key.get(key)
        if cur is None:
            p.assets = [asset]
            self.by_key[key] = p
        else:
            cur.assets.append(asset)
            if not cur.affiliation and p.affiliation:
                cur.affiliation = p.affiliation
            cur.ids.update({k: v for k, v in p.ids.items() if k not in cur.ids})


# Keywords that describe a whole field rather than a problem. Sharing them means little.
GENERIC = {
    "large language models", "large language model", "llm", "llms", "deep learning", "machine learning",
    "artificial intelligence", "natural language processing", "nlp", "neural networks", "transformers",
    "benchmark", "evaluation", "dataset", "survey", "python",
    "keywords/large-language-models", "keywords/deep-learning", "keywords/machine-learning",
    "keywords/artificial-intelligence", "keywords/natural-language-processing", "keywords/benchmark",
}


def _idf(df: dict[str, int] | None, k: str, n_docs: int) -> float:
    """Down-weight terms that appear across many candidates (and the hard-coded generic ones)."""
    if k in GENERIC:
        return 0.08
    if not df or n_docs <= 1:
        return 1.0
    return min(1.0, max(0.15, math.log((n_docs + 1) / (df.get(k, 0) + 1)) / math.log(n_docs + 1)))


def _weighted_overlap(
    a: dict[str, float], b: dict[str, float], *, df: dict[str, int] | None = None, n_docs: int = 0
) -> tuple[float, list[str]]:
    if not a or not b:
        return 0.0, []
    shared = [k for k in a if k in b]
    w = {k: _idf(df, k, n_docs) for k in set(a) | set(b)}
    # apply the weight to the mass itself, on both sides, so a generic term cannot carry the score
    aw = {k: v * w[k] for k, v in a.items()}
    bw = {k: v * w[k] for k, v in b.items()}
    num = sum(math.sqrt(aw[k] * bw[k]) for k in shared)
    den = math.sqrt(sum(aw.values()) * sum(bw.values())) or 1.0
    shared.sort(key=lambda k: -(a[k] * b[k] * w[k]))
    return num / den, shared


def score(
    me: Profile, p: Person, *, recent_months: int, df: dict[str, int] | None = None, n_docs: int = 0
) -> tuple[float, Overlap]:
    t_score, t_shared = _weighted_overlap(me.topic_ids, p.topic_ids)
    k_score, k_shared = _weighted_overlap(me.keywords, p.keywords, df=df, n_docs=n_docs)
    kid_score, _ = _weighted_overlap(me.keyword_ids, p.keyword_ids, df=df, n_docs=n_docs)
    # OpenAlex topics are coarse (a text-to-SQL paper lands in "Topic Modeling"); keywords are
    # what actually says "same problem". Free-text keywords also cover code and models.
    overlap_score = 0.25 * t_score + 0.45 * max(k_score, kid_score) + 0.30 * k_score

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
    named = [topic_names.get(t, t) for t in t_shared[:6]]
    named.sort(key=lambda n: n in GENERIC_TOPICS)
    ov = Overlap(
        shared_topics=named[:5],
        shared_keywords=k_shared[:8],
        they_have=they_have,
        you_have=you_have,
        already_coauthors=already,
    )
    return max(0.0, overlap_score + complement + recency - penalty), ov


GENERIC_TOPICS = {"Large Language Models and Applications", "Topic Modeling", "Natural Language Processing Techniques",
                  "Machine Learning in Healthcare", "Software Engineering Research"}


def _why(p: Person, ov: Overlap) -> str:
    bits = []
    specific_kw = [k for k in ov.shared_keywords if k not in GENERIC][:3]
    specific_topics = [t for t in ov.shared_topics if t not in GENERIC_TOPICS][:2]
    if specific_kw:
        bits.append("same problem: " + ", ".join(specific_kw))
    elif specific_topics:
        bits.append("same topic: " + ", ".join(specific_topics))
    elif ov.shared_topics:
        bits.append("same field: " + ov.shared_topics[0])
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


def _repos_confirm(repos: list[Asset], me: Profile, p: Person) -> bool:
    """A GitHub account found by name is the same human only if its repos touch the same subject."""
    mine = set(me.keywords) | set(k for a in me.assets for k in a.keywords)
    theirs = set(p.keywords) | set(k for a in p.assets for k in a.keywords)
    wanted = {k for k in (mine | theirs) if k not in GENERIC and len(k) > 3}
    for r in repos:
        text = (r.title + " " + r.summary + " " + " ".join(r.keywords)).lower()
        if any(k in text for k in wanted):
            return True
    return False


async def _github_by_name(p: Person, me: Profile) -> None:
    """Many researchers never put GitHub on ORCID, but their GitHub profile carries a site or
    email. Search by full name; accept only a unique hit whose repos confirm the subject."""
    if p.ids.get("github") or p.contact.github or len(_norm_name(p.name).split()) < 2:
        return
    try:
        hits = await github.search_users(p.name)
    except SourceError:
        return
    if len(hits) != 1:
        return  # 0 = not there; >1 = namesakes, not worth the risk
    login = hits[0]
    try:
        repos = await github.user_repos(login, limit=30)
    except SourceError:
        return
    if not _repos_confirm(repos, me, p):
        return
    p.ids["github"] = login
    p.contact.github = f"https://github.com/{login}"
    p.contact.provenance["github"] = "github user search by full name, confirmed by repo subject"
    p.assets.extend(repos[:10])


async def _enrich(p: Person, me: Profile | None = None, *, lookup_github_by_name: bool = True) -> None:
    """Add public contacts for one person. Each step is best-effort."""
    if me is not None and lookup_github_by_name:
        await _github_by_name(p, me)
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
    gh = p.ids.get("github") or github.login_from_url(p.contact.github)
    if gh:
        try:
            u = await github.user(gh)
            if u and u.ids.get("github_org"):
                p.ids["github_org"] = gh
                p.ids.pop("github", None)
                p.contact.github = None
                p.contact.provenance.pop("github", None)
            elif u:
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
    hf = p.ids.get("huggingface")
    if hf and p.name.lower() == hf.lower():
        ov = await huggingface.user_overview(hf)
        if ov:
            if (ov.get("type") or "").lower() == "org":
                p.ids["huggingface_org"] = hf
            elif ov.get("fullname") and len(str(ov["fullname"]).split()) >= 2:
                p.name = str(ov["fullname"])
    if p.contact.website:
        p.card = await card.fetch(p.contact.website)


async def _enrich_safe(p: Person, me: Profile, errors: list[str], *, lookup_github_by_name: bool) -> None:
    """One candidate's broken website must never take the whole result down."""
    try:
        await _enrich(p, me, lookup_github_by_name=lookup_github_by_name)
    except Exception as e:  # noqa: BLE001
        errors.append(f"enrich {p.name}: {type(e).__name__}: {e}")


def ov_is_coauthor(me: Profile, p: Person) -> bool:
    return any(_norm_name(c) == _norm_name(me.name) for a in p.assets for c in a.coauthors)


def _is_org(p: Person) -> bool:
    return bool(p.ids.get("github_org") or p.ids.get("huggingface_org"))


def _second_signal(keep: Person, p: Person) -> str | None:
    """A shared full name is not enough to merge two records (and hand one person's email to
    another). Require one more link between them."""
    a, b = keep.affiliation.lower(), p.affiliation.lower()
    if a and b and (a in b or b in a):
        return "same affiliation"
    gh = p.ids.get("github") or github.login_from_url(p.contact.github)
    if gh:
        if keep.contact.github and github.login_from_url(keep.contact.github) == gh:
            return "orcid/profile links to this github"
        handles = {h for a_ in keep.assets for h in a_.extra.get("github_handles", "").split(",") if h}
        if gh in handles:
            return "their paper links to this github"
    hf = p.ids.get("huggingface")
    if hf:
        handles = {h for a_ in keep.assets for h in a_.extra.get("hf_handles", "").split(",") if h}
        if hf in handles:
            return "their paper links to this hugging face account"
    if keep.contact.website and p.contact.website and _host(keep.contact.website) == _host(p.contact.website):
        return "same website"
    return None


def _host(u: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(u if "://" in u else "https://" + u).netloc.lower().removeprefix("www.")


def _merge_by_name(people: list[Person]) -> list[Person]:
    """Merge records that share a full name AND a second signal (affiliation, a link from one to
    the other, same site). Name alone keeps them separate, marked as possible namesakes."""
    def rank(p: Person) -> int:
        return (2 if p.ids.get("openalex") else 0) + (1 if p.ids.get("orcid") else 0)

    by_name: dict[str, Person] = {}
    out: list[Person] = []
    for p in sorted(people, key=rank, reverse=True):
        n = _norm_name(p.name)
        if len(n.split()) >= 2 and n in by_name and (sig := _second_signal(by_name[n], p)):
            keep = by_name[n]
            keep.contact.provenance["merge"] = sig
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
            if n in by_name:
                p.contact.provenance["namesake_of"] = by_name[n].name
            else:
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
    lookup_github_by_name: bool = True,
) -> tuple[list[Candidate], list[str], list[Person]]:
    """Returns (candidates, source_errors, people_you_already_publish_with)."""
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

    async def papers_by_keyword(kid: str) -> None:
        try:
            for w in await openalex.works_by_keyword(kid, since=since, limit=100):
                asset = openalex.work_to_asset(w)
                for a in (w.get("authorships") or []):
                    p = openalex.authorship_to_person(a)
                    if p:
                        pool.add(p, asset)
        except SourceError as e:
            errors.append(f"openalex keyword {kid}: {e}")

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

    async def preprints_by_query(q: str) -> None:
        """arXiv is days ahead of OpenAlex for brand-new work. Authors there have no ids, so a
        person is keyed by name and merged later only with a second signal."""
        try:
            for a in await arxiv.by_keywords([q], max_results=40):
                if not a.date or a.date < since:
                    continue
                for name in a.coauthors[:6]:
                    if name and len(name.split()) >= 2:
                        p = Person(name=name)
                        for h in filter(None, a.extra.get("github_handles", "").split(",")):
                            p.ids.setdefault("github", h)
                            p.contact.github = f"https://github.com/{h}"
                            p.contact.provenance["github"] = "linked from their arXiv paper"
                        pool.add(p, a)
        except SourceError as e:
            errors.append(f"arxiv '{q}': {e}")

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

    tasks = [papers_by_keyword(k) for k in list(me.keyword_ids)[:keyword_queries + 2]]
    tasks += [papers_by_topic(t) for t in list(me.topic_ids)[:topic_limit]]
    queries = [k for k in me.keywords if len(k) >= 5 and k not in GENERIC][:keyword_queries]
    tasks += [papers_by_query(q) for q in queries]
    tasks += [preprints_by_query(q) for q in queries[:2]]
    if include_code:
        tasks += [code_by_query(q) for q in queries]
    if include_models:
        tasks += [models_by_query(q) for q in queries]
    await asyncio.gather(*tasks)

    people = list(pool.by_key.values())
    for p in people:
        p.assets = dedupe_assets(p.assets)
        aggregate(p)
    # document frequency over the candidate pool: a keyword everyone shares says nothing
    df: dict[str, int] = {}
    for p in people:
        for k in set(p.keywords) | set(p.keyword_ids):
            df[k] = df.get(k, 0) + 1
    n_docs = len(people)

    scored: list[tuple[float, Person, Overlap]] = []
    for p in people:
        s, ov = score(me, p, recent_months=recent_months, df=df, n_docs=n_docs)
        if s > 0.02:
            scored.append((s, p, ov))
    scored.sort(key=lambda x: -x[0])

    top = [p for _, p, _ in scored[: max(limit, enrich_top)]]
    await asyncio.gather(*(_enrich_safe(p, me, errors, lookup_github_by_name=lookup_github_by_name) for p in top[:enrich_top]))
    top = [p for p in top if not pool.is_me(p)]  # enrichment may have revealed it was the user

    # A GitHub login or HF handle that turned out to be the same human as an OpenAlex author:
    # merge now that we know their real name.
    merged = _merge_by_name(top)

    out: list[Candidate] = []
    known: list[Person] = []
    for p in merged:
        if _is_org(p):
            continue
        if ov_is_coauthor(me, p):
            known.append(p)  # not "who else", but worth showing separately
            continue
        p.assets = dedupe_assets(p.assets)
        aggregate(p)
        s, ov = score(me, p, recent_months=recent_months, df=df, n_docs=n_docs)
        s += {"card": 0.2, "email": 0.05, "website": 0.02, "profile_only": 0.0}[_reachable(p)]
        out.append(Candidate(person=p, score=round(s, 3), overlap=ov, why=_why(p, ov), reachable=_reachable(p)))  # type: ignore[arg-type]
    out.sort(key=lambda c: -c.score)
    return out[:limit], errors, known
