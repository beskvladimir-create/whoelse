"""The watcher. Runs on the user's machine on a schedule, reads the registry, and when a mutual
match appears it starts the joint work and tells the user where. The user does nothing; they
just don't remove whoelse.

    whoelse-watch            # one pass; exit 0
    whoelse-watch --loop 6h  # keep running

Rules that keep strangers safe:
  * a request acts on nobody until `network.verified()` holds (GitHub profile name == request name);
  * exactly one side creates the repository: the one whose name sorts first; the other side waits,
    checks for the invitation on later passes, and takes over after WAIT_DAYS without it;
  * an existing repository is never overwritten; the stranger is emailed only with a public link,
    and only once; the user is emailed once per pair;
  * state is saved after every pair, so an SMTP failure cannot replay anything.

Notification: email through the user's own SMTP (WHOELSE_SMTP_HOST/PORT/USER/PASS/FROM), else a
file in ~/.whoelse/inbox/. GitHub itself also emails both sides when a repository is created and
a collaborator invited.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import smtplib
import time
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .config import settings
from .http import SourceError, http
from .models import Candidate, Overlap, Person
from .network import Request, list_requests, load_local_requests, match_requests, verified
from .profile import build_profile, fold, load_profile
from .sources import github as gh
from .workspace import build_workspace, create_repo, repo_name, write_local

WAIT_DAYS = 3


def _inbox() -> Path:
    d = settings().home / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return settings().home / "watch-state.json"


def load_state() -> dict[str, dict[str, Any]]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except ValueError:
        return {}


def save_state(state: dict[str, dict[str, Any]]) -> None:
    _state_path().write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))


def notify(subject: str, body: str, to: str) -> str:
    """Email if SMTP is fully configured (host and a From address of the user's own); always drop a
    copy in the inbox folder. Never forges the recipient as sender."""
    subject = subject.replace("\r", " ").replace("\n", " ")[:200]
    stamp = date.today().isoformat() + "-" + str(int(time.time() * 1000))
    (_inbox() / f"{stamp}.txt").write_text(f"To: {to}\nSubject: {subject}\n\n{body}")
    host = os.environ.get("WHOELSE_SMTP_HOST")
    sender = os.environ.get("WHOELSE_SMTP_FROM") or os.environ.get("WHOELSE_SMTP_USER")
    if not host or not sender:
        return "inbox"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    port = int(os.environ.get("WHOELSE_SMTP_PORT", "587"))
    tls = os.environ.get("WHOELSE_SMTP_TLS", "starttls").lower()
    if tls == "ssl" or port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server as s:
        if tls == "starttls" and port != 465:
            s.starttls()
        user, pw = os.environ.get("WHOELSE_SMTP_USER"), os.environ.get("WHOELSE_SMTP_PASS")
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    return "email"


async def _person_from_request(req: Request) -> Person:
    """The other side as a full person: their published work, not just their request."""
    ids = {k: v for k, v in req.ids.model_dump().items() if v}
    try:
        prof = await build_profile(req.name, orcid_id=ids.get("orcid"), github_login=ids.get("github"), huggingface_user=ids.get("huggingface"))
        p = Person(name=prof.name, ids={**prof.ids, **ids}, affiliation=prof.affiliation, assets=prof.assets,
                   keywords=prof.keywords, topics=prof.topics, contact=prof.contact)
    except Exception:  # noqa: BLE001 - the request alone is still enough to start
        p = Person(name=req.name, ids=ids, keywords={k: 1.0 for k in req.keywords})
    p.contact.email = req.contact
    p.contact.provenance["email"] = "their own whoelse request"
    if req.site:
        p.contact.website = req.site
    return p


async def _repo_exists(full_name: str) -> str | None:
    try:
        data = await http.get_json(f"https://api.github.com/repos/{full_name}", headers=gh._headers(),
                                   fixture_name=f"github_repo_{full_name.replace('/', '_')}", cache_hours=0)
    except SourceError:
        return None
    return (data or {}).get("html_url") if data else None


def _i_create(mine: Request, other: Request) -> bool:
    return sorted([fold(mine.name), fold(other.name)])[0] == fold(mine.name)


async def _handle_pair(mine: Request, m: dict[str, Any], state: dict[str, dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    o: Request = m["request"]
    pair = "|".join(sorted([mine.name, o.name]))
    st = state.get(pair)
    if not isinstance(st, dict):
        st = {}
    result: dict[str, Any] = {"pair": pair, "shared": m["shared"]}
    if st.get("done") or (st.get("told_them") and st.get("repo")):
        if not st.get("done"):
            st["done"] = True
            state[pair] = st
        return {**result, "status": "done", "repo": st.get("repo")}
    if not m["auto_start"]:
        return {**result, "status": "report_only", "note": "no wanted format in common; nothing started"}

    ok, why = await verified(o)
    if not ok:
        return {**result, "status": "unverified", "note": f"not acting on this request: {why}"}

    fmt = m["common_formats"][0]
    topic = mine.wants[0].topic
    key = m["shared"][0]  # the matched keyword: identical on both sides, unlike either topic text
    expected = repo_name(mine.name, o.name, key)

    if not _i_create(mine, o):
        # Waiting side. Look for the creator's repository; after WAIT_DAYS take over.
        creator_login = o.ids.github
        if creator_login:
            url = await _repo_exists(f"{creator_login}/{expected}")
            if url:
                if not dry_run:
                    state[pair] = {"done": True, "role": "joined", "repo": url, "at": date.today().isoformat()}
                    notify(f"whoelse: {o.name} started joint work with you",
                           f"{o.name} created the repository for your joint {fmt.replace('_', ' ')} on {topic}:\n\n{url}\n\n"
                           f"Open an issue titled \"in\" there to confirm you are in.", mine.contact)
                return {**result, "status": "joined", "repo": url}
        since = st.get("waiting_since") or date.today().isoformat()
        try:
            since_d = datetime.strptime(str(since), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            since_d = date.today()
            since = since_d.isoformat()
        if not dry_run:
            state[pair] = {"waiting_since": since, "role": "wait"}
        days = (date.today() - since_d).days
        if days < WAIT_DAYS:
            return {**result, "status": "waiting", "note": f"{o.name} creates the repository; checking again (day {days}/{WAIT_DAYS})"}
        result["note"] = f"{o.name} did not create the repository in {WAIT_DAYS} days; taking over"

    # Creating side.
    cand = Candidate(person=await _person_from_request(o), score=m["score"],
                     overlap=Overlap(shared_keywords=m["shared"], they_have=m["they_have_you_dont"]),
                     why="mutual request in the whoelse network", reachable="email")
    mine_prof = load_profile(mine.name)
    if not mine_prof:
        return {**result, "status": "error", "note": "your profile is missing; run load_profile again"}
    files = build_workspace(mine_prof, cand, fmt, topic=topic, key=key)
    root = write_local(files)
    result.update({"format": fmt, "local": str(root), "role": "create"})
    if dry_run:
        return {**result, "status": "dry_run"}

    repo_url = st.get("repo")
    if not repo_url:
        try:
            # Private until the stranger says "in": their name must not appear in public on the
            # strength of a registry file. They can read and push as a collaborator from day one.
            created = await create_repo(files, private=True, invite=o.ids.github)
            repo_url = created["repo"]
            result["invited"] = created.get("invited")
        except SourceError as e:
            result["repo"] = f"not created: {e}"
    if repo_url:
        result["repo"] = repo_url
    online = bool(repo_url)

    if not st.get("told_you"):
        body = (f"{o.name} wants the same thing you do: {topic}.\n\n"
                + (f"The work has started: {repo_url}\n\n" if online else f"The workspace is ready locally: {root}\n\n")
                + "Section 1 is drafted from both of your papers where they exist, the table has the published numbers, "
                  "the plan is 14 days.\n")
        if not online:
            body += ("\nThe repository could not be created on GitHub (see above), so the other side has NOT been told. "
                     "Set GITHUB_TOKEN and run whoelse-watch again, or push the folder to GitHub under the name "
                     f"'{expected}'; the watcher will find it and notify them.\n")
        try:
            result["notified_you"] = notify(f"whoelse: joint work with {o.name}", body, mine.contact)
        except Exception as e:  # noqa: BLE001
            result["notified_you"] = f"failed: {e}"
        state[pair] = {**st, "role": "create", "told_you": True, "repo": repo_url, "local": str(root)}
        save_state(state)

    if not online:
        # maybe the user pushed it by hand since last time
        me_login = None
        try:
            me_data = await http.get_json("https://api.github.com/user", headers=gh._headers(), fixture_name="github_me", cache_hours=0)
            me_login = (me_data or {}).get("login")
        except SourceError:
            pass
        if me_login:
            url = await _repo_exists(f"{me_login}/{expected}")
            if url:
                repo_url, online = url, True
                result["repo"] = url
    if online and not st.get("told_them"):
        body2 = (f"{mine.name} works on the same problem as you ({topic}) and has started a joint "
                 f"{fmt.replace('_', ' ')} with your name on it:\n\n{repo_url}\n\n"
                 f"Section 1 is drafted from both papers where they exist; the plan is 14 days. The repository is private "
                 f"to the two of us until you say so. To join, accept the invitation and open an issue titled \"in\". "
                 f"To decline, ignore this; the work will be finished alone, made public without your name, with a citation to yours.\n")
        try:
            result["notified_them"] = notify(f"{mine.name} started joint work with you: {fmt.replace('_', ' ')}", body2, o.contact)
            state[pair] = {**state.get(pair, {}), "told_them": True, "repo": repo_url, "done": True, "at": date.today().isoformat()}
        except Exception as e:  # noqa: BLE001
            result["notified_them"] = f"failed: {e}"
        save_state(state)
    elif not online:
        result["notified_them"] = "not yet: no public repository to link"
    result["status"] = "done" if state.get(pair, {}).get("done") else "pending"
    return result


async def one_pass(*, me_name: str | None = None, dry_run: bool = False) -> list[dict[str, Any]]:
    """For every locally published request: read the network, match, act. Each pair is isolated;
    one failure never stops the others, and state is saved as it goes."""
    local = load_local_requests()
    if me_name:
        local = {k: v for k, v in local.items() if k == me_name or v.get("name") == me_name}
    if not local:
        return [{"note": "no published request on this machine; run publish_request first"}]
    try:
        others = await list_requests()
    except SourceError as e:
        return [{"error": str(e)}]
    state = load_state()
    events: list[dict[str, Any]] = []
    from .network import parse_request
    for key, raw in local.items():
        mine = parse_request(raw)
        if not mine:
            events.append({"name": raw.get("name", key), "note": "local request does not satisfy the schema; run publish_request again"})
            continue
        if not (raw.get("_published") or {}).get("pr"):
            events.append({"name": mine.name, "warning": "your request is saved locally but not confirmed in the registry; others cannot see you yet"})
        matches = match_requests(mine, others)
        events.append({"name": mine.name, "network": len(others), "matches": len(matches),
                       "auto_start": sum(1 for x in matches if x["auto_start"])})
        for m in matches[:3]:
            try:
                events.append(await _handle_pair(mine, m, state, dry_run=dry_run))
            except Exception as e:  # noqa: BLE001
                events.append({"pair": "|".join(sorted([mine.name, m["request"].name])), "status": "error", "error": f"{type(e).__name__}: {e}"})
            save_state(state)
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
        try:
            events = asyncio.run(one_pass(me_name=a.name, dry_run=a.dry_run))
        except Exception as e:  # noqa: BLE001
            events = [{"error": f"{type(e).__name__}: {e}"}]
        print(json.dumps(events, indent=2, ensure_ascii=False, default=str))
        if not interval:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
