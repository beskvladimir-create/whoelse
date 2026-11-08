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
        if any(f"{k}:{v}" in self.my_ids for k, v in p.ids.items() if v):
            return True
        if _norm_name(p.name) not in self.my_names:
            return False
        # same name: a different scholarly id proves it is a namesake, not me
        for k in ("openalex", "orcid"):
            if self.me.ids.get(k) and p.ids.get(k) and self.me.ids[k] != p.ids[k]:
                return False
        return True

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


def _idf(df: dict[str, int] | None, k: str, n_docs: int, generic: frozenset[str] | set[str] | None = None) -> float:
    """Down-weight terms that appear across many candidates (and the hard-coded generic ones)."""
    if k in (GENERIC if generic is None else generic):
        return 0.08
    if not df or n_docs <= 1:
        return 1.0
    return min(1.0, max(0.15, math.log((n_docs + 1) / (df.get(k, 0) + 1)) / math.log(n_docs + 1)))


def _weighted_overlap(
    a: dict[str, float], b: dict[str, float], *, df: dict[str, int] | None = None, n_docs: int = 0,
    generic: set[str] | None = None,
) -> tuple[float, list[str]]:
    if not a or not b:
        return 0.0, []
    shared = [k for k in a if k in b]
    w = {k: _idf(df, k, n_docs, generic) for k in set(a) | set(b)}
    # apply the weight to the mass itself, on both sides, so a generic term cannot carry the score
    aw = {k: v * w[k] for k, v in a.items()}
    bw = {k: v * w[k] for k, v in b.items()}
    num = sum(math.sqrt(aw[k] * bw[k]) for k in shared)
    den = math.sqrt(sum(aw.values()) * sum(bw.values())) or 1.0
    shared.sort(key=lambda k: -(a[k] * b[k] * w[k]))
    return num / den, shared


def score(
    me: Profile, p: Person, *, recent_months: int, df: dict[str, int] | None = None, n_docs: int = 0,
    topic_df: dict[str, int] | None = None, generic_topic_ids: set[str] | None = None,
) -> tuple[float, Overlap]:
    # Topics get the same treatment as keywords: a topic half the pool shares (OpenAlex's "Topic
    # Modeling" is a bucket, not a subject) is damped by its document frequency, and the known
    # bucket topics are damped outright, so sharing only a bucket cannot carry a candidate.
    t_score, t_shared = _weighted_overlap(me.topic_ids, p.topic_ids, df=topic_df, n_docs=n_docs, generic=generic_topic_ids or set())
    k_score, k_shared = _weighted_overlap(me.keywords, p.keywords, df=df, n_docs=n_docs)
    kid_score, _ = _weighted_overlap(me.keyword_ids, p.keyword_ids, df=df, n_docs=n_docs)
    # OpenAlex topics are coarse (a text-to-SQL paper lands in "Topic Modeling"); keywords are
    # what actually says "same problem". Free-text keywords also cover code and models.
    overlap_score = 0.25 * t_score + 0.45 * max(k_score, kid_score) + 0.30 * k_score
    measured_overlap = overlap_score
    if overlap_score == 0.0 and _from_keyword_search(p):
        # found by a query on the user's own terms (arXiv/GitHub/HF carry no OpenAlex keywords):
        # that is overlap at the level of one shared keyword, but it earns no freshness bonus,
        # or a repository pushed today outranks a relevant scientist
        overlap_score = 0.15

    my_kinds = {a.kind for a in me.assets}
    their_kinds = {a.kind for a in p.assets}
    they_have = sorted(their_kinds - my_kinds)
    you_have = sorted(my_kinds - their_kinds)
    complement = 0.1 * min(len(they_have) + len(you_have), 2)

    # Recency multiplies the overlap instead of adding to it: a fresh author off the subject
    # stays off the list; a fresh author on the subject rises above a stale one.
    recency = 0.0
    if p.last_active:
        months = (date.today() - p.last_active).days / 30.4
        recency = max(0.0, 1.0 - months / max(recent_months, 1)) * 0.5 * measured_overlap

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
    ov.measured = overlap_score > 0.0
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
    else:
        recent = sorted((a for a in p.assets if a.title), key=lambda a: a.date or date.min, reverse=True)
        if recent:
            bits.append(f"new {recent[0].kind} on your keywords: {recent[0].title[:60]}")
    if ov.they_have:
        bits.append("they have " + "/".join(ov.they_have) + " you don't")
    if p.last_active:
        bits.append(f"active {p.last_active.isoformat()}")
    if p.card:
        bits.append("publishes a whoelse card")
    if _handle_only(p):
        bits.append("account name only, may be a team or a bot")
    return "; ".join(bits) or "weak overlap"


def _reachable(p: Person) -> str:
    if p.card:
        return "card"
    if p.contact.email:
        return "email"
    if p.contact.website or p.contact.github or p.contact.linkedin or p.contact.huggingface:
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
    except SourceError as e:
        if "429" in str(e) or "403" in str(e):
            raise  # surfaced by _enrich_safe as "github search rate-limited"
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
                    p.contact.provenance["name"] = "github profile name"
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
                p.contact.provenance["name"] = "hugging face profile fullname"
    if p.contact.website:
        p.card = await card.fetch(p.contact.website)


async def _enrich_safe(p: Person, me: Profile, errors: list[str], *, lookup_github_by_name: bool) -> None:
    """One candidate's broken website must never take the whole result down."""
    try:
        await _enrich(p, me, lookup_github_by_name=lookup_github_by_name)
    except SourceError as e:
        errors.append(f"github search rate-limited while enriching {p.name}: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"enrich {p.name}: {type(e).__name__}: {e}")


def _phrases(queries: list[str]) -> list[str]:
    return [q for q in queries if " " in q.strip() or "-" in q]


def _mentions(q: str, a: Asset) -> bool:
    """The search engines are fuzzy; the hit must actually carry the phrase (every word of it) in
    its name, description or tags, so "text-to-sql" cannot return a repository about text files."""
    raw = a.title.replace("/", " ") + " " + a.summary + " " + " ".join(a.keywords)
    words = _norm_name(raw.replace("-", " ").replace("_", " ")).split()
    need = _norm_name(q.replace("-", " ")).split()
    if not need:
        return False
    n = len(need)
    return any(words[i:i + n] == need for i in range(len(words) - n + 1))   # the phrase, contiguous


def _from_keyword_search(p: Person) -> bool:
    """arXiv/GitHub/HF hits come from a keyword query on the user's own terms; that is overlap
    evidence even when the record carries no OpenAlex keywords to score against."""
    return any(a.source in ("arxiv", "github", "huggingface") for a in p.assets)


def _handle_only(p: Person) -> bool:
    """Name is still a login: nobody has claimed it as a person."""
    n = p.name.strip()
    return bool(n) and (" " not in n) and (n.lower() in {v.lower() for v in p.ids.values()})


def ov_is_coauthor(me: Profile, p: Person) -> bool:
    return any(_norm_name(c) == _norm_name(me.name) for a in p.assets for c in a.coauthors)


def _is_org(p: Person) -> bool:
    return bool(p.ids.get("github_org") or p.ids.get("huggingface_org"))


def _broken_name(p: Person) -> bool:
    """Author strings that are metadata damage, not people: digits inside the name ("2 S.K.ALISHA
    1BALAM SATHYA SANDEEP"), seven or more words, or nothing alphabetic. Logins are exempt."""
    n = p.name.strip()
    if p.ids.get("github") and not p.ids.get("openalex") and not p.ids.get("orcid"):
        return False
    if re.search(r"\d", n):
        return True
    words = _norm_name(n).split()
    return len(words) >= 7 or not words


_EMAIL_FREE = {"gmail", "googlemail", "yahoo", "outlook", "hotmail", "proton", "protonmail", "icloud", "mail", "yandex", "qq", "163", "126", "live", "me"}


def _email_domain_note(p: Person) -> str | None:
    """A public email whose domain does not match the stated affiliation is worth a second look
    before sending (a move, an old address, or a namesake). Free-mail domains say nothing."""
    if not p.contact.email or "@" not in p.contact.email or not p.affiliation:
        return None
    dom = p.contact.email.rsplit("@", 1)[1].lower()
    labels = [x for x in dom.split(".") if len(x) >= 3 and x not in ("edu", "com", "org", "net", "www")]
    if not labels or labels[0] in _EMAIL_FREE:
        return None
    aff = _aff_tokens(p.affiliation) | {t[:4] for t in _aff_tokens(p.affiliation)}
    words = [w for w in re.findall(r"[^\W\d_]+", fold(p.affiliation)) if w not in ("of", "the", "de", "and", "for", "di", "du", "der")]
    acronym = "".join(w[0] for w in words)
    if any(lab in aff or lab[:4] in aff or lab == acronym or any(lab in a or a in lab for a in aff if len(a) >= 4) for lab in labels):
        return None
    return f"email domain {dom} does not match the stated affiliation ({p.affiliation}); check before writing"


_AFF_STOP = {"university", "of", "the", "institute", "college", "school", "department", "dept", "lab", "laboratory",
             "research", "center", "centre", "technology", "science", "sciences", "and", "de", "for", "national", "state"}


def _aff_tokens(aff: str) -> set[str]:
    return {t for t in re.findall(r"[^\W\d_]{3,}", fold(aff)) if t not in _AFF_STOP}


def _title_keys(p: Person) -> set[str]:
    return {re.sub(r"\W+", " ", fold(a.title)).strip()[:80] for a in p.assets if a.kind == "paper"}


def _second_signal(keep: Person, p: Person) -> str | None:
    """A shared full name is not enough to merge two records (and hand one person's email to
    another). Require one more link between them."""
    if _title_keys(keep) & _title_keys(p):
        return "same paper"
    # The person typed their full name into their own GitHub/HF profile: that is a claim they made,
    # unlike a login that merely resembles a name. Accept it when the name is distinctive enough.
    if p.contact.provenance.get("name") and len(_norm_name(p.name).split()) >= 2 and not _common_name(p.name):
        return p.contact.provenance["name"] + " matches"
    ta, tb = _aff_tokens(keep.affiliation), _aff_tokens(p.affiliation)
    if ta and tb and (ta & tb):
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


_COMMON_FAMILY = {"wang", "li", "zhang", "liu", "chen", "yang", "huang", "zhao", "wu", "zhou", "kim", "lee", "park",
                  "nguyen", "tran", "smith", "johnson", "williams", "brown", "jones", "garcia", "martinez", "singh",
                  "kumar", "khan", "ali", "ahmed", "mohamed", "ivanov", "petrov", "muller", "schmidt", "rossi", "silva"}


def _common_name(name: str) -> bool:
    """Common family names collide too often for a profile fullname alone to merge records."""
    parts = _norm_name(name).split()
    return any(p in _COMMON_FAMILY for p in parts)


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
    keyword_queries: int = 4,
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
                        # keyed by name only; the paper's GitHub link stays on the asset and can
                        # become a second signal in _merge_by_name, never an identity by itself
                        pool.add(Person(name=name), a)
        except SourceError as e:
            errors.append(f"arxiv '{q}': {e}")

    async def code_by_query(q: str) -> None:
        try:
            for r in await github.search_repos(q, since=since, limit=30):
                owner = r.extra.get("owner", "")
                if owner and "/" in r.title and _mentions(q, r):
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
                    if author and _mentions(q, r):
                        p = Person(name=author, ids={"huggingface": author})
                        p.contact.huggingface = f"https://huggingface.co/{author}"
                        p.contact.provenance["huggingface"] = "huggingface author"
                        pool.add(p, r)
        except SourceError as e:
            errors.append(f"huggingface '{q}': {e}")

    tasks = [papers_by_keyword(k) for k in list(me.keyword_ids)[:keyword_queries + 2]]
    # Seed from the user's specific topics: a bucket topic pulls in a lab's worth of strangers who
    # share nothing but the bucket (seen live: "Topic Modeling" filling the pool with one lab).
    # The width stays (five specific topics): narrowing it to two lost the people who were only
    # reachable through the third topic, seen live on the next run. The df damping in score()
    # is what keeps buckets harmless, not a narrow seed.
    my_topic_names = {tid: name for a in me.assets for tid, name in zip(a.topic_ids, a.topics)}
    specific_topics = [t for t in me.topic_ids if my_topic_names.get(t, "") not in GENERIC_TOPICS]
    tasks += [papers_by_topic(t) for t in specific_topics[:topic_limit]]
    queries = [k for k in me.keywords if len(k) >= 5 and k not in GENERIC][:keyword_queries]
    tasks += [papers_by_query(q) for q in queries]
    # Code, model and preprint searches are literal: a single broad word ("russian", "archives")
    # returns VPN configs and archivers, not research. Only phrases of two or more words go there.
    phrases = _phrases(queries)
    tasks += [preprints_by_query(q) for q in phrases[:2]]
    if include_code:
        tasks += [code_by_query(q) for q in phrases]
    if include_models:
        tasks += [models_by_query(q) for q in phrases]
    await asyncio.gather(*tasks)

    people = list(pool.by_key.values())
    for p in people:
        p.assets = dedupe_assets(p.assets)
        aggregate(p)
    # document frequency over the candidate pool: a keyword everyone shares says nothing
    df: dict[str, int] = {}
    topic_df: dict[str, int] = {}
    generic_topic_ids: set[str] = set()
    for p in people:
        for k in set(p.keywords) | set(p.keyword_ids):
            df[k] = df.get(k, 0) + 1
        for t in set(p.topic_ids):
            topic_df[t] = topic_df.get(t, 0) + 1
        for a in p.assets:
            for tid, name in zip(a.topic_ids, a.topics):
                if name in GENERIC_TOPICS:
                    generic_topic_ids.add(tid)
    for a in me.assets:
        for tid, name in zip(a.topic_ids, a.topics):
            if name in GENERIC_TOPICS:
                generic_topic_ids.add(tid)
    n_docs = len(people)
    kw = dict(df=df, n_docs=n_docs, topic_df=topic_df, generic_topic_ids=generic_topic_ids)

    scored: list[tuple[float, Person, Overlap]] = []
    for p in people:
        s, ov = score(me, p, recent_months=recent_months, **kw)
        # a real signal is a shared keyword, a keyword-search hit, a card, or a specific (non-bucket) topic
        has_signal = bool(ov.shared_keywords) or _from_keyword_search(p) or p.card is not None
        strong_topic = any(t not in GENERIC_TOPICS for t in ov.shared_topics)
        if s > 0.05 and (has_signal or strong_topic):
            scored.append((s, p, ov))
    scored.sort(key=lambda x: -x[0])

    top = [p for _, p, _ in scored[: max(limit, enrich_top)]]
    # By-name GitHub lookups are the scarce resource (10 searches/min without a token). Spend them
    # only where they can pay off: people with a full name and no other way to reach them.
    budget = 8 if not settings().github_token else enrich_top
    eligible: set[int] = set()
    for i, p in enumerate(top[:enrich_top]):
        if lookup_github_by_name and len(_norm_name(p.name).split()) >= 2 and not p.ids.get("github") and not p.contact.github:
            if len(eligible) < budget:
                eligible.add(i)
    await asyncio.gather(*(
        _enrich_safe(p, me, errors, lookup_github_by_name=(i in eligible))
        for i, p in enumerate(top[:enrich_top])
    ))
    top = [p for p in top if not pool.is_me(p)]  # enrichment may have revealed it was the user

    # A GitHub login or HF handle that turned out to be the same human as an OpenAlex author:
    # merge now that we know their real name.
    merged = _merge_by_name(top)

    out: list[Candidate] = []
    known: list[Person] = []
    for p in merged:
        if _is_org(p) or _broken_name(p):
            continue
        if ov_is_coauthor(me, p):
            known.append(p)  # not "who else", but worth showing separately
            continue
        p.assets = dedupe_assets(p.assets)
        aggregate(p)
        s, ov = score(me, p, recent_months=recent_months, **kw)
        s += {"card": 0.2, "email": 0.05, "website": 0.02, "profile_only": 0.0}[_reachable(p)]
        if (note := _email_domain_note(p)):
            p.contact.provenance["email_note"] = note
        out.append(Candidate(person=p, score=round(s, 3), overlap=ov, why=_why(p, ov), reachable=_reachable(p)))  # type: ignore[arg-type]
    out.sort(key=lambda c: -c.score)
    return out[:limit], errors, known
