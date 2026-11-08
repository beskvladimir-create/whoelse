"""Don't build it alone: what exists, who won, what nobody has; and the merge proposal."""
from __future__ import annotations

import pytest
from whoelse.http import SourceError
from whoelse import duplicates as dup
from whoelse import server

IDEA = "sync Claude Code sessions across machines"


async def test_find_duplicates_ranks_cluster_and_drops_noise():
    d = await dup.find_duplicates(IDEA)
    names = [r["repo"] for r in d["cluster"]]
    assert "tawanorg/claude-sync" in names and "chrisdoc/hevy-mcp" not in names  # fitness app is not a duplicate
    assert d["leader"]["repo"] == "tawanorg/claude-sync" and d["leader"]["stars"] == 320
    assert d["count"] >= 6 and d["median_stars"] <= 4
    feats = {r["repo"]: r["features"] for r in d["cluster"]}
    assert "encryption" in feats["tawanorg/claude-sync"]
    assert "cloud drive" in feats["Vincentvn28/claude-session-sync"]
    assert "remote" in feats["ikook-wang/cc-sync"]
    only = {r["repo"]: r["only_here"] for r in d["cluster"]}
    assert "cloud drive" in only["Vincentvn28/claude-session-sync"]
    assert not any(f.startswith("license") for fs in only.values() for f in fs)   # a licence is not a feature to port
    assert "tawanorg/claude-sync (320 stars" in d["verdict"] and "median" in d["verdict"]


async def test_max_stars_exclusion_is_said_not_hidden():
    d = await dup.find_duplicates(IDEA, max_stars=10)
    assert all(r["stars"] <= 10 for r in d["cluster"])
    assert d["excluded_by_max_stars"][0]["repo"] == "tawanorg/claude-sync"
    assert "tawanorg/claude-sync (320 stars) was excluded" in d["verdict"]


async def test_product_mentions_are_not_duplicates():
    # ecosystem noise mentions "Claude Code" but not the job; only the one that backs up sessions stays
    d = await dup.find_duplicates("a Claude Code plugin to back up sessions")
    names = [r["repo"] for r in d["cluster"]]
    assert "y/cc-backup" in names
    assert "thedotmack/claude-mem" not in names and "x/claude-hud" not in names
    assert "already won" not in d["verdict"]


async def test_broad_field_is_called_a_field():
    d = await dup.find_duplicates("todo app in rust")
    assert d["search_total"] == 2193 and "is a field, not a gap" in d["verdict"] and "2,193" in d["verdict"]
    assert d["count_note"]


async def test_failed_search_does_not_claim_novelty():
    d = await dup.find_duplicates("reversible pii anonymisation")   # no fixture -> every query errors
    assert d["count"] == 0 and d["source_errors"] and "search failed" in d["verdict"] and "new" not in d["verdict"].lower()


async def test_unsearchable_ideas_are_refused():
    with pytest.raises(ValueError):
        await dup.find_duplicates("Синхронизация сессий Claude Code между машинами")   # only the product survives
    with pytest.raises(ValueError):
        await dup.find_duplicates("the best tool")
    assert dup.clean_idea("sync @github-staff sessions https://evil.example\n‮now") == "sync github-staff sessions now"


def test_queries_pick_rare_words_not_long_ones():
    qs = dup._queries_for("LLM-based NL2SQL for closed-contour environments")
    assert "nl2sql" in qs and any("text-to-sql" in q for q in qs)
    qs2 = dup._queries_for("a Claude Code plugin to back up sessions")
    assert "claude back" not in qs2 and "claude code backup" in qs2
    assert dup._queries_for("reversible PII anonymisation")[0] == "reversible pii anonymization"


async def test_merge_plan_has_base_contributions_and_issue_per_author():
    d = await dup.find_duplicates(IDEA)
    plan = dup.merge_plan(d)
    assert plan["base"] == "tawanorg/claude-sync"  # the living leader keeps its stars and users
    assert len(plan["issues"]) == d["count"] and all(i["body"].startswith("Hi ") for i in plan["issues"])
    assert set(plan["contributions"]) == {r["repo"] for r in d["cluster"] if r["repo"] != plan["base"]}
    assert "Nothing is deleted" in plan["plan_md"] and "every author is a maintainer" in plan["plan_md"].lower()
    base_issue = next(i for i in plan["issues"] if i["repo"] == plan["base"])
    assert "as the base, because" in base_issue["body"]
    assert "(link to" not in base_issue["body"] and "# Merge plan" in base_issue["body"]   # plan inline when no URL
    import re
    assert "320 stars" in plan["plan_md"] and not re.search(r"\b1 stars", plan["plan_md"])


async def test_server_binds_approval_to_shown_texts():
    r = await server.find_duplicates(IDEA)
    assert r["count"] >= 6
    m = await server.propose_merge(IDEA)
    assert "opened" not in m and "next" in m and m["plan_id"] in m["next"] and len(m["plan"]["issues"]) == r["count"]
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError):
        await server.propose_merge(IDEA, open_issues=True)                       # no plan_id: nothing goes out
    with pytest.raises(ToolError):
        await server.propose_merge(IDEA, open_issues=True, plan_id="nope")       # unknown plan_id
    m2 = await server.propose_merge(IDEA, open_issues=True, plan_id=m["plan_id"])
    assert m2["opened_count"] == 0 and all("offline" in o["error"] for o in m2["opened"])   # offline: nothing goes out


def _row(repo, stars, pushed="2026-11-01", **kw):
    r = {"repo": repo, "url": f"https://github.com/{repo}", "stars": stars, "pushed": pushed, "owner": repo.split("/")[0],
         "only_here": [], "features": [], "summary": "does the thing", "archived": False, "issues_disabled": False, "fork": False, "owner_type": "User"}
    r.update(kw)
    return r


def _dup(rows):
    return {"idea": "sync sessions", "cluster": rows, "features_nobody_has": []}


def test_merge_plan_skips_ineligible_and_names_why():
    rows = [_row(f"u{i}/r{i}", 20 - i) for i in range(9)]
    rows[1]["archived"] = True
    rows[2]["issues_disabled"] = True
    rows[3]["fork"] = True
    rows[4]["owner_type"] = "Organization"
    rows[5]["stars"] = 5000
    plan = dup.merge_plan(_dup(rows), me="u6")
    repos = {i["repo"] for i in plan["issues"]}
    assert repos == {"u0/r0", "u7/r7", "u8/r8"}
    assert set(plan["skipped"]) == {"u1/r1", "u2/r2", "u3/r3", "u4/r4", "u5/r5", "u6/r6"}
    assert "won" in plan["skipped"]["u5/r5"] and "own" in plan["skipped"]["u6/r6"]


def test_merge_plan_refuses_tiny_and_bulk_clusters():
    with pytest.raises(ValueError, match="at least 3"):
        dup.merge_plan(_dup([_row("a/x", 3), _row("b/y", 2)]))
    with pytest.raises(ValueError, match="mailing"):
        dup.merge_plan(_dup([_row(f"u{i}/r{i}", 5) for i in range(16)]))


def test_issue_text_links_plan_url_and_lists_peers_whole():
    rows = [_row(f"u{i}/r{i}", 15 - i) for i in range(15)]
    plan = dup.merge_plan(_dup(rows), plan_url="https://github.com/me/plan")
    body = plan["issues"][-1]["body"]
    assert "https://github.com/me/plan" in body and "# Merge plan" not in body
    assert "and 4 more" in body and body.count("](https://github.com/") == 10   # never cut mid-link
    assert "no description; ask" in dup.merge_plan(_dup([_row("a/x", 3), _row("b/y", 2, summary=""), _row("c/z", 1)]))["plan_md"]


async def test_open_issue_ledger_blocks_repeats_and_daily_cap(tmp_path, monkeypatch):
    from whoelse import config
    monkeypatch.setenv("WHOELSE_HOME", str(tmp_path))
    monkeypatch.setenv("WHOELSE_FIXTURES", "")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    config.reset_settings()
    try:
        from datetime import date
        today = date.today().isoformat()
        dup._ledger_save({"a/x": {"date": today, "issue": "u"}})
        with pytest.raises(SourceError, match="already asked"):
            await dup.open_issue("a", "x", "t", "b")
        dup._ledger_save({f"o{i}/r": {"date": today, "issue": "u"} for i in range(dup.MAX_ISSUES_PER_DAY)})
        with pytest.raises(SourceError, match="daily cap"):
            await dup.open_issue("new", "r", "t", "b")
    finally:
        config.reset_settings()


def test_rate_limit_detection():
    class R:
        def __init__(self, code, headers=None, text=""):
            self.status_code, self.headers, self.text = code, headers or {}, text
    assert dup._rate_limited(R(429)) and dup._rate_limited(R(403, {"Retry-After": "60"}))
    assert dup._rate_limited(R(403, text="You have exceeded a secondary rate limit"))
    assert not dup._rate_limited(R(403, text="Issues are disabled for this repo")) and not dup._rate_limited(R(201))


async def test_empty_cluster_with_related_field_is_not_called_new():
    d = await dup.find_duplicates("sync Claude Code sessions to a wearable")   # nobody does the wearable part
    assert d["count"] == 0 and d["related"]["count"] >= 6
    assert "specific part looks new; the general part is not" in d["verdict"]


async def test_non_result_search_response_is_an_error_not_novelty(monkeypatch):
    from whoelse.sources import github as gh
    async def bad(*a, **k):
        return "oops"
    monkeypatch.setattr(gh.http, "get_json", bad)
    d = await dup.find_duplicates(IDEA)
    assert d["count"] == 0 and d["source_errors"] and "search failed" in d["verdict"]


async def test_broad_field_cannot_become_a_merge_proposal():
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="field, not a cluster"):
        await server.propose_merge("todo app in rust")


def test_verdict_median_is_of_the_others():
    from whoelse.models import Asset
    from datetime import date
    mk = lambda n, s: Asset(kind="repo", title=n, url="", source="github", summary="x", date=date.today(), stats={"stars": s})  # noqa: E731
    cl = [mk("a/lead", 80), mk("b/x", 4), mk("c/y", 3), mk("d/z", 2)]
    v = dup._verdict("i", cl, [80, 4, 3, 2], cl[0], months=6, broad=False, total=4, errors=[], excluded=None, capped=False)
    assert "the other 3 have a median of 3" in v


def test_inactive_repos_are_not_asked_and_name_never_empty():
    rows = [_row(f"u{i}/r{i}", 5) for i in range(4)]
    rows[0]["pushed"] = "2025-01-01"
    plan = dup.merge_plan(_dup(rows))
    assert "inactive" in plan["skipped"]["u0/r0"]
    d = _dup([_row(f"u{i}/r{i}", 5) for i in range(3)]); d["idea"] = "!!! ???"
    assert dup.merge_plan(d)["name"] == dup.merge_plan(d)["base"]


def test_hyphen_parts_count_once_and_actions_are_required():
    from whoelse.models import Asset
    from datetime import date
    mk = lambda n, d_: Asset(kind="repo", title=n, url="", source="github", summary=d_, date=date.today(), stats={"stars": 1})  # noqa: E731
    toks = dup._tokens("a Chrome extension that blocks AI-generated images")
    groups = dup._job_groups(toks)
    assert sum(1 for g in groups if "ai-generated" in g) == 1 and len([g for g in groups if g & {"ai", "generated", "ai-generated"}]) == 1
    sim, hit = dup._similarity_hits(set(dup._job_tokens(toks)), mk("x/git-ai", "Track AI-generated code in your repos"), groups)
    assert len(hit) == 1                      # ai-generated counted once, not three times
    assert "block" in dup._actions_in("a Chrome extension that blocks AI-generated images")
    assert not dup._actions_in("Track AI-generated code in your repos") & {"block"}
    assert "convert" in dup._actions_in("converts notebooks") and "convert" in dup._actions_in("A notebook exporter")


def test_batch_takes_leader_plus_most_recent_and_defers_the_rest():
    rows = [_row(f"u{i}/r{i}", 1, pushed=f"2026-{(i % 5) + 6:02d}-15") for i in range(30)]
    rows[0]["stars"] = 300
    rows[0]["pushed"] = "2026-11-01"
    with pytest.raises(ValueError, match="batch=true"):
        dup.merge_plan(_dup(rows))
    plan = dup.merge_plan(_dup(rows), batch=True)
    assert plan["base"] == "u0/r0" and len(plan["issues"]) == dup.MAX_CLUSTER_FOR_MERGE
    assert plan["issues"][0]["title"].startswith("30 of us") and "this round asks 15" in plan["issues"][1]["body"]
    assert len(plan["deferred"]) == 30 - dup.MAX_CLUSTER_FOR_MERGE


async def test_distinctive_word_required_and_verb_not_counted():
    # "sessions to a wearable": the sync-session repositories share sessions and sync but not the wearable part
    d = await dup.find_duplicates("sync Claude Code sessions to a wearable")
    assert d["count"] == 0
    # the verb ("generator") is required but does not count as a job word: a note-UID generator for Obsidian is not a static site generator
    from whoelse.models import Asset
    from datetime import date
    toks = dup._tokens("a static site generator for Obsidian vaults")
    groups = dup._job_groups(toks)
    core = [g for g in groups if not all(dup._ACTION_FORMS.get(t) for t in g)]
    assert {"generator"} not in core and {"vault"} in core
