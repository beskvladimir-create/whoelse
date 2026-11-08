"""The network: an open registry of people who are waiting to work with someone.

One JSON file per person in a public GitHub repository (default: beskvladimir-create/whoelse-network,
folder `people/`). Reading needs no account. Writing is a pull request that the user's own agent
opens with the user's GitHub token; without a token, whoelse writes the file locally and tells the
user exactly where to put it. The registry holds requests, not profiles: what the person wants to
build, with whom, by when.

Trust model. A registry file is data written by a stranger. Before anything acts on it:
  1. it must parse against the strict Request schema below (anything else is dropped);
  2. the registry's own CI only merges a file whose `ids.github` equals the PR author's login and
     whose path is `people/<slug(name)>.json` (see registry/ci.yml, shipped with this package);
  3. the watcher never emails, invites or names a person unless `verified()` holds: the GitHub
     login in `ids` has a public profile whose display name matches `name`, and an ORCID, if given,
     does not contradict the contact.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from .brief import FORMATS
from .config import settings
from .http import SourceError, http
from .models import Profile
from .profile import fold, slug
from .sources import github as gh

DEFAULT_REGISTRY = "beskvladimir-create/whoelse-network"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
API = "https://api.github.com"
FORMAT_IDS = {f[0] for f in FORMATS}
ASSET_KINDS = {"paper", "repo", "model", "dataset", "space"}
_ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_GH_LOGIN = re.compile(r"^[A-Za-z\d](?:[A-Za-z\d]|-(?=[A-Za-z\d])){0,38}$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
_CLEAN = re.compile(r"[\x00-\x1f\x7f]")


def _clean_text(v: str) -> str:
    """Drop control and invisible formatting characters (RTL override, zero-width, bidi isolates);
    collapse whitespace. What is left is what a human would read."""
    import unicodedata
    out = []
    for ch in v:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Co", "Cn"):
            continue
        out.append(" " if cat == "Zs" or ch in "\t\n\r" else ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def registry_repo() -> str:
    return os.environ.get("WHOELSE_REGISTRY", DEFAULT_REGISTRY)


# ---------- the schema every registry file must satisfy

class Want(BaseModel):
    format: str
    topic: str = Field(min_length=3, max_length=200)
    by: str = ""

    @field_validator("format")
    @classmethod
    def _format(cls, v: str) -> str:
        if v not in FORMAT_IDS:
            raise ValueError("unknown format")
        return v

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, v: str) -> str:
        v = _clean_text(v)
        if len(v) < 3:
            raise ValueError("topic too short")
        return v

    @field_validator("by")
    @classmethod
    def _iso_or_empty(cls, v: str) -> str:
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("by must be YYYY-MM-DD or empty")
        return v


class Ids(BaseModel):
    orcid: str | None = None
    github: str | None = None
    huggingface: str | None = None
    openalex: str | None = None

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, v: str | None) -> str | None:
        if v is not None and not _ORCID.match(v):
            raise ValueError("bad ORCID")
        return v

    @field_validator("github", "huggingface")
    @classmethod
    def _login(cls, v: str | None) -> str | None:
        if v is not None and not _GH_LOGIN.match(v):
            raise ValueError("bad login")
        return v

    @field_validator("openalex")
    @classmethod
    def _oa(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"A\d{4,12}", v):
            raise ValueError("bad openalex id")
        return v


class Request(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    contact: str = Field(max_length=254)
    site: str = Field(default="", max_length=200)
    ids: Ids = Field(default_factory=Ids)
    working_on: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    wants: list[Want] = Field(min_length=1, max_length=3)
    has: list[str] = Field(default_factory=list, max_length=5)
    open_to_strangers: bool = True
    languages: list[str] = Field(default_factory=lambda: ["en"], max_length=10)
    published: str = ""
    expires: str = ""
    spec: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _one_line(cls, v: str) -> str:
        v = _clean_text(v)
        if len(v.split()) < 2 or "<" in v or ">" in v or "@" in v:
            raise ValueError("name must be a plain full name")
        return v

    @field_validator("contact")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL.match(v):
            raise ValueError("contact must be one email address")
        return v

    @field_validator("working_on", "keywords", "languages", "has", mode="before")
    @classmethod
    def _short_strings(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("must be a list of strings")
        out = []
        for x in v:
            if not isinstance(x, str):
                raise ValueError("strings only")
            x = _clean_text(x)[:60]
            if x:
                out.append(x)
        return out

    @field_validator("has")
    @classmethod
    def _kinds(cls, v: list[str]) -> list[str]:
        bad = set(v) - ASSET_KINDS
        if bad:
            raise ValueError(f"unknown asset kinds {sorted(bad)}")
        return v

    @field_validator("site")
    @classmethod
    def _site(cls, v: str) -> str:
        v = v.strip()
        if v and not re.match(r"^https?://[^\s/]+", v):
            raise ValueError("site must be an http(s) URL")
        return v

    @field_validator("published", "expires")
    @classmethod
    def _dates(cls, v: str) -> str:
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    def current(self, today: date | None = None) -> bool:
        t = (today or date.today()).isoformat()
        return not self.expires or self.expires >= t


def parse_request(data: Any) -> Request | None:
    """Strict parse. Anything that does not fit is dropped, never partially trusted."""
    if not isinstance(data, dict):
        return None
    try:
        return Request.model_validate(data)
    except ValidationError:
        return None


# ---------- building a request

def make_request(
    prof: Profile,
    *,
    contact: str,
    wants: list[dict[str, str]],
    site: str = "",
    languages: list[str] | None = None,
    months_valid: int = 3,
) -> dict[str, Any]:
    """Validated on the way out too: the user's own request must satisfy the same schema."""
    kinds = sorted({a.kind for a in prof.assets})
    req = Request(
        name=prof.name,
        contact=contact,
        site=site,
        ids=Ids(**{k: v for k, v in prof.ids.items() if k in ("orcid", "github", "huggingface", "openalex")}),
        working_on=[t for t in list(prof.topics)[:5]],
        keywords=[k for k in list(prof.keywords)[:12]],
        wants=[Want(**w) for w in wants],
        has=kinds,
        open_to_strangers=True,
        languages=languages or ["en"],
        published=date.today().isoformat(),
        expires=(date.today() + timedelta(days=30 * months_valid)).isoformat(),
        spec="https://github.com/beskvladimir-create/whoelse#the-network",
    )
    return req.model_dump()


def request_path(name: str) -> str:
    return f"people/{slug(name)}.json"


def save_request_locally(req: dict[str, Any], *, published: dict[str, Any] | None = None) -> Path:
    d = settings().home / "network"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{slug(req['name'])}.json"
    data = dict(req)
    data["_published"] = published or {}
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return p


def load_local_requests() -> dict[str, dict[str, Any]]:
    d = settings().home / "network"
    if not d.exists():
        return {}
    out = {}
    for p in d.glob("*.json"):
        try:
            out[p.stem] = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    return out


# ---------- reading the registry

async def default_branch(repo: str) -> str:
    try:
        info = await http.get_json(f"{API}/repos/{repo}", headers=gh._headers(), fixture_name=f"network_repo_{repo.replace('/', '_')}")
    except SourceError:
        return "main"
    return (info or {}).get("default_branch") or "main"


async def list_requests() -> list[Request]:
    """All current, well-formed requests. The tree is read fresh every time (the watcher exists to
    see today's network); each file is fetched by its blob sha, so unchanged files cache well."""
    repo = registry_repo()
    branch = await default_branch(repo)
    try:
        tree = await http.get_json(
            f"{API}/repos/{repo}/git/trees/{branch}", {"recursive": "1"}, headers=gh._headers(),
            fixture_name=f"network_tree_{repo.replace('/', '_')}", cache_hours=0,
        )
    except SourceError as e:
        raise SourceError(f"registry {repo} unreadable: {e}")
    if not isinstance(tree, dict):
        return []
    entries = [
        t for t in tree.get("tree", [])
        if isinstance(t, dict) and str(t.get("path", "")).startswith("people/") and str(t.get("path", "")).endswith(".json")
    ]
    out: list[Request] = []
    for t in entries:
        path = t["path"]
        sha = t.get("sha")
        try:
            if sha:
                blob = await http.get_json(f"{API}/repos/{repo}/git/blobs/{sha}", headers=gh._headers(),
                                           fixture_name=f"network_{Path(path).stem}")
                raw = _decode_blob(blob)
            else:
                raw = await http.get_json(RAW.format(repo=repo, ref=branch, path=path),
                                          fixture_name=f"network_{Path(path).stem}", cache_hours=0)
        except SourceError:
            continue
        req = parse_request(raw)
        if req and req.current() and slug(req.name) == Path(path).stem:
            out.append(req)
    return out


def _decode_blob(blob: Any) -> Any:
    """A git blob object ({content: base64, encoding: "base64"}) or, in fixtures, the JSON itself."""
    if isinstance(blob, dict) and blob.get("encoding") == "base64" and isinstance(blob.get("content"), str):
        import base64
        try:
            return json.loads(base64.b64decode(blob["content"]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    return blob


# ---------- verification before anyone is named, invited or emailed

async def verified(req: Request) -> tuple[bool, str]:
    """What this establishes, and no more: the file belongs to the GitHub account in ids.github
    (the registry CI ties it to the PR author) and that account's display name is the name in the
    file. It does NOT prove that account is the researcher of that name: anyone can set a display
    name. That is why the watcher never publishes a stranger's name: the repository is created
    private, the account is invited, and only after they accept ("in") does anything go public."""
    login = req.ids.github
    if not login:
        return False, "no github login in request"
    try:
        u = await gh.user(login)
    except SourceError as e:
        return False, f"github profile unreachable: {e}"
    if not u or u.ids.get("github_org"):
        return False, "github login missing or an organisation"
    if fold(u.name) == fold(login):
        return False, "github profile has no display name to match against"
    if fold(u.name) != fold(req.name):
        return False, f"github profile name '{u.name}' does not match request name"
    if req.ids.orcid:
        from .sources import orcid as orc
        try:
            c = await orc.person(req.ids.orcid)
        except SourceError:
            return False, "orcid record unreachable"
        if c.email and fold(c.email) != fold(req.contact):
            return False, "orcid public email differs from request contact"
    return True, "github profile name matches the request"


# ---------- matching requests against each other

from .profile import STOP_KEYWORDS as _TOOLING

GENERIC = {"large language models", "deep learning", "machine learning", "artificial intelligence", "nlp", "benchmark",
           "dataset", "language", "models", "model", "data", "systems", "system", "learning", "search", "enterprise",
           "analysis", "ai", "llm", "llms", "neural networks", "transformers", "python", "pytorch", "tensorflow",
           "jax", "huggingface", "open source", "research", "paper", "code"} | set(_TOOLING)
_TOPIC_STOP = {"data", "with", "from", "using", "based", "model", "models", "closed", "open", "language", "enterprise",
               "systems", "system", "learning", "search", "analysis", "study", "approach", "methods", "method", "the", "and", "for"}


def _kw(req: Request) -> set[str]:
    out = set()
    for k in req.keywords + req.working_on:
        k = fold(k).strip()
        if k and k not in GENERIC:
            out.add(k)
    return out


def _phrases(req: Request) -> set[str]:
    """Evidence from the stated topic: hyphenated terms and two-word phrases. Single plain words are not evidence."""
    out = set()
    for w in req.wants:
        toks = [t for t in re.findall(r"[a-z0-9][a-z0-9-]{2,}", fold(w.topic)) if t not in _TOPIC_STOP]
        for i in range(len(toks) - 1):
            out.add(toks[i] + " " + toks[i + 1])
        out.update(t for t in toks if "-" in t)
    return out


def match_requests(mine: Request | dict, others: list[Request | dict]) -> list[dict[str, Any]]:
    """Mutual matches: a shared real keyword or phrase, strangers, both open to strangers. Ranked by
    evidence, then a wanted format in common, then complementary assets. `auto_start` is True only
    when the wanted format is the same: the watcher starts work on its own only then."""
    m = mine if isinstance(mine, Request) else parse_request(mine)
    if not m or not m.open_to_strangers:
        return []
    my_kw, my_ph = _kw(m), _phrases(m)
    my_ids = {f"{k}:{v}" for k, v in m.ids.model_dump().items() if v}
    my_has = set(m.has)
    my_formats = {w.format for w in m.wants}
    out = []
    for raw in others:
        o = raw if isinstance(raw, Request) else parse_request(raw)
        if not o or not o.open_to_strangers:
            continue
        if fold(o.name) == fold(m.name):
            continue
        if my_ids & {f"{k}:{v}" for k, v in o.ids.model_dump().items() if v}:
            continue
        theirs = _kw(o) | _phrases(o)
        shared = sorted((my_kw | my_ph) & theirs)
        if not shared:
            continue
        common_formats = sorted(my_formats & {w.format for w in o.wants})
        complement = sorted(set(o.has) - my_has)
        score = len(shared) + (1.0 if common_formats else 0.0) + min(0.5, 0.25 * len(complement))
        out.append({
            "request": o,
            "shared": shared,
            "common_formats": common_formats,
            "they_have_you_dont": complement,
            "score": round(score, 2),
            "auto_start": bool(common_formats),
        })
    out.sort(key=lambda x: -x["score"])
    return out


# ---------- writing: a pull request with the user's token

async def publish_via_pr(req: dict[str, Any]) -> dict[str, Any]:
    """Add or update people/<slug>.json in the registry through a pull request.
    Needs GITHUB_TOKEN with `public_repo` scope. Handles the user owning the registry (no fork),
    a stale fork (synced first), a fork still being created (polled), and renewal (same branch,
    existing PR reused)."""
    import asyncio
    import base64

    import httpx

    if settings().fixtures_dir:
        raise SourceError("offline mode (WHOELSE_FIXTURES set); cannot open a pull request")
    if not settings().github_token:
        raise SourceError("no GITHUB_TOKEN; cannot open a pull request")
    if not parse_request(req):
        raise SourceError("request does not satisfy the registry schema")
    repo = registry_repo()
    owner, _ = repo.split("/", 1)
    client = await http._get_client()
    h = gh._headers()
    try:
        me = (await client.get(f"{API}/user", headers=h)).json().get("login")
        if not me:
            raise SourceError("token does not resolve to a user")
        base = await default_branch(repo)
        if me == owner:
            work = repo
        else:
            r = await client.post(f"{API}/repos/{repo}/forks", headers=h)
            if r.status_code not in (200, 202):
                raise SourceError(f"fork failed: HTTP {r.status_code} {r.text[:160]}")
            work = (r.json() or {}).get("full_name") or f"{me}/{repo.split('/')[1]}"
            for _ in range(6):  # forks are created asynchronously
                if (await client.get(f"{API}/repos/{work}", headers=h)).status_code == 200:
                    break
                await asyncio.sleep(2)
            await client.post(f"{API}/repos/{work}/merge-upstream", headers=h, json={"branch": base})
        ref = await client.get(f"{API}/repos/{work}/git/ref/heads/{base}", headers=h)
        if ref.status_code != 200:
            raise SourceError(f"cannot read {work}@{base}: HTTP {ref.status_code}")
        base_sha = ref.json()["object"]["sha"]
        branch = f"whoelse/{slug(req['name'])}"
        r = await client.post(f"{API}/repos/{work}/git/refs", headers=h, json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        if r.status_code == 422 and "already exists" in r.text.lower():
            pass
        elif r.status_code != 201:
            raise SourceError(f"branch failed: HTTP {r.status_code} {r.text[:160]}")
        path = request_path(req["name"])
        content = base64.b64encode(json.dumps(req, indent=2, ensure_ascii=False).encode()).decode()
        existing = await client.get(f"{API}/repos/{work}/contents/{path}", headers=h, params={"ref": branch})
        body: dict[str, Any] = {"message": f"whoelse: request from {req['name']}", "content": content, "branch": branch}
        if existing.status_code == 200:
            body["sha"] = existing.json()["sha"]
        r = await client.put(f"{API}/repos/{work}/contents/{path}", headers=h, json=body)
        if r.status_code not in (200, 201):
            raise SourceError(f"commit failed: HTTP {r.status_code} {r.text[:160]}")
        head = branch if me == owner else f"{me}:{branch}"
        open_prs = await client.get(f"{API}/repos/{repo}/pulls", headers=h, params={"head": f"{me}:{branch}", "state": "open"})
        if open_prs.status_code == 200 and open_prs.json():
            return {"pr": open_prs.json()[0].get("html_url"), "path": path, "updated": True}
        r = await client.post(
            f"{API}/repos/{repo}/pulls", headers=h,
            json={"title": f"{req['name']}: {req['wants'][0]['topic'][:60]}", "head": head, "base": base,
                  "body": "Open request published by whoelse. Merging makes this person visible to everyone running whoelse."},
        )
        if r.status_code != 201:
            raise SourceError(f"pull request failed: HTTP {r.status_code} {r.text[:160]}")
        return {"pr": r.json().get("html_url"), "path": path}
    except httpx.HTTPError as e:
        raise SourceError(f"github: {e}")
    except (KeyError, ValueError, TypeError) as e:
        raise SourceError(f"github response not understood: {e}")


def waiting_text(req: dict[str, Any] | Request, network_size: int, matches: int, contact: str) -> str:
    r = req if isinstance(req, Request) else parse_request(req)
    topic = r.wants[0].topic if r and r.wants else ""
    if matches:
        return f"{matches} {'person' if matches == 1 else 'people'} in the network want what you want ({topic}). Joint work can start now."
    if network_size == 0:
        return (f"Your request is published. You are the first person in the network on {topic}. "
                f"When someone with the same problem joins, the work starts by itself and a link goes to {contact}. "
                f"Nothing to do; just don't remove whoelse.")
    return (f"Your request is published. {network_size} people are waiting in the network, none on {topic} yet. "
            f"When one joins, the work starts by itself and a link goes to {contact}. Nothing to do; just don't remove whoelse.")
