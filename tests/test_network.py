"""The part that connects strangers: registry, mutual match, workspace, watcher."""
from __future__ import annotations

import json
from pathlib import Path

from whoelse import server
from whoelse import network as net
from whoelse.config import settings
from whoelse.models import Candidate, Overlap, Person
from whoelse.profile import build_profile
from whoelse.watch import one_pass
from whoelse.workspace import build_workspace, write_local


async def test_registry_reads_current_requests_only():
    reqs = await net.list_requests()
    names = {r["name"] for r in reqs}
    assert names == {"Ana Ferreira", "Kenji Mori", "Yusuf Demir"}  # expired one dropped


async def test_publish_request_matches_a_stranger_and_tells_the_user_to_wait():
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    r = await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech",
                                     topic="text-to-SQL on closed enterprise data", format_id="compare_note")
    assert r["network_size"] == 3
    assert {m["name"] for m in r["mutual_matches"]} == {"Ana Ferreira", "Yusuf Demir"}
    r["mutual_matches"].sort(key=lambda m: m["name"])
    assert "text-to-sql" in r["mutual_matches"][0]["shared"]
    assert r["mutual_matches"][0]["common_formats"] == ["compare_note"]
    assert r["mutual_matches"][0]["they_have_you_dont"] == ["dataset"]
    assert r["published"]["how"] == "manual" and "whoelse-network" in r["published"]["do_this"]
    assert Path(r["saved_locally"]).exists()
    assert "Joint work can start now" in r["what_happens_now"]


def test_waiting_text_is_honest_when_nobody_matches():
    req = {"wants": [{"topic": "protein folding"}], "keywords": []}
    t = net.waiting_text(req, 0, 0, "me@x.org")
    assert "first person in the network" in t and "don't remove whoelse" in t
    t = net.waiting_text(req, 37, 0, "me@x.org")
    assert "37 people are waiting" in t and "me@x.org" in t


def test_match_excludes_self_and_shared_ids():
    mine = {"name": "A B", "ids": {"github": "ab"}, "keywords": ["x"], "wants": [], "has": []}
    same_person = {"name": "A. B.", "ids": {"github": "ab"}, "keywords": ["x"], "wants": [], "has": []}
    other = {"name": "C D", "ids": {}, "keywords": ["x"], "wants": [], "has": ["repo"]}
    assert [m["request"]["name"] for m in net.match_requests(mine, [same_person, other])] == ["C D"]


async def test_workspace_is_a_third_of_a_paper_with_both_names():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    p = Person(name="Ana Ferreira")
    p.assets = [__import__("whoelse.models", fromlist=["Asset"]).Asset(
        kind="paper", title="Text-to-SQL for Open Data Portals", url="https://arxiv.org/abs/x", source="openalex", date=__import__("datetime").date(2026, 5, 1),
        summary="We reach 71.2% execution accuracy on 1,200 portal questions with a 7B model.", coauthors=["Ana Ferreira"])]
    c = Candidate(person=p, score=1, overlap=Overlap(shared_keywords=["text-to-sql"]), why="", reachable="email")
    files = build_workspace(prof, c, "compare_note")
    assert {"README.md", "paper/paper.md", "repro/run.py", "repro/README.md", "PLAN.md", "CITATION.cff", ".whoelse.json"} <= set(files)
    paper = files["paper/paper.md"]
    assert "Vladimir Beskorovainyi" in paper and "Ana Ferreira" in paper
    assert "71.2%" in paper and "1,200" in paper          # published numbers quoted, not invented
    assert "## 1. Two approaches" in paper and "## 3. One experiment" in paper
    assert "besk-tech/askbase" in files["repro/README.md"]  # my code is wired in
    assert "14-day plan" in files["PLAN.md"]
    root = write_local(files)
    assert (root / "paper" / "paper.md").exists()


async def test_start_joint_work_tool_without_token_writes_folder_and_send_facts():
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    r = await server.find_overlaps("Vladimir Beskorovainyi", limit=10)
    idx = next(c["index"] for c in r["candidates"] if c["name"] == "Amine Mhedhbi")
    w = await server.start_joint_work("Vladimir Beskorovainyi", idx, "joint_benchmark")
    assert Path(w["local_folder"]).is_dir()
    assert w["repo"].startswith("not created: offline mode")
    assert w["send_this"]["to"] == "amine.mhedhbi@polymtl.ca"
    assert "in" in w["send_this"]["body_facts"]["how_to_join"]


async def test_watcher_one_creator_per_pair_and_no_stranger_mail_without_online_repo(monkeypatch):
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech",
                                 topic="text-to-SQL on closed enterprise data", format_id="compare_note")
    sent = []
    monkeypatch.setattr("whoelse.watch.notify", lambda subj, body, to: sent.append((to, subj, body)) or "stub")
    events = await one_pass()
    by_pair = {e["pair"]: e for e in events if "pair" in e}
    # Ana sorts before Vladimir: she creates, Vladimir waits
    assert by_pair["Ana Ferreira|Vladimir Beskorovainyi"]["role"] == "wait"
    # Yusuf sorts after: Vladimir creates
    y = by_pair["Vladimir Beskorovainyi|Yusuf Demir"]
    assert y["role"] == "create" and Path(y["local"]).is_dir()
    # offline: no online repo, so the stranger is NOT emailed a local path; the user is told why
    tos = [to for to, _, _ in sent]
    assert tos == ["vladimir@besk.tech"]
    assert "has NOT been told yet" in sent[0][2]
    assert y["notified_them"].startswith("not yet")
    # pair not marked seen until the stranger is reachable, so a later run (with a repo) retries
    seen = json.loads((settings().home / "watch-seen.json").read_text())
    assert "Ana Ferreira|Vladimir Beskorovainyi" in seen and "Vladimir Beskorovainyi|Yusuf Demir" not in seen


async def test_watcher_with_online_repo_notifies_both_once(monkeypatch):
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech",
                                 topic="text-to-SQL on closed enterprise data", format_id="compare_note")
    sent = []
    monkeypatch.setattr("whoelse.watch.notify", lambda subj, body, to: sent.append((to, body)) or "stub")

    async def fake_create(files, invite=None):
        return {"repo": "https://github.com/besk/demo", "full_name": "besk/demo", "invited": invite}
    monkeypatch.setattr("whoelse.watch.create_repo", fake_create)
    events = await one_pass()
    y = [e for e in events if e.get("pair") == "Vladimir Beskorovainyi|Yusuf Demir"][0]
    assert y["repo"] == "https://github.com/besk/demo" and y["invited"] == "ydemir"
    assert {to for to, _ in sent} == {"vladimir@besk.tech", "yusuf@boun.example"}
    assert all("https://github.com/besk/demo" in b for _, b in sent)
    sent.clear()
    await one_pass()
    assert not sent  # idempotent


async def test_watcher_workspace_uses_on_topic_work_from_both_sides():
    await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    r = await server.publish_request("Vladimir Beskorovainyi", contact="vladimir@besk.tech",
                                     topic="text-to-SQL on closed enterprise data", format_id="compare_note")
    assert all(m["shared"] == ["text-to-sql"] for m in r["mutual_matches"])
    # make Vladimir the creator for Ana too, so the workspace content can be inspected
    import whoelse.watch as w
    monkeypatch_fold = w.fold
    w.fold = lambda n: {"ana ferreira": "zz"}.get(monkeypatch_fold(n), monkeypatch_fold(n))
    try:
        events = await one_pass(dry_run=True)
    finally:
        w.fold = monkeypatch_fold
    root = Path([e for e in events if e.get("pair") == "Ana Ferreira|Vladimir Beskorovainyi"][0]["local"])
    paper = (root / "paper" / "paper.md").read_text()
    assert "Production Text-to-SQL" in paper and "Open Data Portals" in paper and "71.2%" in paper
    repro = (root / "repro" / "README.md").read_text()
    assert "besk-tech/askbase" in repro and "anaferreira/portal-sql" in repro
    assert "text-to-SQL on closed enterprise data" in paper
