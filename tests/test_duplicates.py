"""Before you build it: what exists, who won, what nobody has; and the merge proposal."""
from __future__ import annotations

from whoelse import duplicates as dup
from whoelse import server


async def test_find_duplicates_ranks_cluster_and_drops_noise():
    d = await dup.find_duplicates("sync Claude Code sessions across machines")
    names = [r["repo"] for r in d["cluster"]]
    assert "tawanorg/claude-sync" in names and "chrisdoc/hevy-mcp" not in names  # fitness app is not a duplicate
    assert d["leader"]["repo"] == "tawanorg/claude-sync" and d["leader"]["stars"] == 320
    assert d["count"] >= 7 and d["median_stars"] <= 4
    feats = {r["repo"]: r["features"] for r in d["cluster"]}
    assert "encryption" in feats["tawanorg/claude-sync"]
    assert "cloud drive" in feats["Vincentvn28/claude-session-sync"]
    assert "remote" in feats["ikook-wang/cc-sync"]
    # pieces only one repo has are what a merge collects
    only = {r["repo"]: r["only_here"] for r in d["cluster"]}
    assert "cloud drive" in only["Vincentvn28/claude-session-sync"]
    assert "exists" in d["verdict"] and "median" in d["verdict"]


async def test_verdict_names_the_winner_when_there_is_one():
    d = await dup.find_duplicates("sync Claude Code sessions across machines")
    # no repo >= 500 stars in the cluster -> "none above N" phrasing
    assert "none above 320" in d["verdict"]
    d2 = await dup.find_duplicates("sync Claude Code sessions across machines", max_stars=10)
    assert all(r["stars"] <= 10 for r in d2["cluster"])


async def test_nothing_found_is_said_plainly():
    d = await dup.find_duplicates("a todo app", months=24)
    assert d["count"] == 0 and "Nothing close" in d["verdict"]


async def test_merge_plan_has_base_contributions_and_issue_per_author():
    d = await dup.find_duplicates("sync Claude Code sessions across machines")
    plan = dup.merge_plan(d)
    assert plan["base"] == "tawanorg/claude-sync"  # the living leader keeps its stars and users
    assert len(plan["issues"]) == d["count"] and all(i["body"].startswith("Hi ") for i in plan["issues"])
    assert set(plan["contributions"]) == {r["repo"] for r in d["cluster"] if r["repo"] != plan["base"]}
    assert "Nothing is deleted" in plan["plan_md"] and "every author is a maintainer" in plan["plan_md"].lower()
    assert any("No issue is opened without the user's explicit yes" in r for r in plan["rules"])


async def test_server_tools_do_not_open_issues_without_yes():
    r = await server.find_duplicates("sync Claude Code sessions across machines")
    assert r["count"] >= 7
    m = await server.propose_merge("sync Claude Code sessions across machines")
    assert "opened" not in m and "next" in m and len(m["plan"]["issues"]) == r["count"]
    m2 = await server.propose_merge("sync Claude Code sessions across machines", open_issues=True)
    assert all("error" in o and "offline" in o["error"] for o in m2["opened"])  # offline: nothing goes out
