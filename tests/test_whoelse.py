from __future__ import annotations

import json

import pytest

from whoelse import server
from whoelse.brief import joint_work_brief, outreach_skeleton
from whoelse.match import find_overlaps
from whoelse.profile import build_profile, load_profile, save_profile
from whoelse.sources import arxiv, card, openalex


def test_openalex_abstract_reconstruction():
    idx = {"hello": [0], "world": [1]}
    assert openalex.abstract_from_inverted(idx) == "hello world"


def test_arxiv_parse_feed():
    xml = (open("tests/fixtures/arxiv_au_vladimir_beskorovainyi.json").read())
    text = json.loads(xml)["__text__"]
    entries = arxiv.parse_feed(text)
    assert entries[0]["id"] == "2604.03672v1"
    assert "Beskorovainyi" in entries[0]["authors"][0]


def test_card_url():
    assert card.card_url_for("http://amine.io/") == "http://amine.io/.well-known/whoelse.json"
    assert card.card_url_for("vladimir.besk.tech") == "https://vladimir.besk.tech/.well-known/whoelse.json"
    assert card.card_url_for("") is None


async def test_build_profile_merges_sources():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    kinds = {a.kind for a in prof.assets}
    assert kinds == {"paper", "repo"}
    # arXiv duplicate of W1 is merged
    titles = [a.title for a in prof.assets]
    assert sum("Appeals Processor" in t for t in titles) == 1
    assert "T10181" in prof.topic_ids and "T12345" in prof.topic_ids
    assert "text-to-sql" in prof.keywords
    # ORCID public email came through, with provenance
    assert prof.contact.email == "vladimir@besk.tech"
    assert prof.contact.provenance["email"] == "orcid public email"
    assert prof.contact.website == "https://vladimir.besk.tech"
    save_profile(prof)
    assert load_profile("Vladimir Beskorovainyi").name == prof.name


async def test_find_overlaps_ranks_and_enriches():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    cands = await find_overlaps(prof, limit=10)
    names = [c.person.name for c in cands]
    # I am not my own candidate
    assert "Vladimir Beskorovainyi" not in names
    # Topic-overlap people are present
    assert "Paolo Papotti" in names and "Amine Mhedhbi" in names and "Alejandro Peña" in names
    amine = next(c for c in cands if c.person.name == "Amine Mhedhbi")
    # ORCID enrichment found a public email and his site, and his site has a whoelse card
    assert amine.person.contact.email == "amine.mhedhbi@polymtl.ca"
    assert amine.reachable == "card"
    assert amine.person.card and "joint benchmark" in amine.person.card.open_to
    # Papotti: GitHub owner 'ppapotti' merged into the OpenAlex person by name via github user profile
    papotti = next(c for c in cands if c.person.name == "Paolo Papotti")
    assert papotti.person.contact.github == "https://github.com/ppapotti"
    assert papotti.reachable == "website"
    # David Graus: limited-visibility email must NOT leak
    graus = next(c for c in cands if c.person.name == "David Graus")
    assert graus.person.contact.email is None
    assert graus.person.contact.website == "https://graus.nu/"
    # Scores are sorted, card bonus puts Amine near the top
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)
    assert names.index("Amine Mhedhbi") <= 2


async def test_brief_and_outreach():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    cands = await find_overlaps(prof, limit=10)
    amine = next(c for c in cands if c.person.name == "Amine Mhedhbi")
    brief = joint_work_brief(prof, amine)
    assert brief["them"]["card"]["contact"] == "amine.mhedhbi@polymtl.ca"
    assert brief["formats"][0]["id"] in {"joint_benchmark", "compare_note", "talk_together", "shared_dataset", "merge_tools", "replication", "review_each_other"}
    assert "contact_provenance" in brief and brief["contact_provenance"]["email"] == "orcid public email"
    sk = outreach_skeleton(prof, amine, "joint_benchmark")
    assert sk["to"] == "amine.mhedhbi@polymtl.ca"
    assert sk["facts"]["format"]["id"] == "joint_benchmark"
    assert any("one person at a time" in r for r in sk["rules"])


async def test_server_tools_end_to_end():
    r = await server.load_profile("Vladimir Beskorovainyi", github="besk-tech")
    assert r["assets"]["paper"] == 3 and r["assets"]["repo"] == 2
    r = await server.find_overlaps("Vladimir Beskorovainyi", limit=5)
    assert r["count"] == 5 and r["connected"]
    idx = next(c["index"] for c in r["candidates"] if c["name"] == "Amine Mhedhbi")
    brief = await server.joint_work_brief("Vladimir Beskorovainyi", idx)
    assert brief["them"]["name"] == "Amine Mhedhbi"
    draft = await server.draft_outreach("Vladimir Beskorovainyi", idx, "compare_note")
    assert draft["subject"].startswith("Comparison note")
    with pytest.raises(ValueError):
        await server.draft_outreach("Vladimir Beskorovainyi", idx, "spam_everyone")
    peer = await server.add_peer("Vladimir Beskorovainyi", idx, "SQL routing")
    assert peer["name"] == "Amine Mhedhbi"
    known = await server.list_known()
    assert known["peers"][0]["name"] == "Amine Mhedhbi"
    cardj = await server.make_card("Vladimir Beskorovainyi", ["text-to-SQL"], ["co-author"], "vladimir@besk.tech")
    assert json.loads(cardj["json"])["open_to"] == ["co-author"]
    assert (await server.remove_peer("Amine Mhedhbi"))["removed"] is True


async def test_tools_are_listed():
    tools = {t.name for t in await server.mcp.list_tools()}
    assert {"load_profile", "find_overlaps", "joint_work_brief", "draft_outreach", "whats_new_from_peers", "make_card"} <= tools


async def test_namesakes_are_not_guessed():
    r = await server.load_profile("Li Wei")
    assert r["status"] == "ambiguous" and len(r["options"]) == 3
    assert r["options"][0]["institutions"] == "Peking University | Peking University"
    # pinned by ORCID it resolves
    r = await server.load_profile("Li Wei", orcid="0000-0002-2222-3333")
    assert r["ids"]["openalex"] == "A5000000102"
    # pinned by affiliation hint it resolves too
    r = await server.load_profile("Li Wei", affiliation_hint="tsinghua")
    assert r["ids"]["openalex"] == "A5000000102"


async def test_keyword_walk_finds_people_topics_miss():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    assert "keywords/text-to-sql" in prof.keyword_ids
    cands = await find_overlaps(prof, limit=15)
    names = [c.person.name for c in cands]
    assert "Nikhil Rao" in names  # only reachable through the keyword filter
    rao = next(c for c in cands if c.person.name == "Nikhil Rao")
    assert rao.reachable == "email" and rao.person.contact.provenance["email"] == "orcid public email"
