"""Before you build it: who already did, and what would it take to build it together.

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
_FEATURE_WORDS = {
    "encrypt": "encryption", "encrypted": "encryption", "encryption": "encryption", "e2e": "encryption", "end-to-end": "encryption",
    "syncthing": "p2p sync", "lan": "LAN sync", "r2": "object storage", "obsidian": "Obsidian",
    "search": "search", "fts": "search", "full-text": "search",
    "crdt": "conflict-free merge", "merge": "merge",
    "tui": "terminal UI", "dashboard": "dashboard", "desktop": "desktop app", "menu": "menu bar", "widget": "desktop app",
    "ios": "mobile", "android": "mobile", "watch": "wearable", "mobile": "mobile",
    "git": "git-backed", "github": "git-backed", "drive": "cloud drive", "icloud": "cloud drive", "s3": "object storage",
    "cloudflare": "cloud sync", "turso": "cloud sync", "self-hosted": "self-hosted", "backend": "self-hosted",
    "ssh": "remote", "mosh": "remote", "tailscale": "remote", "remote": "remote",
    "backup": "backup", "restore": "backup", "rollback": "backup",
    "multi-device": "multi-device", "machines": "multi-device", "devices": "multi-device", "cross-platform": "cross-platform",
    "windows": "windows", "macos": "macos", "linux": "linux",
    "mcp": "MCP server", "plugin": "plugin", "hook": "hooks", "hooks": "hooks", "skill": "skill",
    "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini", "opencode": "OpenCode", "copilot": "Copilot",
    "token": "token tracking", "cost": "cost tracking", "usage": "usage tracking", "analytics": "analytics",
    "memory": "memory", "config": "config sync", "settings": "config sync", "dotfiles": "config sync",
    "telegram": "messenger bridge", "wechat": "messenger bridge", "discord": "messenger bridge", "slack": "messenger bridge",
    "tests": "tests", "test": "tests", "ci": "CI", "docker": "docker", "homebrew": "homebrew", "npm": "npm", "pip": "pip",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9+.-]{1,}", fold(text)) if t not in _STOP and len(t) > 1]


def _features(repo: Asset) -> set[str]:
    text = fold(repo.title.split("/")[-1] + " " + repo.summary + " " + " ".join(repo.keywords))
    out = set()
    for tok in re.findall(r"[a-z0-9][a-z0-9+.-]*", text):
        if tok in _FEATURE_WORDS:
            out.add(_FEATURE_WORDS[tok])
    if repo.extra.get("license"):
        out.add(f"license: {repo.extra['license']}")
    return out


_COMMON = {"sync", "machines", "machine", "sessions", "session", "code", "files", "file", "data", "manager", "management",
           "server", "client", "service", "system", "history", "across", "multiple", "devices", "device", "agent", "agents",
           "ai", "llm", "chat", "web", "api", "python", "node", "rust", "go", "app", "apps", "desktop", "mobile", "cloud"}
_PRODUCTS = {"claude", "codex", "cursor", "gemini", "copilot", "opencode", "openclaw", "hermes", "aider", "windsurf", "antigravity",
             "obsidian", "notion", "slack", "telegram", "discord", "github", "gitlab", "vscode", "neovim", "tmux", "docker", "kubernetes"}


def _queries_for(idea: str) -> list[str]:
    """GitHub search queries from a one-line idea: the whole sentence (GitHub ANDs the words), then
    the product name with each distinctive word, then the distinctive words alone. Distinctive =
    hyphenated or product names or not in the common-word list."""
    toks = _tokens(idea)
    products = [t for t in toks if t in _PRODUCTS]
    distinctive = [t for t in toks if (t in _PRODUCTS or "-" in t or t not in _COMMON)]
    # the two most informative non-product words: longest first, then original order
    core = [t for t in distinctive if t not in _PRODUCTS]
    core = sorted(dict.fromkeys(core), key=lambda t: -len(t))[:2]
    qs = [" ".join(toks[:6])]
    if products:
        qs += [f"{products[0]} {c}" for c in core]
        # the verb/noun that names the job, with the product: "claude sync sessions"
        job = [t for t in toks if t in _COMMON and t not in ("across", "multiple", "code", "machines", "machine", "devices", "device")][:2]
        if job:
            qs.append(f"{products[0]} {' '.join(job)}")
    elif len(core) >= 2:
        qs.append(" ".join(core))
    seen, out = set(), []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:4]


def _similarity(idea_toks: set[str], repo: Asset) -> float:
    bag = set(_tokens(repo.title.split("/")[-1].replace("-", " ") + " " + repo.summary + " " + " ".join(repo.keywords)))
    if not bag or not idea_toks:
        return 0.0
    inter = idea_toks & bag
    return len(inter) / math.sqrt(len(idea_toks) * len(bag))


async def find_duplicates(idea: str, *, months: int = 24, max_stars: int | None = None, limit: int = 40) -> dict[str, Any]:
    """What already exists for this idea, as a ranked cluster, with a feature matrix."""
    since = date.today() - timedelta(days=30 * months)
    idea_toks = set(_tokens(idea))
    found: dict[str, Asset] = {}
    errors: list[str] = []
    for q in _queries_for(idea):
        try:
            for r in await gh.search_repos(q, since=since, limit=50):
                found.setdefault(r.title, r)
        except SourceError as e:
            errors.append(f"github '{q}': {e}")
    repos = list(found.values())
    scored = []
    for r in repos:
        sim = _similarity(idea_toks, r)
        if sim < 0.2:
            continue
        if max_stars is not None and r.stats.get("stars", 0) > max_stars:
            continue
        scored.append((sim, r))
    # relevance decides membership; stars decide order, because the reader wants the leader first
    scored.sort(key=lambda x: -x[0])
    cluster = sorted((r for _, r in scored[:limit]), key=lambda r: -r.stats.get("stars", 0))

    matrix = {r.title: sorted(_features(r)) for r in cluster}
    all_features = Counter(f for fs in matrix.values() for f in fs)
    stars = [r.stats.get("stars", 0) for r in cluster]
    leader = max(cluster, key=lambda r: r.stats.get("stars", 0)) if cluster else None
    # "nobody has": features that appear in the wider search results (so they are relevant to this
    # kind of tool) but in none of the cluster members
    wider = Counter(f for r in repos for f in _features(r))
    nobody_has = sorted((f for f in wider if f not in all_features and not f.startswith("license")), key=lambda f: -wider[f]) if cluster else []
    # "what only one has": the pieces a merge would collect
    unique = {r.title: [f for f in fs if all_features[f] == 1] for r, fs in ((r, matrix[r.title]) for r in cluster)}

    verdict = _verdict(idea, cluster, stars, leader)
    return {
        "idea": idea,
        "count": len(cluster),
        "total_stars": sum(stars),
        "median_stars": sorted(stars)[len(stars) // 2] if stars else 0,
        "leader": {"repo": leader.title, "url": leader.url, "stars": leader.stats.get("stars", 0), "pushed": leader.date.isoformat() if leader.date else None} if leader else None,
        "cluster": [
            {"repo": r.title, "url": r.url, "stars": r.stats.get("stars", 0), "language": next((k for k in r.keywords if k in ("python", "go", "rust", "typescript", "javascript", "shell", "swift", "c#", "java")), ""),
             "pushed": r.date.isoformat() if r.date else None, "summary": r.summary[:140], "features": matrix[r.title], "only_here": unique[r.title],
             "owner": r.extra.get("owner", ""), "archived": r.extra.get("archived") == "yes", "issues_disabled": r.extra.get("has_issues") == "no"}
            for r in cluster
        ],
        "features_anyone_has": [f for f, _ in all_features.most_common()],
        "features_nobody_has": nobody_has[:12],
        "verdict": verdict,
        "source_errors": errors,
    }


def _verdict(idea: str, cluster: list[Asset], stars: list[int], leader: Asset | None) -> str:
    if not cluster:
        return f"Nothing close to \"{idea}\" found on GitHub in the last two years. If that holds after a second search with other words, this is new."
    n = len(cluster)
    big = [r for r in cluster if r.stats.get("stars", 0) >= 500]
    if big:
        return (f"\"{idea}\" exists: {n} implementations, and {big[0].title} ({big[0].stats.get('stars', 0)} stars) already won. "
                f"Building another one will get the median {sorted(stars)[n // 2]} stars. Contribute the missing piece to {big[0].title} instead, "
                f"or build only what nobody has.")
    return (f"\"{idea}\" exists {n} times, none above {max(stars)} stars; the median is {sorted(stars)[n // 2]}. "
            f"That is {n} people who each built the same thing and got {sorted(stars)[n // 2]} stars for it. "
            f"The product that would win is the merge: see features_anyone_has and only_here. Propose it to them (propose_merge) or join the most active one.")


# ---------- the merge proposal

MAX_CLUSTER_FOR_MERGE = 15   # more than this is a bulk mailing, not a proposal; the user narrows the idea
MIN_CLUSTER_FOR_MERGE = 3
MAX_ISSUES_PER_DAY = 10      # GitHub's acceptable use forbids excessive bulk content in issues


def merge_plan(dup: dict[str, Any], *, days: int = 21, plan_url: str | None = None) -> dict[str, Any]:
    """From a duplicates cluster: which repo is the base (most active, most stars), what each other
    repo contributes (its only_here features), who the authors are, and the text of the issue each
    author receives. Nothing is sent by this function. `plan_url` is where the plan will be readable
    (the user's repository or gist); without it the issue text carries the whole plan inline."""
    cluster = [r for r in dup["cluster"] if not r.get("archived")]
    if len(cluster) < MIN_CLUSTER_FOR_MERGE:
        raise ValueError(f"a merge proposal needs at least {MIN_CLUSTER_FOR_MERGE} living repositories (found {len(cluster)})")
    if len(cluster) > MAX_CLUSTER_FOR_MERGE:
        # keep the three with most stars and the most recently active of the rest
        top = sorted(cluster, key=lambda r: -r["stars"])[:3]
        rest = sorted((r for r in cluster if r not in top), key=lambda r: r["pushed"] or "", reverse=True)
        cluster = top + rest[: MAX_CLUSTER_FOR_MERGE - 3]
    # The base is the leader if it is alive (its stars and users carry over); else the most active.
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    alive = [r for r in cluster if (r["pushed"] or "") >= cutoff]
    base = max(alive or cluster, key=lambda r: (r["stars"], r["pushed"] or ""))
    others = [r for r in cluster if r["repo"] != base["repo"]]
    authors = sorted({r["owner"] for r in cluster if r["owner"]})
    name = "merged-" + re.sub(r"[^a-z0-9]+", "-", fold(dup["idea"]))[:40].strip("-")
    deadline = (date.today() + timedelta(days=days)).isoformat()
    contributions = {r["repo"]: (r["only_here"] or ["review and tests"]) for r in others}

    plan_md = [f"# Merge plan: {dup['idea']}", "",
               f"{len(cluster)} repositories solve this. Together they have {dup['total_stars']} stars; the median is {dup['median_stars']}. "
               f"One project with all of their pieces is the one that gets used.", "",
               f"**Base:** `{base['repo']}` (most recently active, {base['stars']} stars). Nothing is deleted anywhere; every original repository stays and gets a line \"merged into {name}\" if its author wants.", "",
               "| from | brings |", "|---|---|"]
    for r in others:
        plan_md.append(f"| `{r['repo']}` | {', '.join(contributions[r['repo']])} |")
    plan_md += ["", "**Authorship:** every author is a maintainer with write access from day one and is listed in README and CITATION.cff. Commits keep their authors.", "",
                f"**Deadline:** first release that does what all of them did, by {deadline}. Then the pieces nobody has: {', '.join(dup['features_nobody_has'][:5]) or 'to decide together'}.", "",
                "**How to say yes:** reply \"in\" on the issue in your repository, or open an issue in the merged repository. How to say no: ignore it.", ""]

    issue_title = f"{len(cluster)} of us built the same thing. Merge?"
    stars_phrase = (f"`{base['repo']}` has {base['stars']} stars, the rest a median of {dup['median_stars']}"
                    if base["stars"] >= 50 else f"the median has {dup['median_stars']} stars")
    plan_ref = f"Plan: {plan_url}" if plan_url else "Plan (full text below)."
    issues = []
    for r in cluster:
        if r.get("issues_disabled"):
            continue
        others_list = ", ".join(f"[{o['repo']}]({o['url']})" for o in cluster if o["repo"] != r["repo"])[:1500]
        yours = ", ".join(r["only_here"]) or "a working implementation"
        body = (f"Hi {r['owner']},\n\n"
                f"`{r['repo']}` is one of {len(cluster)} repositories that solve \"{dup['idea']}\" ({others_list}). "
                f"{stars_phrase}; none has everything. Yours has what the others don't: **{yours}**.\n\n"
                f"Proposal: one repository with all of us as maintainers, `{base['repo']}` as the base, your piece ported with your authorship, "
                f"first release by {deadline}. {plan_ref}\n\n"
                f"Nothing is deleted. Your repository stays; you decide whether to point it at the merged one.\n\n"
                f"In? Reply \"in\". Not interested? Ignore this, no follow-up.\n")
        if not plan_url:
            body += "\n---\n\n" + "\n".join(plan_md)
        issues.append({"repo": r["repo"], "owner": r["owner"], "title": issue_title, "body": body})

    return {
        "name": name,
        "base": base["repo"],
        "authors": authors,
        "contributions": contributions,
        "deadline": deadline,
        "plan_md": "\n".join(plan_md),
        "issues": issues,
        "truncated_to": len(cluster) if len(dup["cluster"]) > len(cluster) else None,
        "rules": [
            "Open one issue per repository, from the user's own GitHub account, each author sees the same plan.",
            "No issue is opened without the user's explicit yes; the texts above are for them to read first.",
            f"At most {MAX_ISSUES_PER_DAY} issues per day, 20 seconds apart, never to archived repositories or ones with issues disabled, never twice to the same repository.",
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


async def open_issue(owner: str, repo: str, title: str, body: str) -> dict[str, Any]:
    """Open an issue with the user's token. Only called after the user said yes. Keeps a local
    ledger so the same repository is never asked twice and the daily cap holds across runs."""
    import asyncio
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
        if meta.status_code == 200:
            m = meta.json()
            if m.get("archived"):
                raise SourceError(f"{key} is archived")
            if m.get("has_issues") is False:
                raise SourceError(f"{key} has issues disabled")
        # never duplicate an open issue with the same title (ours or anyone's)
        existing = await client.get(f"{API}/repos/{owner}/{repo}/issues", headers=h, params={"state": "open", "per_page": 50})
        if existing.status_code == 200 and any((i.get("title") or "") == title for i in existing.json() if isinstance(i, dict)):
            raise SourceError(f"{key} already has an open issue with this title")
        r = await client.post(f"{API}/repos/{owner}/{repo}/issues", headers=h, json={"title": title, "body": body})
    except httpx.HTTPError as e:
        raise SourceError(f"github: {e}")
    if r.status_code in (403, 404, 410):
        raise SourceError(f"{key}: cannot open issues there (HTTP {r.status_code})")
    if r.status_code != 201:
        raise SourceError(f"issue failed: HTTP {r.status_code} {r.text[:160]}")
    url = r.json().get("html_url")
    led[key] = {"date": today, "issue": url}
    _ledger_save(led)
    await asyncio.sleep(20)  # pace: this is a conversation starter, not a mailing
    return {"issue": url}
