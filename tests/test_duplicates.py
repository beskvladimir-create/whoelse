"""Before you build it: what exists, who won, what nobody has; and the merge proposal."""
from __future__ import annotations

import pytest
from whoelse.http import SourceError
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
    assert "tawanorg/claude-sync (320 stars)" in d["verdict"]
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


def _row(repo, stars, pushed="2026-11-01", archived=False, issues_disabled=False):
    return {"repo": repo, "url": f"https://github.com/{repo}", "stars": stars, "pushed": pushed, "owner": repo.split("/")[0],
            "only_here": [], "features": [], "archived": archived, "issues_disabled": issues_disabled}


def _dup(rows):
    return {"idea": "sync sessions", "cluster": rows, "total_stars": sum(r["stars"] for r in rows), "median_stars": 3,
            "features_nobody_has": []}


def test_merge_plan_limits_cluster_and_skips_archived_and_no_issues():
    rows = [_row(f"u{i}/r{i}", 100 - i, pushed=f"2026-10-{(i % 28) + 1:02d}") for i in range(20)]
    rows[5]["archived"] = True
    rows[6]["issues_disabled"] = True
    plan = dup.merge_plan(_dup(rows))
    assert plan["truncated_to"] == dup.MAX_CLUSTER_FOR_MERGE
    assert plan["base"] == "u0/r0"
    repos = [i["repo"] for i in plan["issues"]]
    assert "u5/r5" not in repos and "u6/r6" not in repos
    assert len(repos) <= dup.MAX_CLUSTER_FOR_MERGE
    assert any(r in repos for r in ("u1/r1", "u2/r2"))


def test_merge_plan_refuses_tiny_cluster():
    with pytest.raises(ValueError):
        dup.merge_plan(_dup([_row("a/x", 3), _row("b/y", 2)]))


def test_issue_text_inline_plan_or_url_and_honest_stars():
    rows = [_row("lead/sync", 320), _row("a/x", 3), _row("b/y", 2)]
    inline = dup.merge_plan(_dup(rows))
    assert "# Merge plan" in inline["issues"][0]["body"]
    assert "320 stars" in inline["issues"][0]["body"]
    assert "(link to" not in inline["issues"][0]["body"]
    linked = dup.merge_plan(_dup(rows), plan_url="https://github.com/me/plan")
    assert "https://github.com/me/plan" in linked["issues"][0]["body"]
    assert "# Merge plan" not in linked["issues"][0]["body"]


@pytest.mark.asyncio
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
