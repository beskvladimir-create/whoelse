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


API = "https://api.github.com"


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings().github_token:
        h["Authorization"] = f"Bearer {settings().github_token}"
    return h


def _ascii_slug(text: str, limit: int) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-.")
    return t[:limit].strip("-.") or "x"


def repo_name(name_a: str, name_b: str, topic: str) -> str:
    """Deterministic for a pair+topic, so both sides and later passes agree on it; GitHub-safe."""
    a = _ascii_slug(name_a.split()[-1] if name_a.split() else name_a, 20)
    b = _ascii_slug(name_b.split()[-1] if name_b.split() else name_b, 20)
    first, second = sorted([a, b])
    return f"{first}-{second}-{_ascii_slug(topic, 40)}"[:90]


def _yaml(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


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


def _cite(a: Asset, fallback_author: str = "") -> str:
    y = a.date.year if a.date else "n.d."
    authors = [c for c in a.coauthors if c] or ([fallback_author] if fallback_author else [])
    who = authors[0] + (" et al." if len(authors) > 1 else "") if authors else "Unknown"
    return f"{who} ({y}). {a.title}. {a.url}".strip()


def build_workspace(me: Profile, c: Candidate, format_id: str, *, days: int = 14, topic: str | None = None) -> dict[str, str]:
    """Returns {relative_path: content}. `topic` is the human-written subject when there is one
    (from a request); otherwise the sharpest shared keyword."""
    p = c.person
    fmt = next((f for f in FORMATS if f[0] == format_id), FORMATS[0])
    kw = [k for k in c.overlap.shared_keywords if k]
    topic = topic or (kw[:1] or c.overlap.shared_topics[:1] or ["the same problem"])[0]
    if format_id not in {f[0] for f in FORMATS}:
        raise ValueError(f"unknown format_id {format_id!r}")
    mine, theirs = _papers(me.assets, topic=topic, keywords=kw), _papers(p.assets, topic=topic, keywords=kw)
    my_code, their_code = _code(me.assets, kw[0] if kw else topic), _code(p.assets, kw[0] if kw else topic)
    name = repo_name(me.name, p.name, topic)
    deadline = date.today() + timedelta(days=days)
    files: dict[str, str] = {}
    fmt_label = fmt[1]
    what_is_there = []
    if mine and theirs:
        what_is_there.append("section 1 is drafted from both published works")
    elif mine or theirs:
        what_is_there.append(f"section 1 is drafted from {(me.name if mine else p.name)}'s published work; the other half is to be written")
    else:
        what_is_there.append("the outline is written; neither side has a published abstract on this yet")
    if (mine and _numbers(mine[0].summary)) or (theirs and _numbers(theirs[0].summary)):
        what_is_there.append("the comparison table holds the figures already published")
    if my_code or their_code:
        what_is_there.append("the reproduction script points at the existing code")
    deliverable = {
        "compare_note": "a short comparison note (arXiv preprint)",
        "joint_paper": "a full paper",
        "joint_benchmark": "a benchmark with a leaderboard (data/, eval/, leaderboard.md)",
        "replication": "a cross-replication report with results.json",
        "merge_tools": "one merged repository with both as maintainers",
        "shared_dataset": "a documented dataset release with both names on the card",
        "talk_together": "a joint talk or podcast episode (abstract, outline, target venues)",
        "review_each_other": "exchanged draft reviews (private)",
    }[format_id]

    files["README.md"] = f"""# {fmt_label}: {topic}

**{me.name}** and **{p.name}** are working on the same problem from two sides. This repository is
the start of {deliverable}: {"; ".join(what_is_there)}. First result due **{deadline.isoformat()}**.

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
        sec1.append(f"**{who}** ({_cite(a, who)}): {a.summary[:700].rstrip()}{'...' if len(a.summary) > 700 else ''}\n")
        if nums:
            sec1.append(f"Reported figures: {', '.join(nums)}.\n")
    files["paper/paper.md"] = f"""---
title: {_yaml(fmt_label + ": " + topic)}
authors: [{_yaml(me.name)}, {_yaml(p.name)}]
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

{("1. " + _cite(mine[0], me.name)) if mine else "1. (" + me.name + ": no published work on this yet)"}
{("2. " + _cite(theirs[0], p.name)) if theirs else "2. (" + p.name + ": no published work on this yet)"}
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
| {days} | {deliverable.split(" (")[0]} delivered; release tagged v0.1 | both |

If one side goes quiet for 5 days, the other finishes alone, keeps the citation, and tags v0.1.
"""
    files["CITATION.cff"] = f"""cff-version: 1.2.0
title: {_yaml(fmt_label + ": " + topic)}
authors:
  - name: {_yaml(me.name)}
  - name: {_yaml(p.name)}
date-released: {deadline.isoformat()}
"""
    if format_id == "joint_benchmark":
        files["data/README.md"] = "# Data\n\nEach side adds its data here with a LICENSE and a one-paragraph card. Nothing private.\n"
        files["eval/README.md"] = "# Evaluation\n\nOne metric, one script, run by both. `python eval/run.py data/ > leaderboard.md`\n"
        files["leaderboard.md"] = f"# Leaderboard: {topic}\n\n| system | metric | by | date |\n|---|---|---|---|\n"
        files.pop("paper/paper.md", None)
    elif format_id == "talk_together":
        files["talk/abstract.md"] = f"# {topic}: a two-sided talk\n\n*150 words. What each of you found, where you disagree, what the audience takes home.*\n"
        files["talk/outline.md"] = f"# Outline (25 min)\n\n1. The problem ({me.name}, 5)\n2. Approach A ({me.name}, 6)\n3. Approach B ({p.name}, 6)\n4. Where they differ, with one table (both, 5)\n5. What we would do next (both, 3)\n"
        files["talk/venues.md"] = "# Where to submit\n\n| venue | CFP deadline | format |\n|---|---|---|\n| | | |\n"
        files.pop("paper/paper.md", None); files.pop("repro/run.py", None); files.pop("repro/README.md", None)
    elif format_id == "review_each_other":
        files["drafts/README.md"] = f"# Drafts\n\n`drafts/{_ascii_slug(me.name, 20)}/` and `drafts/{_ascii_slug(p.name, 20)}/`. Each reviews the other's within 7 days, as issues.\n"
        files.pop("paper/paper.md", None); files.pop("repro/run.py", None); files.pop("repro/README.md", None)
    elif format_id == "shared_dataset":
        files["dataset-card.md"] = f"# Dataset card: {topic}\n\nAuthors: {me.name}, {p.name}\n\n## What is in it\n\n## How it was collected\n\n## License\n\n## Known limits\n"
        files.pop("paper/paper.md", None)
    files[".whoelse.json"] = json.dumps(
        {"format": format_id, "topic": topic, "sides": [me.name, p.name], "deadline": deadline.isoformat(), "started": date.today().isoformat()},
        indent=2, ensure_ascii=False,
    )
    files["__name__"] = name
    files["__deliverable__"] = deliverable
    return files


def write_local(files: dict[str, str]) -> Path:
    name = files["__name__"]
    root = settings().home / "work" / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        if rel.startswith("__"):
            continue
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


async def create_repo(files: dict[str, str], *, private: bool = False, invite: str | None = None) -> dict[str, Any]:
    """Create the repository under the token owner's account and commit every file.
    Optionally invite a GitHub login as collaborator (that is how the other side gets write access)."""
    if settings().fixtures_dir:
        raise SourceError("offline mode (WHOELSE_FIXTURES set); workspace written locally instead")
    if not settings().github_token:
        raise SourceError("no GITHUB_TOKEN; workspace written locally instead")
    import base64

    import httpx

    name = files["__name__"]
    client = await http._get_client()
    h = _gh_headers()
    try:
        me = (await client.get(f"{API}/user", headers=h)).json().get("login")
        if not me:
            raise SourceError("token does not resolve to a user")
        full = f"{me}/{name}"
        if (await client.get(f"{API}/repos/{full}", headers=h)).status_code == 200:
            # Already there: someone may have pushed. Never overwrite.
            return {"repo": f"https://github.com/{full}", "full_name": full, "existing": True}
        r = await client.post(f"{API}/user/repos", headers=h, json={
            "name": name, "private": private, "auto_init": False,
            "description": files["README.md"].splitlines()[0].lstrip("# ")[:120],
            "has_issues": True, "has_wiki": False,
        })
        if r.status_code != 201:
            raise SourceError(f"create repo failed: HTTP {r.status_code} {r.text[:200]}")
        full = r.json().get("full_name") or full
        for rel, content in files.items():
            if rel.startswith("__"):
                continue
            body = {"message": f"whoelse: {rel}", "content": base64.b64encode(content.encode()).decode()}
            rr = await client.put(f"{API}/repos/{full}/contents/{rel}", headers=h, json=body)
            if rr.status_code not in (200, 201):
                raise SourceError(f"commit {rel} failed: HTTP {rr.status_code} {rr.text[:200]}")
        out: dict[str, Any] = {"repo": f"https://github.com/{full}", "full_name": full}
        if invite:
            rr = await client.put(f"{API}/repos/{full}/collaborators/{invite}", headers=h, json={"permission": "push"})
            out["invited"] = invite if rr.status_code in (201, 204) else f"invite failed: HTTP {rr.status_code}"
        return out
    except httpx.HTTPError as e:
        raise SourceError(f"github: {e}")
    except (KeyError, ValueError, TypeError) as e:
        raise SourceError(f"github response not understood: {e}")
