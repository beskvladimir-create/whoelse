"""Joint work starts before the two people have exchanged a word.

`start_joint_work` builds a workspace: a paper skeleton with the first section drafted from both
sides' published abstracts, a comparison table filled from published numbers, a reproduction
script skeleton pointing at both repos, a 14-day plan, and both names on the byline. Then it
creates a GitHub repository for it (with the user's token) or leaves it as a folder with exact
instructions. The other person receives a link to a third of a finished work, not a letter.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .brief import FORMATS
from .config import settings
from .http import SourceError, http
from .models import Asset, Candidate, Profile
from .profile import slug

API = "https://api.github.com"


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings().github_token:
        h["Authorization"] = f"Bearer {settings().github_token}"
    return h


def _papers(assets: list[Asset], n: int = 3, topic: str = "", keywords: list[str] | None = None) -> list[Asset]:
    """Papers, the ones about the shared problem first, then by date."""
    wanted = {w.lower() for w in (keywords or [])} | ({topic.lower()} if topic else set())
    wanted |= {w.replace("-", " ") for w in wanted}

    def rel(a: Asset) -> int:
        bag = (a.title + " " + a.summary + " " + " ".join(a.keywords + a.topics)).lower()
        return sum(1 for w in wanted if w and w in bag)
    return sorted((a for a in assets if a.kind == "paper"), key=lambda a: (rel(a), a.date or date.min), reverse=True)[:n]


def _code(assets: list[Asset], topic: str = "") -> list[Asset]:
    """Runnable things, the on-topic ones first."""
    items = [a for a in assets if a.kind in ("repo", "model", "dataset")]
    t = topic.lower()

    def on_topic(a: Asset) -> int:
        bag = (a.title + " " + a.summary + " " + " ".join(a.keywords)).lower()
        return 1 if t and (t in bag or t.replace("-", " ") in bag or t.replace("-", "") in bag) else 0
    return sorted(items, key=lambda a: (on_topic(a), a.date or date.min), reverse=True)


def _numbers(text: str) -> list[str]:
    """Figures a published abstract states: percentages, accuracies, sizes. Quoted, never invented."""
    return re.findall(r"\b\d{1,3}(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?[BMK]\b|\b\d+(?:,\d{3})+\b", text)[:6]


def _cite(a: Asset) -> str:
    y = a.date.year if a.date else "n.d."
    return f"{a.coauthors[0] if a.coauthors else '?'} et al. ({y}). {a.title}. {a.url}"


def build_workspace(me: Profile, c: Candidate, format_id: str, *, days: int = 14, topic: str | None = None) -> dict[str, str]:
    """Returns {relative_path: content}. `topic` is the human-written subject when there is one
    (from a request); otherwise the sharpest shared keyword."""
    p = c.person
    fmt = next((f for f in FORMATS if f[0] == format_id), FORMATS[0])
    kw = [k for k in c.overlap.shared_keywords if k]
    topic = topic or (kw[:1] or c.overlap.shared_topics[:1] or ["the same problem"])[0]
    mine, theirs = _papers(me.assets, topic=topic, keywords=kw), _papers(p.assets, topic=topic, keywords=kw)
    my_code, their_code = _code(me.assets, kw[0] if kw else topic), _code(p.assets, kw[0] if kw else topic)
    name = f"{slug(me.name.split()[-1])}-{slug(p.name.split()[-1])}-{slug(topic)[:30]}"
    deadline = date.today() + timedelta(days=days)
    files: dict[str, str] = {}

    # README: what this is, for the person who just received the link
    files["README.md"] = f"""# {fmt[1]}: {topic}

**{me.name}** and **{p.name}** are working on the same problem from two sides. This repository is
the start of a joint {fmt[1].lower()}: the outline is written, section 1 is drafted from both
published works, the comparison table holds the numbers each side has already published, and the
reproduction script points at both codebases. First result due **{deadline.isoformat()}**.

What each side brings:

- {me.name}: {', '.join(a.title for a in mine[:2]) or 'see profile'}{'; code: ' + ', '.join(a.title for a in my_code[:2]) if my_code else ''}
- {p.name}: {', '.join(a.title for a in theirs[:2]) or 'see profile'}{'; code: ' + ', '.join(a.title for a in their_code[:2]) if their_code else ''}

How to say yes: open an issue titled "in", or push a commit. How to say no: ignore it; after
{days} days {me.name} finishes alone and publishes with a citation to your work.

Started with [whoelse](https://github.com/beskvladimir-create/whoelse). Nothing here was sent to
anyone else.
"""

    # The paper
    sec1 = []
    sec1.append(f"## 1. Two approaches to {topic}\n")
    for who, papers in ((me.name, mine), (p.name, theirs)):
        if not papers:
            sec1.append(f"*{who}: no published abstract found; to be written by {who}.*\n")
            continue
        a = papers[0]
        nums = _numbers(a.summary)
        sec1.append(f"**{who}** ({_cite(a)}): {a.summary[:700].rstrip()}{'...' if len(a.summary) > 700 else ''}\n")
        if nums:
            sec1.append(f"Reported figures: {', '.join(nums)}.\n")
    files["paper/paper.md"] = f"""---
title: "{fmt[1]}: {topic}"
authors: ["{me.name}", "{p.name}"]
status: draft, section 1 from published abstracts, sections 2-4 to write
---

# {fmt[1]}: {topic}

**Abstract.** *To write last.*

{chr(10).join(sec1)}
## 2. Where the approaches differ

| aspect | {me.name} | {p.name} |
|---|---|---|
| problem setting | | |
| data | | |
| model / method | | |
| reported result | {', '.join(_numbers(mine[0].summary)) if mine else ''} | {', '.join(_numbers(theirs[0].summary)) if theirs else ''} |
| cost / hardware | | |
| what it does not cover | | |

*Fill from the papers; every cell must cite a page or a table.*

## 3. One experiment that settles something

*Pick one question the two works answer differently. Run both methods on the same data
(see `repro/`). Report the table, not the adjectives.*

## 4. What we would do together next

*One paragraph, written together, once section 3 has a number in it.*

## References

1. {_cite(mine[0]) if mine else ''}
2. {_cite(theirs[0]) if theirs else ''}
"""

    # Reproduction skeleton
    files["repro/README.md"] = f"""# Reproduction

Both methods, same data, same metric. Each side fills in its own half.

| | {me.name} | {p.name} |
|---|---|---|
| code | {my_code[0].url if my_code else 'TODO'} | {their_code[0].url if their_code else 'TODO'} |
| entry point | TODO | TODO |
| data | TODO | TODO |
| metric | TODO | TODO |

`run.py` runs whatever both halves provide and writes `results.json`.
"""
    files["repro/run.py"] = '''"""Run both methods on the same data. Each side implements its own function."""
import json
from pathlib import Path


def run_a(data_dir: Path) -> dict:
    """''' + me.name + '''"""
    raise NotImplementedError


def run_b(data_dir: Path) -> dict:
    """''' + p.name + '''"""
    raise NotImplementedError


if __name__ == "__main__":
    data = Path("data")
    out = {}
    for name, fn in (("a", run_a), ("b", run_b)):
        try:
            out[name] = fn(data)
        except NotImplementedError:
            out[name] = "not implemented yet"
    Path("results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
'''

    # Plan
    files["PLAN.md"] = f"""# {days}-day plan

| day | what | who |
|---|---|---|
| 1 | read each other's paper; fill table in paper.md section 2 | both |
| 3 | agree the one question for section 3 (issue #1) | both |
| 5 | repro/run.py runs end to end on a toy sample | both |
| 9 | full run; results.json committed | both |
| 11 | section 3 written from results.json | {me.name} drafts, {p.name} edits |
| 13 | section 4 and abstract | {p.name} drafts, {me.name} edits |
| {days} | preprint submitted (arXiv) or release tagged | both |

If one side goes quiet for 5 days, the other finishes alone, keeps the citation, and tags v0.1.
"""
    files["CITATION.cff"] = f"""cff-version: 1.2.0
title: "{fmt[1]}: {topic}"
authors:
  - name: "{me.name}"
  - name: "{p.name}"
date-released: {deadline.isoformat()}
"""
    files[".whoelse.json"] = json.dumps(
        {"format": format_id, "topic": topic, "sides": [me.name, p.name], "deadline": deadline.isoformat(), "started": date.today().isoformat()},
        indent=2, ensure_ascii=False,
    )
    files["__name__"] = name
    return files


def write_local(files: dict[str, str]) -> Path:
    name = files.pop("__name__")
    root = settings().home / "work" / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    files["__name__"] = name
    return root


async def create_repo(files: dict[str, str], *, private: bool = False, invite: str | None = None) -> dict[str, Any]:
    """Create the repository under the token owner's account and commit every file.
    Optionally invite a GitHub login as collaborator (that is how the other side gets write access)."""
    if settings().fixtures_dir:
        raise SourceError("offline mode (WHOELSE_FIXTURES set); workspace written locally instead")
    if not settings().github_token:
        raise SourceError("no GITHUB_TOKEN; workspace written locally instead")
    import base64

    name = files["__name__"]
    client = await http._get_client()
    h = _gh_headers()
    r = await client.post(f"{API}/user/repos", headers=h, json={
        "name": name, "private": private, "auto_init": False,
        "description": files["README.md"].splitlines()[0].lstrip("# ")[:120],
        "has_issues": True, "has_wiki": False,
    })
    if r.status_code == 422 and "already exists" in r.text:
        me = (await client.get(f"{API}/user", headers=h)).json()["login"]
        full = f"{me}/{name}"
    elif r.status_code != 201:
        raise SourceError(f"create repo failed: HTTP {r.status_code} {r.text[:200]}")
    else:
        full = r.json()["full_name"]
    for rel, content in files.items():
        if rel == "__name__":
            continue
        body = {"message": f"whoelse: {rel}", "content": base64.b64encode(content.encode()).decode()}
        ex = await client.get(f"{API}/repos/{full}/contents/{rel}", headers=h)
        if ex.status_code == 200:
            body["sha"] = ex.json()["sha"]
        rr = await client.put(f"{API}/repos/{full}/contents/{rel}", headers=h, json=body)
        if rr.status_code not in (200, 201):
            raise SourceError(f"commit {rel} failed: HTTP {rr.status_code} {rr.text[:200]}")
    out: dict[str, Any] = {"repo": f"https://github.com/{full}", "full_name": full}
    if invite:
        rr = await client.put(f"{API}/repos/{full}/collaborators/{invite}", headers=h, json={"permission": "push"})
        out["invited"] = invite if rr.status_code in (201, 204) else f"invite failed: HTTP {rr.status_code}"
    return out
