"""The watcher. Runs on the user's machine on a schedule, reads the registry, and when a mutual
match appears it starts the joint work and tells the user where. The user does nothing; they
just don't remove whoelse.

    whoelse-watch            # one pass; exit 0
    whoelse-watch --loop 6h  # keep running

Notification: email through the user's own SMTP (WHOELSE_SMTP_HOST/PORT/USER/PASS, from the
user's own address), else a line on stdout and a file in ~/.whoelse/inbox/. GitHub itself also
emails both sides when a repository is created and a collaborator invited.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import smtplib
import time
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from .config import settings
from .http import SourceError
from .models import Candidate, Overlap, Person
from .network import list_requests, match_requests
from .profile import build_profile, load_profile
from .workspace import build_workspace, create_repo, write_local


def _inbox() -> Path:
    d = settings().home / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seen_path() -> Path:
    return settings().home / "watch-seen.json"


def _load_seen() -> set[str]:
    p = _seen_path()
    return set(json.loads(p.read_text())) if p.exists() else set()


def _save_seen(s: set[str]) -> None:
    _seen_path().write_text(json.dumps(sorted(s)))


def notify(subject: str, body: str, to: str) -> str:
    """Email if SMTP is configured; always drop a copy in the inbox folder."""
    stamp = date.today().isoformat() + "-" + str(int(time.time()))
    (_inbox() / f"{stamp}.txt").write_text(f"To: {to}\nSubject: {subject}\n\n{body}")
    host = os.environ.get("WHOELSE_SMTP_HOST")
    if not host:
        return "inbox"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("WHOELSE_SMTP_FROM", os.environ.get("WHOELSE_SMTP_USER", to))
    msg["To"] = to
    msg.set_content(body)
    port = int(os.environ.get("WHOELSE_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        user, pw = os.environ.get("WHOELSE_SMTP_USER"), os.environ.get("WHOELSE_SMTP_PASS")
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    return "email"


async def _person_from_request(req: dict) -> Person:
    """The other side as a full person: their published work, not just their request."""
    ids = dict(req.get("ids") or {})
    try:
        prof = await build_profile(req["name"], orcid_id=ids.get("orcid"), github_login=ids.get("github"), huggingface_user=ids.get("huggingface"))
        p = Person(name=prof.name, ids={**prof.ids, **ids}, affiliation=prof.affiliation, assets=prof.assets,
                   keywords=prof.keywords, topics=prof.topics, contact=prof.contact)
    except Exception:  # noqa: BLE001 - the request alone is still enough to start
        p = Person(name=req["name"], ids=ids, keywords={k: 1.0 for k in req.get("keywords", [])})
    p.contact.email = req.get("contact") or p.contact.email
    if p.contact.email:
        p.contact.provenance["email"] = "their own whoelse request"
    if req.get("site"):
        p.contact.website = req["site"]
    return p


async def one_pass(*, me_name: str | None = None, dry_run: bool = False) -> list[dict]:
    """Check the registry for every local profile that has a published request. Start work on new
    mutual matches. Returns what happened."""
    home = settings().home
    net_dir = home / "network"
    if not net_dir.exists():
        return [{"note": "no published request on this machine; run publish_request first"}]
    requests = {p.stem: json.loads(p.read_text()) for p in net_dir.glob("*.json")}
    if me_name:
        requests = {k: v for k, v in requests.items() if k == me_name or v.get("name") == me_name}
    if not requests:
        return [{"note": "no request found for that name"}]
    try:
        others = await list_requests()
    except SourceError as e:
        return [{"error": str(e)}]
    seen = _load_seen()
    events: list[dict] = []
    for key, mine in requests.items():
        prof = load_profile(mine["name"])
        if not prof:
            events.append({"name": mine["name"], "note": "profile missing; run load_profile again"})
            continue
        matches = match_requests(mine, others)
        events.append({"name": mine["name"], "network": len(others), "matches": len(matches)})
        for m in matches[:3]:
            o = m["request"]
            pair = "|".join(sorted([mine["name"], o["name"]]))
            if pair in seen:
                continue
            fmt = (m["common_formats"] or [w.get("format") for w in o.get("wants", [])] or ["compare_note"])[0]
            topic = next((w.get("topic") for w in mine.get("wants", []) if w.get("topic")), None) \
                or next((w.get("topic") for w in o.get("wants", []) if w.get("topic")), None)
            cand = Candidate(
                person=await _person_from_request(o), score=m["score"],
                overlap=Overlap(shared_keywords=m["shared"], they_have=m["they_have_you_dont"]),
                why="mutual request in the whoelse network", reachable="email" if o.get("contact") else "profile_only",
            )
            files = build_workspace(prof, cand, fmt, topic=topic)
            root = write_local(files)
            result: dict = {"pair": pair, "format": fmt, "local": str(root)}
            if not dry_run:
                try:
                    created = await create_repo(files, invite=(o.get("ids") or {}).get("github"))
                    result.update(created)
                except SourceError as e:
                    result["repo"] = f"not created: {e}"
                link = result.get("repo") if str(result.get("repo", "")).startswith("http") else str(root)
                body = (
                    f"{o['name']} wants the same thing you do: {topic or ', '.join(m['shared'][:3])}.\n\n"
                    f"The work has started: {link}\n\n"
                    f"Section 1 is drafted from both of your papers, the table has the published numbers, "
                    f"the plan is 14 days. Say yes by opening an issue titled \"in\" or pushing a commit.\n"
                )
                result["notified_you"] = notify(f"whoelse: joint work started with {o['name']}", body, mine["contact"])
                if o.get("contact"):
                    body2 = (
                        f"{mine['name']} works on the same problem as you ({topic or ', '.join(m['shared'][:3])}) and has started a joint "
                        f"{fmt.replace('_', ' ')} with your name on it:\n\n{link}\n\n"
                        f"Section 1 is drafted from both papers; the plan is 14 days. To join, open an issue titled \"in\". "
                        f"To decline, ignore this; the work will be finished alone with a citation to yours.\n"
                    )
                    result["notified_them"] = notify(f"{mine['name']} started joint work with you: {fmt.replace('_', ' ')}", body2, o["contact"])
                seen.add(pair)
            events.append(result)
    if not dry_run:
        _save_seen(seen)
    return events


def main() -> None:
    ap = argparse.ArgumentParser(description="whoelse watcher")
    ap.add_argument("--name", help="only this profile")
    ap.add_argument("--loop", help="keep running, e.g. 6h or 30m")
    ap.add_argument("--dry-run", action="store_true", help="build workspaces locally, create nothing, send nothing")
    a = ap.parse_args()
    interval = 0
    if a.loop:
        n, unit = int(a.loop[:-1]), a.loop[-1]
        interval = n * {"m": 60, "h": 3600, "d": 86400}[unit]
    while True:
        events = asyncio.run(one_pass(me_name=a.name, dry_run=a.dry_run))
        print(json.dumps(events, indent=2, ensure_ascii=False, default=str))
        if not interval:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
