"""The part that connects strangers: registry schema, verification, mutual match, workspace, watcher."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from whoelse import network as net
from whoelse import server
from whoelse.config import settings
from whoelse.models import Asset, Candidate, Overlap, Person
from whoelse.profile import build_profile
from whoelse.watch import load_state, one_pass, save_state
from whoelse.workspace import build_workspace, repo_name

TOPIC = "text-to-SQL on closed enterprise data"


async def _me_published():
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    r = await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech", topic=TOPIC, format_id="compare_note", confirmed=True)
    # mark as confirmed in the registry so the watcher does not warn (offline: PR cannot be opened)
    p = Path(r["saved_locally"])
    d = json.loads(p.read_text()); d["_published"] = {"pr": "https://github.com/x/pull/1"}; p.write_text(json.dumps(d))
    return r


# ---- registry and schema

async def test_registry_drops_malformed_expired_and_mismatched_files():
    reqs = await net.list_requests()
    assert {r.name for r in reqs} == {"Ana Ferreira", "Kenji Mori", "Yusuf Demir", "Yuyu Luo"}  # evil + expired dropped


def test_schema_rejects_hostile_shapes():
    bad = [
        {"name": ["a", "b"], "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}]},
        {"name": "A B", "contact": "a@b.co, c@d.co", "wants": [{"format": "compare_note", "topic": "xyz"}]},
        {"name": "A\r\nB", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}]},
        {"name": "A B", "contact": "a@b.co", "wants": ["compare_note"]},
        {"name": "A B", "contact": "a@b.co", "wants": [{"format": "spam_everyone", "topic": "xyz"}]},
        {"name": "A B", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}], "ids": {"orcid": "not-an-orcid"}},
        {"name": "A B", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}], "keywords": "text-to-sql"},
        {"name": "A B", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}], "expires": 2099},
        {"name": "A B", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}], "keywords": ["k"] * 21},
        {"name": "Solo", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}]},
    ]
    for b in bad:
        assert net.parse_request(b) is None, b
    assert net.parse_request({"name": "A B", "contact": "a@b.co", "wants": [{"format": "compare_note", "topic": "xyz"}]}) is not None


def test_match_requires_real_evidence_and_openness():
    base = {"contact": "x@y.co", "has": [], "ids": {}}
    mine = {**base, "name": "Me Myself", "keywords": ["text-to-sql"], "wants": [{"format": "compare_note", "topic": "language models for enterprise search"}]}
    generic = {**base, "name": "B B", "keywords": ["enterprise"], "wants": [{"format": "talk_together", "topic": "protein language models"}], "has": ["dataset", "repo", "model"]}
    real = {**base, "name": "C C", "keywords": ["text-to-sql"], "wants": [{"format": "compare_note", "topic": "sql generation"}]}
    closed = {**base, "name": "D D", "keywords": ["text-to-sql"], "wants": [{"format": "compare_note", "topic": "x y"}], "open_to_strangers": False}
    same_id = {**base, "name": "E E", "ids": {"github": "me"}, "keywords": ["text-to-sql"], "wants": [{"format": "compare_note", "topic": "x y"}]}
    mine["ids"] = {"github": "me"}
    ms = net.match_requests(mine, [generic, real, closed, same_id])
    assert [m["request"].name for m in ms] == ["C C"]
    assert ms[0]["auto_start"] is True


def test_phrase_in_topic_is_evidence_single_word_is_not():
    base = {"contact": "x@y.co", "has": [], "ids": {}, "keywords": []}
    mine = {**base, "name": "Me Myself", "wants": [{"format": "compare_note", "topic": "schema linking for wide tables"}]}
    other = {**base, "name": "O P", "wants": [{"format": "compare_note", "topic": "schema linking in dialog systems"}]}
    weak = {**base, "name": "Q R", "wants": [{"format": "compare_note", "topic": "wide area networks"}]}
    ms = net.match_requests(mine, [other, weak])
    assert [m["request"].name for m in ms] == ["O P"] and "schema linking" in ms[0]["shared"]


# ---- verification

async def test_impostor_with_someone_elses_orcid_is_not_verified():
    reqs = {r.name: r for r in await net.list_requests()}
    ok, why = await net.verified(reqs["Yuyu Luo"])
    assert not ok and "does not match" in why
    ok, why = await net.verified(reqs["Ana Ferreira"])
    assert ok


# ---- publish_request tool

async def test_publish_request_needs_confirmation_then_matches():
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    r = await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech", topic=TOPIC)
    assert r["status"] == "needs_confirmation" and r["will_publish_publicly"]["contact"] == "vladimir@besk.tech"
    assert not (settings().home / "network").exists()  # nothing written yet
    r = await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech", topic=TOPIC, confirmed=True)
    assert r["status"] == "saved_locally" and r["published"]["how"] == "manual"
    assert r["network_size"] == 4
    names = {m["name"] for m in r["mutual_matches"]}
    assert {"Ana Ferreira", "Yusuf Demir", "Yuyu Luo"} <= names and "Kenji Mori" not in names
    assert "Joint work can start now" in r["what_happens_now"]
    with pytest.raises(Exception):
        await server.publish_request("Vladimir Beskorovainyi", contact="not an email", topic=TOPIC, confirmed=True)


# ---- workspace

def test_repo_name_is_deterministic_ascii_and_symmetric():
    assert repo_name("Vladimir Бескоровайный", "Ana Peña", "Text-to-SQL: closed data") == repo_name("Ana Peña", "Vladimir Бескоровайный", "Text-to-SQL: closed data")
    n = repo_name("Vladimir Beskorovainyi", "Ana Ferreira", TOPIC)
    assert n == "beskorovainyi-ferreira-text-to-sql-on-closed-enterprise-data" and n.isascii()


async def test_workspace_quotes_published_numbers_and_is_honest_without_papers():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    p = Person(name='Ana "Q" Ferreira')
    p.assets = [Asset(kind="paper", title="Text-to-SQL for Open Data Portals", url="https://arxiv.org/abs/x", source="openalex", date=date(2026, 5, 1),
                      summary="We reach 71.2% execution accuracy on 1,200 portal questions with a 7B model.", coauthors=["Ana Ferreira"])]
    c = Candidate(person=p, score=1, overlap=Overlap(shared_keywords=["text-to-sql"]), why="", reachable="email")
    files = build_workspace(prof, c, "compare_note")
    paper = files["paper/paper.md"]
    assert "71.2%" in paper and "1,200" in paper and 'Ana \\"Q\\" Ferreira' in paper  # yaml-escaped
    assert "Ana Ferreira (2026)" in paper and "et al." not in paper.split("Ana Ferreira (2026)")[0][-20:]
    assert "besk-tech/askbase" in files["repro/README.md"]
    # no papers on either side: README must not claim section 1 is drafted from them
    empty = Candidate(person=Person(name="No Papers"), score=1, overlap=Overlap(shared_keywords=["text-to-sql"]), why="", reachable="email")
    from whoelse.models import Profile
    me2 = Profile(name="Me Myself")
    f2 = build_workspace(me2, empty, "compare_note")
    assert "neither side has a published abstract" in f2["README.md"]
    assert "no published work on this yet" in f2["paper/paper.md"]
    with pytest.raises(ValueError):
        build_workspace(me2, empty, "spam_everyone")


async def test_formats_get_their_own_files():
    me = __import__("whoelse.models", fromlist=["Profile"]).Profile(name="Me Myself")
    other = Candidate(person=Person(name="Other One"), score=1, overlap=Overlap(shared_keywords=["x"]), why="", reachable="email")
    f = build_workspace(me, other, "joint_benchmark")
    assert "leaderboard.md" in f and "paper/paper.md" not in f and "benchmark" in f["README.md"]
    f = build_workspace(me, other, "talk_together")
    assert "talk/outline.md" in f and "repro/run.py" not in f and "talk" in f["PLAN.md"]
    f = build_workspace(me, other, "review_each_other")
    assert "drafts/README.md" in f


async def test_start_joint_work_is_local_by_default_and_never_sends():
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    r = await server.find_overlaps("Vladimir Beskorovainyi", limit=10)
    idx = next(c["index"] for c in r["candidates"] if c["name"] == "Amine Mhedhbi")
    w = await server.start_joint_work("Vladimir Beskorovainyi", idx, "joint_benchmark")
    assert Path(w["local_folder"]).is_dir() and "not created (create_github_repo=false)" in w["repo"]
    assert w["send_this"]["to"] == "amine.mhedhbi@polymtl.ca" and w["send_this"]["to_provenance"]
    assert "do not send a local path" in w["send_this"]["body_facts"]["link"]


# ---- watcher

async def test_watcher_verifies_waits_creates_and_never_mails_a_local_path(monkeypatch):
    await _me_published()
    sent = []
    monkeypatch.setattr("whoelse.watch.notify", lambda subj, body, to: sent.append((to, subj, body)) or "stub")
    events = await one_pass()
    by_pair = {e["pair"]: e for e in events if "pair" in e}
    # impostor is refused before anything happens
    assert by_pair["Vladimir Beskorovainyi|Yuyu Luo"]["status"] == "unverified"
    # Ana sorts first: she creates; we wait and check again
    assert by_pair["Ana Ferreira|Vladimir Beskorovainyi"]["status"] == "waiting"
    # Yusuf sorts after: we create (offline: repo cannot be created)
    y = by_pair["Vladimir Beskorovainyi|Yusuf Demir"]
    assert y["role"] == "create" and Path(y["local"]).is_dir() and y["status"] == "pending"
    assert y["notified_them"].startswith("not yet")
    assert [to for to, _, _ in sent] == ["vladimir@besk.tech"]
    assert "has NOT been told" in sent[0][2]
    # second pass: user is not re-mailed, state persisted
    sent.clear()
    events = await one_pass()
    assert not sent
    st = load_state()
    assert st["Vladimir Beskorovainyi|Yusuf Demir"]["told_you"] is True and not st["Vladimir Beskorovainyi|Yusuf Demir"].get("done")
    assert st["Ana Ferreira|Vladimir Beskorovainyi"]["role"] == "wait"


async def test_watcher_with_online_repo_notifies_stranger_once_and_marks_done(monkeypatch):
    await _me_published()
    sent = []
    monkeypatch.setattr("whoelse.watch.notify", lambda subj, body, to: sent.append((to, body)) or "stub")

    async def fake_create(files, invite=None, private=False):
        return {"repo": "https://github.com/besk-tech/demo", "full_name": "besk-tech/demo", "invited": invite}
    monkeypatch.setattr("whoelse.watch.create_repo", fake_create)
    events = await one_pass()
    y = [e for e in events if e.get("pair") == "Vladimir Beskorovainyi|Yusuf Demir"][0]
    assert y["status"] == "done" and y["invited"] == "ydemir"
    assert {to for to, _ in sent} == {"vladimir@besk.tech", "yusuf@boun.example"}
    assert all("https://github.com/besk-tech/demo" in b for _, b in sent)
    sent.clear()
    events = await one_pass()
    assert not sent and [e for e in events if e.get("pair") == "Vladimir Beskorovainyi|Yusuf Demir"][0]["status"] == "done"


async def test_waiting_side_takes_over_after_wait_days(monkeypatch):
    await _me_published()
    monkeypatch.setattr("whoelse.watch.notify", lambda *a: "stub")
    state = {"Ana Ferreira|Vladimir Beskorovainyi": {"role": "wait", "waiting_since": (date.today() - timedelta(days=4)).isoformat()}}
    save_state(state)
    events = await one_pass(dry_run=True)
    e = [x for x in events if x.get("pair") == "Ana Ferreira|Vladimir Beskorovainyi"][0]
    assert e["role"] == "create" and "taking over" in e["note"]
    root = Path(e["local"])
    paper = (root / "paper" / "paper.md").read_text()
    assert "Production Text-to-SQL" in paper and "Open Data Portals" in paper and "71.2%" in paper
    assert "besk-tech/askbase" in (root / "repro" / "README.md").read_text() and "anaferreira/portal-sql" in (root / "repro" / "README.md").read_text()


async def test_waiting_side_joins_when_creator_repo_appears(monkeypatch):
    await _me_published()
    sent = []
    monkeypatch.setattr("whoelse.watch.notify", lambda subj, body, to: sent.append((to, body)) or "stub")

    async def exists(full_name):
        return "https://github.com/anaferreira/" + full_name.split("/")[1] if full_name.startswith("anaferreira/") else None
    monkeypatch.setattr("whoelse.watch._repo_exists", exists)
    events = await one_pass()
    e = [x for x in events if x.get("pair") == "Ana Ferreira|Vladimir Beskorovainyi"][0]
    assert e["status"] == "joined" and e["repo"].endswith(repo_name("Vladimir Beskorovainyi", "Ana Ferreira", TOPIC))
    assert sent and sent[0][0] == "vladimir@besk.tech"


async def test_one_broken_pair_does_not_stop_the_pass(monkeypatch):
    await _me_published()
    monkeypatch.setattr("whoelse.watch.notify", lambda *a: "stub")

    async def boom(req):
        if req.name == "Yusuf Demir":
            raise RuntimeError("github down")
        return True, "ok"
    monkeypatch.setattr("whoelse.watch.verified", boom)
    events = await one_pass(dry_run=True)
    statuses = {e["pair"]: e["status"] for e in events if "pair" in e}
    assert statuses["Vladimir Beskorovainyi|Yusuf Demir"] == "error"
    assert statuses["Ana Ferreira|Vladimir Beskorovainyi"] in ("waiting", "dry_run")


def test_notify_never_forges_sender(monkeypatch, tmp_path):
    from whoelse import watch
    monkeypatch.setenv("WHOELSE_SMTP_HOST", "smtp.example")
    monkeypatch.delenv("WHOELSE_SMTP_FROM", raising=False)
    monkeypatch.delenv("WHOELSE_SMTP_USER", raising=False)
    assert watch.notify("s", "b", "someone@else.example") == "inbox"  # no From: falls back, no send
