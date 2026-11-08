"""Don't build it alone: who already did, and what would it take to build it together.

Two uses, one engine:
  * find_duplicates(idea): an agent asked to "build X" calls this first and tells the user
    "X exists in N implementations; here are the best, here is what none of them has; join one,
    merge them, or build the missing part". Hundreds of hours of rebuilding the same thing stop here.
  * propose_merge(cluster): for the authors of those N implementations, a merge plan with every
    name on it and a neutral repository, delivered where each of them already reads: an issue in
    their own repository.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from .config import settings
from .http import SourceError, http
from .models import Asset
from .profile import fold
from .sources import github as gh

API = "https://api.github.com"

_STOP = {"a", "an", "the", "for", "and", "or", "of", "to", "in", "on", "with", "your", "you", "via", "from", "by", "into",
         "is", "it", "that", "this", "all", "any", "one", "tool", "tools", "app", "cli", "simple", "fast", "easy", "lightweight",
         "open", "source", "free", "local", "based", "using", "built", "made", "powered", "support", "supports", "across",
         "between", "every", "more", "etc", "like", "just", "also", "new", "best"}
# Single tokens that name a feature unambiguously. Words that also mean something else ("watch",
# "merge", "token", "memory", "hook", "drive", "remote", "test") are not here; the phrases below cover them.
_FEATURE_WORDS = {
    "encrypt": "encryption", "encrypted": "encryption", "encryption": "encryption", "e2e": "encryption", "e2ee": "encryption",
    "syncthing": "p2p sync", "lan": "LAN sync", "r2": "object storage", "obsidian": "Obsidian",
    "fts": "search", "fulltext": "search", "full-text": "search",
    "crdt": "conflict-free merge",
    "tui": "terminal UI", "dashboard": "dashboard",
    "ios": "mobile", "android": "mobile", "mobile": "mobile",
    "gdrive": "cloud drive", "icloud": "cloud drive", "dropbox": "cloud drive", "s3": "object storage", "minio": "object storage",
    "cloudflare": "cloud sync", "turso": "cloud sync", "supabase": "cloud sync", "self-hosted": "self-hosted", "selfhosted": "self-hosted",
    "ssh": "remote", "mosh": "remote", "tailscale": "remote", "wireguard": "remote",
    "backup": "backup", "backups": "backup", "restore": "backup", "rollback": "backup",
    "multi-device": "multi-device", "cross-platform": "cross-platform",
    "windows": "windows", "macos": "macos", "linux": "linux",
    "mcp": "MCP server", "plugin": "plugin", "hooks": "hooks", "skill": "skill",
    "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini", "opencode": "OpenCode", "copilot": "Copilot",
    "analytics": "analytics", "dotfiles": "config sync",
    "telegram": "messenger bridge", "wechat": "messenger bridge", "discord": "messenger bridge", "slack": "messenger bridge",
    "tests": "tests", "pytest": "tests", "ci": "CI", "docker": "docker", "homebrew": "homebrew", "npm": "npm", "pip": "pip",
}
_FEATURE_PHRASES = {
    "end to end": "encryption", "end-to-end": "encryption", "menu bar": "menu bar", "menubar": "menu bar",
    "google drive": "cloud drive", "desktop app": "desktop app", "electron": "desktop app", "tauri": "desktop app",
    "token usage": "usage tracking", "usage tracking": "usage tracking", "cost tracking": "cost tracking", "token cost": "cost tracking",
    "across machines": "multi-device", "across devices": "multi-device", "multiple machines": "multi-device", "multiple devices": "multi-device",
    "git backed": "git-backed", "git-backed": "git-backed", "git repo": "git-backed", "git repository": "git-backed", "via git": "git-backed",
    "settings sync": "config sync", "config sync": "config sync", "sync config": "config sync", "sync settings": "config sync",
    "full text search": "search", "search sessions": "search", "search history": "search", "searchable": "search",
    "github actions": "CI", "test coverage": "tests", "unit tests": "tests",
    "remote machine": "remote", "remote server": "remote",
}


_COMMON = {"sync", "machines", "machine", "sessions", "session", "code", "files", "file", "data", "manager", "management",
           "server", "client", "service", "system", "history", "across", "multiple", "devices", "device", "agent", "agents",
           "ai", "llm", "chat", "web", "api", "python", "node", "rust", "go", "app", "apps", "desktop", "mobile", "cloud",
           "working", "people", "person", "thing", "things", "same", "finds", "find", "search", "environments", "environment"}
_PRODUCTS = {"claude", "claude-code", "codex", "cursor", "gemini", "copilot", "opencode", "openclaw", "hermes", "aider", "windsurf",
             "antigravity", "obsidian", "notion", "slack", "telegram", "discord", "github", "gitlab", "vscode", "neovim", "tmux",
             "docker", "kubernetes", "chatgpt", "openai", "anthropic", "ollama", "langchain"}
_LANGS_Q = {"rust", "python", "go", "golang", "typescript", "javascript", "java", "kotlin", "swift", "ruby", "php", "c#", "csharp", "c++", "cpp", "elixir", "zig", "dart", "scala", "haskell"}
_TECH = {"mcp", "cli", "api", "sdk", "tui", "gui", "llm", "rag", "ocr", "pii", "sql", "nlp"}   # short but sharp
# the form a tool takes is not the job it does: "a plugin to back up sessions" is about backing up sessions
_FORM = {"plugin", "cli", "app", "tool", "extension", "script", "library", "package", "wrapper", "utility", "bot", "program"}
# words too weak to carry a two-word query ("claude back", "claude up")
_WEAK = {"back", "up", "code", "app", "tool", "new", "run", "make", "use", "get", "set", "own", "my"}
_NORMALISE = [("claude code", "claude-code"), ("back up", "backup"), ("back-up", "backup"), ("model context protocol", "mcp"),
              ("text to sql", "text-to-sql"), ("text2sql", "nl2sql"), ("command line", "cli"), ("command-line", "cli"),
              ("end to end", "e2e"), ("end-to-end", "e2e"), ("synchronise", "sync"), ("synchronize", "sync"),
              ("synchronisation", "sync"), ("synchronization", "sync"), ("syncing", "sync"), ("synced", "sync"), ("syncs", "sync"),
              ("anonymisation", "anonymization"), ("anonymise", "anonymize"), ("pseudonymisation", "pseudonymization"),
              ("de-identification", "deidentification"), ("de-identify", "deidentify")]
# alternative words searched and matched as the same job
_SYNONYMS = {"anonymization": ["anonymisation", "pseudonymization", "de-identification", "redaction"],
             "anonymize": ["anonymise", "anonymizer", "redact"],
             "backup": ["snapshot", "export"], "nl2sql": ["text-to-sql", "text2sql"], "text-to-sql": ["nl2sql", "text2sql"],
             "cli": ["command-line", "terminal"], "sync": ["synchronize", "synchronise", "sharing"],
             "duplicates": ["duplicate", "dedupe", "dedup"], "mcp": ["model context protocol"],
             "machines": ["devices", "computers", "hosts"], "sessions": ["conversations", "transcripts"],
             "plugin": ["extension", "addon"], "search": ["find", "query", "lookup"]}


def _normalise(text: str) -> str:
    t = fold(text)
    for a, b in _NORMALISE:
        t = t.replace(a, b)
    return t


_KEEP_S = {"sessions", "machines", "devices", "files", "costs", "tokens", "notebooks", "posts", "vaults", "images", "videos",
           "papers", "documents", "providers", "models", "repos", "repositories", "plugins", "hooks", "tests", "settings"}


def _stem(t: str) -> str:
    """Light, symmetric stemming so "costs"/"cost", "tracking"/"track", "summarizes"/"summarize" meet.
    Applied to the idea and to repository text alike, so it only has to be consistent, not correct."""
    if len(t) <= 4 or not t.isalpha():
        return t
    if t.endswith("ies") and len(t) > 5:
        return t[:-3] + "y"
    if t.endswith("ing") and len(t) > 6:
        t = t[:-3]
        return t[:-1] if len(t) > 3 and t[-1] == t[-2] and t[-1] not in "aeiou" else t
    if t.endswith("es") and t[:-2].endswith(("sh", "ch", "x", "z", "ss")):
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _tokens(text: str, *, stem: bool = True) -> list[str]:
    """Stemmed tokens for matching; unstemmed (stem=False) for search queries, which GitHub matches literally."""
    raw = [t.strip(".-+") for t in re.findall(r"[a-z0-9][a-z0-9+.-]{1,}", _normalise(text))]
    toks: list[str] = []
    for t in raw:
        toks.append(t)
        if "-" in t and t not in _PRODUCTS:
            toks.extend(p for p in t.split("-") if len(p) > 1)   # "static-site" also counts as static, site
    return [(_stem(t) if stem else t) for t in toks if t not in _STOP and len(t) > 1]


def _job_tokens(toks: list[str]) -> list[str]:
    """What the tool does, without the product it does it for. "code" after "claude" is part of the
    product name and is already folded into claude-code by _normalise."""
    return [t for t in dict.fromkeys(toks) if t not in _PRODUCTS and t not in _FORM]


_GENERIC_WORDS = {"parsing", "parse", "parser", "tracking", "track", "tracker", "convert", "converts", "converting", "converter",
                  "summarize", "summarizes", "summarizing", "summarizer", "summary", "block", "blocks", "blocking", "blocker",
                  "find", "finds", "finding", "finder", "generate", "generates", "generator", "generation", "manage", "manages", "manager",
                  "check", "checks", "checker", "monitor", "monitoring", "scan", "scanner", "build", "builder", "create", "creates",
                  "write", "writes", "read", "reads", "run", "runs", "runner", "export", "exports", "import", "imports",
                  "static", "site", "sites", "dashboard", "bot", "extension", "library", "framework", "service", "problem", "people",
                  "working", "research", "same", "across", "between", "before", "after", "sending", "send", "document", "documents"}


def _rarity(t: str) -> tuple[int, int]:
    """Sort key: rarer first. Digits or hyphens inside a word (nl2sql, crdt-sync, e2e) beat plain
    words; plain words not in the common list beat common ones; length is the last resort."""
    if re.search(r"\d", t):
        special = 0
    elif "-" in t or t in _TECH:
        special = 1
    elif t in _COMMON or t in _GENERIC_WORDS:
        special = 3
    else:
        special = 2
    return (special, -len(t))


_SYN_STEMMED: dict[str, list[set[str]]] = {}


def _syns(t: str) -> list[set[str]]:
    """Synonym token sets for a stemmed token (the table is written in plain English; stems are derived once)."""
    if not _SYN_STEMMED:
        for k, vs in _SYNONYMS.items():
            _SYN_STEMMED.setdefault(_stem(k), []).extend(set(_tokens(v)) for v in vs)
    return _SYN_STEMMED.get(t, [])


def _expand(bag: set[str]) -> set[str]:
    out = set(bag)
    for t in bag:
        for syn in _syns(t):
            out.update(syn)
    return out


def _features(repo: Asset) -> set[str]:
    text = _normalise(repo.title.split("/")[-1].replace("-", " ").replace("_", " ") + " " + repo.summary + " " + " ".join(repo.keywords))
    out = set()
    for tok in re.findall(r"[a-z0-9][a-z0-9+.-]*", text):
        if tok in _FEATURE_WORDS:
            out.add(_FEATURE_WORDS[tok])
    for phrase, feat in _FEATURE_PHRASES.items():
        if phrase in text:
            out.add(feat)
    if repo.extra.get("license"):
        out.add(f"license: {repo.extra['license']}")
    return out


def _queries_for(idea: str) -> list[str]:
    """GitHub search queries from a one-line idea: the whole sentence (GitHub ANDs the words); the
    product name with the two rarest job words; the rarest job words alone; the sentence again with
    a synonym for its rarest word. Never a two-word query whose second word is weak or short."""
    toks = _tokens(idea, stem=False)
    products = [t for t in toks if t in _PRODUCTS]
    langs = [t for t in toks if t in _LANGS_Q]
    job = [t for t in _job_tokens(toks) if t not in _LANGS_Q]
    core = sorted(job, key=_rarity)[:3]
    plain = lambda t: t.replace("-", " ") if t in _PRODUCTS else t  # noqa: E731
    qs = [" ".join(plain(t) for t in toks[:6])]
    prod = plain(products[0]) if products else ""
    if prod:
        qs += [f"{prod} {c}" for c in core[:2] if len(c) >= 4 and c not in _WEAK and c not in _COMMON]
    sharp = [c for c in core if c not in _COMMON and c not in _GENERIC_WORDS]
    if len(sharp) >= 2:
        qs.append(" ".join(sharp))
    elif len(sharp) == 1 and not prod and len(job) >= 2:
        qs.append(" ".join([sharp[0]] + [t for t in job if t != sharp[0]][:1]))
    if prod:
        # the verb or noun that names the job, with the product: "claude code sync sessions"
        verbs = [t for t in job if t in _COMMON and t not in ("across", "multiple", "machines", "machine", "devices", "device", "same", "thing", "things")][:2]
        if verbs:
            qs.append(f"{prod} {' '.join(verbs)}")
    if core and not prod and (_rarity(core[0])[0] == 0 or ("-" in core[0] and core[0] not in _TECH)):
        qs.append(core[0])   # a sharp word (nl2sql, crdt, mcp) is a query by itself
    for c in core:
        for syn in _SYNONYMS.get(c, [])[:1]:
            qs.append(" ".join(syn if t == c else plain(t) for t in toks[:6]))
    if langs and core:
        # "a Rust library for DICOM": the language is a qualifier, the rarest word is the query
        qs.append(f"{core[0]} language:{'csharp' if langs[0] == 'c#' else 'cpp' if langs[0] == 'c++' else langs[0]}")
    if prod and core:
        qs.append(f"{prod} {core[0]}")
    seen, out = set(), []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:6]


def _bag(repo: Asset) -> set[str]:
    return set(_tokens(repo.title.split("/")[-1].replace("-", " ").replace("_", " ") + " " + repo.summary + " " + " ".join(repo.keywords)))


def _similarity(job: set[str], repo: Asset) -> tuple[float, int]:
    sim, hit = _similarity_hits(job, repo)
    return sim, len(hit)


def _similarity_hits(job: set[str], repo: Asset) -> tuple[float, set[str]]:
    """Cosine-like overlap between the idea's job words and the repository's text, plus the number
    of job words matched. Product names do not count: a repository is not a duplicate of "a Claude
    Code session backup tool" for mentioning Claude Code."""
    raw = _bag(repo)
    bag = _expand(raw)
    if not bag or not job:
        return 0.0, set()
    hit = {t for t in job if t in bag or any(syn & bag for syn in _syns(t))}
    return len(hit) / math.sqrt(len(job) * len(raw)), hit


SIM_THRESHOLD = 0.3
BROAD_SEARCH = 1000   # above this many hits the first query is a field, not a duplicate cluster
_LANGS = ("python", "go", "rust", "typescript", "javascript", "shell", "swift", "c#", "java", "c", "c++", "kotlin", "dart", "ruby", "php", "elixir", "zig")


def clean_idea(idea: str) -> str:
    """The idea is typed by an agent, often lifted from a document, and may end up in public issues
    under the user's account. Control and format characters, URLs and @mentions go; 120 chars max."""
    from .network import _clean_text
    t = _clean_text(re.sub(r"\s+", " ", idea or ""))
    t = re.sub(r"https?://\S+", "", t)
    t = t.replace("@", "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:120].strip()


async def find_duplicates(idea: str, *, months: int = 24, max_stars: int | None = None, limit: int = 40) -> dict[str, Any]:
    """What already exists for this idea, as a ranked cluster, with a feature matrix."""
    from .network import _clean_text
    idea = clean_idea(idea)
    toks = _tokens(idea)
    job = set(_job_tokens(toks))
    products = {t for t in toks if t in _PRODUCTS}
    if not toks:
        raise ValueError("describe the job the tool does, in English words (GitHub search is English)")
    if not job:
        raise ValueError("the idea names a product but not a job; say what the tool does")
    # job words that must appear in a repository's text: all of them for a short idea, half for a long one
    need = len(job) if len(job) <= 3 else max(2, math.ceil(len(job) / 2))
    stale = (date.today() - timedelta(days=30 * months)).isoformat()
    found: dict[str, Asset] = {}
    errors: list[str] = []
    totals: list[int] = []
    for q in _queries_for(idea):
        try:
            assets, total = await gh.search_repos_meta(q, limit=50)
            totals.append(total)
            for r in assets:
                found.setdefault(r.title, r)
        except SourceError as e:
            errors.append(f"github '{q}': {e}")
    repos = list(found.values())
    search_total = totals[0] if totals else 0          # the whole sentence: the most specific query
    field_total = max(totals) if totals else 0         # the widest query: the size of the field
    broad = search_total > BROAD_SEARCH
    scored, excluded, related = [], [], []
    for r in repos:
        sim, bag_hit = _similarity_hits(job, r)
        matched = len(bag_hit)
        if products and not (products & _expand(_bag(r))):
            continue   # the idea is about a product; a repository that never mentions it is about something else
        if matched >= 2 or (matched == 1 and any(t in bag_hit for t in job if t not in _COMMON)):
            sharp_hit = any(t not in _COMMON and t not in _TECH and t not in _GENERIC_WORDS for t in bag_hit)
            related.append((matched + (1 if sharp_hit else 0), r, sharp_hit))
        if sim < SIM_THRESHOLD or matched < need:
            continue
        if max_stars is not None and r.stats.get("stars", 0) > max_stars:
            excluded.append(r)
            continue
        scored.append((sim, r))
    # relevance (the threshold) decides membership; stars decide order and what survives the cap,
    # because the reader wants the leader first and a 3,000-star duplicate must never fall off the list
    scored.sort(key=lambda x: (-x[1].stats.get("stars", 0), -x[0]))
    capped = len(scored) > limit
    cluster = [r for _, r in scored[:limit]]

    matrix = {r.title: sorted(_features(r)) for r in cluster}
    all_features = Counter(f for fs in matrix.values() for f in fs)
    stars = [r.stats.get("stars", 0) for r in cluster]
    leader = max(cluster, key=lambda r: r.stats.get("stars", 0)) if cluster else None
    # "nobody has": features seen in at least two related repositories (ones that share a job word
    # with the idea) but in no cluster member. From one-line descriptions, so a hint, not a census.
    wider = Counter(f for _, r, _ in related for f in _features(r))
    nobody_has = sorted((f for f, n in wider.items() if n >= 2 and f not in all_features and not f.startswith("license")),
                        key=lambda f: -wider[f]) if cluster else []
    unique = {r.title: [f for f in matrix[r.title] if all_features[f] == 1 and not f.startswith("license")] for r in cluster}
    strongest_excluded = max(excluded, key=lambda r: r.stats.get("stars", 0)) if excluded else None

    strong = [x for x in related if x[2]] or related
    top_related = max(strong, key=lambda mr: (mr[0], mr[1].stats.get("stars", 0)))[1] if related else None
    related_is_vague = bool(related) and not any(x[2] for x in related)
    stale_n = sum(1 for r in cluster if not r.date or r.date.isoformat() < stale)
    verdict = _verdict(idea, cluster, stars, leader, months=months, broad=broad, total=field_total, sentence_total=search_total,
                       errors=errors, excluded=strongest_excluded, capped=capped, related=len(related),
                       top_related=None if related_is_vague else top_related)
    return {
        "idea": idea,
        "count": len(cluster),
        "count_note": ("at least; the search returns the most-starred 50 per query" if capped or broad else None),
        "search_total": search_total if totals else None,
        "field_total": field_total if totals else None,
        "query_totals": dict(zip(_queries_for(idea), totals)),
        "broad": broad,
        "stale_count": stale_n,
        "stale_note": f"members not pushed in {months} months; the search itself has no date filter, because old and popular is still 'exists'",
        "total_stars": sum(stars),
        "median_stars": sorted(stars)[len(stars) // 2] if stars else 0,
        "median_note": "median of the matches returned, which GitHub sorts by stars; the field's real median is not higher",
        "leader": {"repo": leader.title, "url": leader.url, "stars": leader.stats.get("stars", 0), "pushed": leader.date.isoformat() if leader.date else None} if leader else None,
        "related": {"count": len(related), "count_note": "among the fetched results (50 per query); search_total says how many the field has",
                    "top": {"repo": top_related.title, "stars": top_related.stats.get("stars", 0), "url": top_related.url} if top_related else None,
                    "note": "repositories sharing part of the job with the idea, by their one-line text; the field, not the duplicates, and look-alikes are possible"},
        "excluded_by_max_stars": [{"repo": r.title, "stars": r.stats.get("stars", 0), "url": r.url} for r in sorted(excluded, key=lambda r: -r.stats.get("stars", 0))[:5]],
        "cluster": [
            {"repo": r.title, "url": r.url, "stars": r.stats.get("stars", 0), "language": next((k for k in r.keywords if k in _LANGS), ""),
             "pushed": r.date.isoformat() if r.date else None, "summary": _clean_text(r.summary)[:140], "features": matrix[r.title], "only_here": unique[r.title],
             "owner": _clean_text(r.extra.get("owner", "")), "owner_type": r.extra.get("owner_type", ""), "fork": r.extra.get("fork") == "yes",
             "archived": r.extra.get("archived") == "yes", "issues_disabled": r.extra.get("has_issues") == "no"}
            for r in cluster
        ],
        "features_anyone_has": [f for f, _ in all_features.most_common()],
        "features_nobody_has": nobody_has[:12],
        "features_note": "from each repository's one-line description and topics, not its README",
        "verdict": verdict,
        "source_errors": errors,
    }


def _verdict(idea: str, cluster: list[Asset], stars: list[int], leader: Asset | None, *, months: int, broad: bool, total: int,
             errors: list[str], excluded: Asset | None, capped: bool, related: int = 0, top_related: Asset | None = None,
             sentence_total: int = 0) -> str:

    if not cluster:
        if errors and not total and not related:
            return f"The search failed ({len(errors)} source errors; see source_errors). Nothing can be concluded about \"{idea}\"."
        tail = f" The strongest repository above max_stars was {excluded.title} ({excluded.stats.get('stars', 0)} stars)." if excluded else ""
        if top_related is not None:
            size = f"at least {total:,}" if total > related else f"{related}"
            return (f"Nothing on GitHub matches the whole of \"{idea}\" (searched without a date limit), but the field exists: {size} repositories share "
                    f"part of the job, the strongest among the fetched {top_related.title} ({top_related.stats.get('stars', 0)} stars). The combination may be new; "
                    f"the parts are not. Read the strongest before building.{tail}")
        if related:
            return (f"Nothing on GitHub matches \"{idea}\" (no date limit). {related} repositories share its general words but not its "
                    f"distinctive ones, so the specific part looks new; the general part is not. See related.{tail}")
        return (f"Nothing close to \"{idea}\" found on GitHub (no date limit). If that holds after a second search with other words "
                f"(the search is English and literal), this is new.{tail}")
    n = len(cluster)
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    def life(r: Asset) -> str:
        d = r.date.isoformat() if r.date else "unknown date"
        return f"last pushed {d}" + ("" if r.date and d >= cutoff else ", inactive")
    lead_stars = leader.stats.get("stars", 0) if leader else 0
    excl = f" {excluded.title} ({excluded.stats.get('stars', 0)} stars) was excluded by max_stars." if excluded else ""
    if broad:
        return (f"\"{idea}\" is a field, not a gap: the search for the whole sentence has {sentence_total:,} repositories. These are the {n} most "
                f"relevant among the most-starred; the top is {leader.title} ({lead_stars} stars, {life(leader)}). "
                f"Narrow the idea to the specific job and search again before concluding anything.{excl}")
    if n == 1:
        return (f"One repository does this: {leader.title} ({lead_stars} stars, {life(leader)}). Not a cluster; "
                f"contribute to it or build the part it lacks.{excl}")
    med = sorted(stars)[n // 2]
    others = sorted(r.stats.get("stars", 0) for r in cluster if r is not leader)
    med_others = others[len(others) // 2] if others else 0
    alive = [r for r in cluster if r.date and r.date.isoformat() >= cutoff and r.extra.get("archived") != "yes"]
    about = f"at least {n}" if capped else f"{n}"
    if not alive:
        return (f"\"{idea}\" exists {about} times, all inactive or archived (top {leader.title}, {lead_stars} stars, {life(leader)}). "
                f"The idea is not new; the field is open. Start from the best of them, with credit.{excl}")
    if lead_stars >= 500:
        return (f"\"{idea}\" exists: {about} implementations, and {leader.title} ({lead_stars} stars, {life(leader)}) already won. "
                f"Building another one will get the median {med} stars (median of the most-starred matches; the real one is lower). "
                f"Contribute the missing piece to {leader.title} instead, or build only what nobody has.{excl}")
    if lead_stars >= 50:
        rest = f"the other one has {med_others}" if n == 2 else f"the other {n - 1} have a median of {med_others}"
        return (f"\"{idea}\" exists {about} times. The leader is {leader.title} ({lead_stars} stars, {life(leader)}); {rest}. They have pieces the leader lacks (only_here); features_nobody_has lists what none has. "
                f"Contribute the missing piece to the leader, build only what nobody has, or propose a merge (propose_merge).{excl}")
    return (f"\"{idea}\" exists {about} times; the top has {max(stars)} stars, the median is {med}. "
            f"That is {n} people who each built the same thing and got about {med} stars for it. "
            f"The product that would win is the merge: see features_anyone_has and only_here. Propose it (propose_merge) or join the most active one.{excl}")


# ---------- the merge proposal

MAX_CLUSTER_FOR_MERGE = 15   # more than this is a bulk mailing, not a proposal; the user narrows the idea
MIN_CLUSTER_FOR_MERGE = 3
MAX_ISSUES_PER_DAY = 10      # GitHub's acceptable use forbids excessive bulk content in issues
MAX_ISSUES_PER_RUN = 10
WON_STARS = 1000             # a repository this far ahead is not "one of us"; contribute to it instead


class RateLimited(SourceError):
    """GitHub asked us to stop. The whole run stops; nothing is retried inside the tool."""


def _eligible(r: dict[str, Any], me: str | None) -> str | None:
    """Why a cluster member is not asked to merge, or None if it is."""
    if r.get("archived"):
        return "archived"
    if r.get("issues_disabled"):
        return "issues disabled"
    if r.get("fork"):
        return "a fork"
    if (r.get("owner_type") or "") == "Organization":
        return "owned by an organisation"
    if not r.get("owner"):
        return "no owner"
    if me and r["owner"].lower() == me.lower():
        return "the user's own repository"
    if r["stars"] >= WON_STARS:
        return f"{r['stars']} stars: it has won; contribute to it instead"
    if (r.get("pushed") or "") < (date.today() - timedelta(days=180)).isoformat():
        return "inactive (no push in 180 days)"
    return None


def merge_plan(dup: dict[str, Any], *, days: int = 21, plan_url: str | None = None, me: str | None = None) -> dict[str, Any]:
    """From a duplicates cluster: which repo is the base (the living leader), what each other repo
    contributes (its only_here features), who the authors are, and the text of the issue each author
    receives. Nothing is sent by this function. `plan_url` is where the plan will be readable (the
    user's repository or gist); without it the issue text carries the whole plan inline. `me` is the
    user's GitHub login, so their own repository is never asked."""
    skipped = {r["repo"]: why for r in dup["cluster"] if (why := _eligible(r, me))}
    cluster = [r for r in dup["cluster"] if r["repo"] not in skipped]
    if len(cluster) < MIN_CLUSTER_FOR_MERGE:
        raise ValueError(f"a merge proposal needs at least {MIN_CLUSTER_FOR_MERGE} living, askable repositories (found {len(cluster)}; "
                         f"skipped: {', '.join(f'{k} ({v})' for k, v in skipped.items()) or 'none'})")
    if len(cluster) > MAX_CLUSTER_FOR_MERGE:
        raise ValueError(f"{len(cluster)} repositories is a mailing, not a proposal (limit {MAX_CLUSTER_FOR_MERGE}). "
                         f"Narrow the idea to the specific job, or set max_stars, and try again.")
    stars = sorted(r["stars"] for r in cluster)
    median = stars[len(stars) // 2]
    total = sum(stars)
    # The base is the leader if it is alive (its stars and users carry over); else the most active.
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    alive = [r for r in cluster if (r["pushed"] or "") >= cutoff]
    base = max(alive or cluster, key=lambda r: (r["stars"], r["pushed"] or ""))
    base_why = "the most-starred of the ones active in the last 90 days" if alive else "the most-starred; none was pushed in the last 90 days"
    others = [r for r in cluster if r["repo"] != base["repo"]]
    authors = sorted({r["owner"] for r in cluster})
    import hashlib
    name = "merged-" + re.sub(r"[^a-z0-9]+", "-", fold(dup["idea"]))[:40].rsplit("-", 1)[0].strip("-")
    if name == "merged-":
        name += hashlib.sha1(dup["idea"].encode()).hexdigest()[:8]
    deadline = (date.today() + timedelta(days=days)).isoformat()

    def brings(r: dict[str, Any]) -> str:
        if r["only_here"]:
            return ", ".join(r["only_here"])
        return "a working implementation" if r.get("summary") else "a working implementation (no description; ask)"

    contributions = {r["repo"]: brings(r) for r in others}
    plural = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")  # noqa: E731
    plan_md = [f"# Merge plan: {dup['idea']}", "",
               f"{len(cluster)} repositories solve this. Together they have {plural(total, 'star')}; the median has {plural(median, 'star')}. "
               f"One project with all of their pieces is the one that gets used.", "",
               f"**Base:** `{base['repo']}` ({plural(base['stars'], 'star')}, last pushed {base['pushed'] or 'unknown'}; {base_why}). Nothing is deleted anywhere; every original repository stays and gets a line \"merged into {name}\" if its author wants.", "",
               "| from | brings |", "|---|---|"]
    for r in others:
        plan_md.append(f"| `{r['repo']}` | {contributions[r['repo']]} |")
    plan_md += ["", "**Authorship:** every author is a maintainer with write access from day one and is listed in README and CITATION.cff. Commits keep their authors.", "",
                f"**Deadline:** first release that does what all of them did, by {deadline}. Then the pieces nobody has: {', '.join(dup['features_nobody_has'][:5]) or 'to decide together'}.", "",
                "**How to say yes:** reply \"in\" on the issue in your repository, or open an issue in the merged repository. How to say no: ignore it.", ""]
    plan_text = "\n".join(plan_md)

    issue_title = f"{len(cluster)} of us built the same thing. Merge?"
    plan_ref = f"The plan: {plan_url}" if plan_url else "The plan is below."
    issues = []
    for r in cluster:
        peers = [o for o in cluster if o["repo"] != r["repo"]]
        shown = ", ".join(f"[{o['repo']}]({o['url']})" for o in peers[:10])
        if len(peers) > 10:
            shown += f" and {len(peers) - 10} more"
        if r["repo"] == base["repo"]:
            role = (f"Proposal: one repository with all of us as maintainers, and `{r['repo']}` as the base, because it is the most used "
                    f"and most active. The others port their pieces ({'; '.join(f'{o['repo']}: {contributions[o['repo']]}' for o in others[:6])}) with their authorship.")
        else:
            role = (f"Proposal: one repository with all of us as maintainers, `{base['repo']}` as the base ({plural(base['stars'], 'star')}), "
                    f"your piece ported with your authorship. Yours has what the others don't: **{brings(r)}**.")
        body = (f"Hi {r['owner']},\n\n"
                f"`{r['repo']}` is one of {len(cluster)} repositories that solve \"{dup['idea']}\": {shown}. "
                f"The median has {plural(median, 'star')}; none has everything.\n\n"
                f"{role} First release by {deadline}. {plan_ref}\n\n"
                f"Nothing is deleted. Your repository stays; you decide whether to point it at the merged one.\n\n"
                f"In? Reply \"in\". Not interested? Ignore this, no follow-up.\n")
        if not plan_url:
            body += "\n---\n\n" + plan_text
        issues.append({"repo": r["repo"], "owner": r["owner"], "title": issue_title, "body": body})

    return {
        "name": name,
        "base": base["repo"],
        "authors": authors,
        "contributions": contributions,
        "deadline": deadline,
        "plan_md": plan_text,
        "issues": issues,
        "skipped": skipped,
        "rules": [
            "Open one issue per repository, from the user's own GitHub account, each author sees the same plan.",
            "No issue is opened without the user's explicit yes to these exact texts; the plan_id binds the yes to them.",
            f"At most {MAX_ISSUES_PER_RUN} issues per run and {MAX_ISSUES_PER_DAY} per day, never twice to the same repository, "
            f"never to archived, forked, organisation-owned or {WON_STARS}+-star repositories or ones with issues disabled.",
            "The merged repository is created only after at least two authors said \"in\".",
        ],
    }


def _ledger_path():
    return settings().home / "issues-opened.json"


def _ledger() -> dict[str, Any]:
    import json
    p = _ledger_path()
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        return {}


def _ledger_save(d: dict[str, Any]) -> None:
    import json
    _ledger_path().parent.mkdir(parents=True, exist_ok=True)
    _ledger_path().write_text(json.dumps(d, indent=2))


_me_cache: dict[str, str] = {}


async def my_login() -> str | None:
    """The login behind GITHUB_TOKEN, so the user's own repositories are never asked."""
    tok = settings().github_token
    if not tok or settings().fixtures_dir:
        return None
    if tok in _me_cache:
        return _me_cache[tok]
    try:
        data = await http.get_json(f"{API}/user", headers=gh._headers(), fixture_name="github_me", cache_hours=1)
    except SourceError:
        return None
    login = (data or {}).get("login") if isinstance(data, dict) else None
    if login:
        _me_cache[tok] = login
    return login


def _rate_limited(r) -> bool:
    if r.status_code == 429:
        return True
    if r.status_code != 403:
        return False
    if r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Remaining") == "0":
        return True
    t = r.text.lower()
    return "rate limit" in t or "abuse" in t


async def open_issue(owner: str, repo: str, title: str, body: str, *, me: str | None = None) -> dict[str, Any]:
    """Open an issue with the user's token. Only called after the user said yes to this exact text.
    Keeps a local ledger so the same repository is never asked twice and the daily cap holds across
    runs. Raises RateLimited when GitHub says stop; the caller ends the run."""
    import httpx
    if settings().fixtures_dir:
        raise SourceError("offline mode; issue not opened")
    if not settings().github_token:
        raise SourceError("no GITHUB_TOKEN; issue not opened")
    led = _ledger()
    key = f"{owner}/{repo}"
    if key in led:
        raise SourceError(f"already asked {key} on {led[key]['date']}: {led[key]['issue']}")
    today = date.today().isoformat()
    if sum(1 for v in led.values() if v.get("date") == today) >= MAX_ISSUES_PER_DAY:
        raise SourceError(f"daily cap of {MAX_ISSUES_PER_DAY} issues reached; continue tomorrow")
    client = await http._get_client()
    h = gh._headers()
    try:
        meta = await client.get(f"{API}/repos/{owner}/{repo}", headers=h)
        if _rate_limited(meta):
            raise RateLimited("GitHub rate limit while reading the repository; run stopped")
        if meta.status_code == 404:
            raise SourceError(f"{key}: not found (private, renamed or gone)")
        if meta.status_code == 200:
            m = meta.json()
            if m.get("archived"):
                raise SourceError(f"{key} is archived")
            if m.get("has_issues") is False:
                raise SourceError(f"{key} has issues disabled")
            if m.get("fork"):
                raise SourceError(f"{key} is a fork")
            if ((m.get("owner") or {}).get("type") or "") == "Organization":
                raise SourceError(f"{key} is owned by an organisation")
        # never a second issue where the user already opened one (open or closed), nor a duplicate title
        params: dict[str, Any] = {"state": "all", "per_page": 100}
        if me:
            params["creator"] = me
        existing = await client.get(f"{API}/repos/{owner}/{repo}/issues", headers=h, params=params)
        if existing.status_code == 200:
            items = [i for i in existing.json() if isinstance(i, dict) and "pull_request" not in i]
            if me and items:
                raise SourceError(f"{key}: the user already has an issue there ({items[0].get('html_url')})")
            if any((i.get("title") or "") == title for i in items):
                raise SourceError(f"{key} already has an issue with this title")
        r = await client.post(f"{API}/repos/{owner}/{repo}/issues", headers=h, json={"title": title, "body": body})
    except httpx.HTTPError as e:
        raise SourceError(f"github: {e}")
    if _rate_limited(r):
        raise RateLimited(f"GitHub rate limit (HTTP {r.status_code}); run stopped, nothing retried")
    if r.status_code == 401:
        raise RateLimited("GITHUB_TOKEN rejected (401); run stopped")
    if r.status_code in (403, 404, 410):
        raise SourceError(f"{key}: cannot open issues there (HTTP {r.status_code}: blocked, interaction limits or issues restricted)")
    if r.status_code == 422:
        try:
            detail = "; ".join(str(e.get("message") or e.get("code")) for e in r.json().get("errors", []))
        except ValueError:
            detail = r.text[:120]
        raise SourceError(f"{key}: GitHub rejected the issue (422: {detail})")
    if r.status_code != 201:
        raise SourceError(f"issue failed: HTTP {r.status_code} {r.text[:160]}")
    url = r.json().get("html_url")
    led = _ledger()
    led[key] = {"date": today, "issue": url}
    _ledger_save(led)
    return {"issue": url}
