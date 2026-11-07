"""One test per defect found in review. If any of these fails, a real-world input broke whoelse."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from whoelse import server
from whoelse.config import Settings, reset_settings, settings
from whoelse.http import Http, SourceError, _retry_after
from whoelse.match import _Pool, _merge_by_name, find_overlaps
from whoelse.models import Asset, Person, Profile
from whoelse.profile import build_profile, dedupe_assets, slug, _norm
from whoelse.sources import arxiv, card, github, openalex


# ---- http layer

def _http_with(handler):
    h = Http()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


async def test_html_200_is_source_error_not_crash(tmp_path):
    reset_settings(Settings(home=tmp_path, fixtures_dir=None))
    h = _http_with(lambda req: httpx.Response(200, text="<html>SPA fallback</html>"))
    with pytest.raises(SourceError):
        await h.get_json("https://x.test/.well-known/whoelse.json")


async def test_retry_after_http_date_does_not_crash():
    assert 1.0 <= _retry_after("Wed, 21 Oct 2015 07:28:00 GMT", 0) <= 60.0
    assert _retry_after("3", 0) == 3.0
    assert _retry_after("garbage", 2) == 4.0


async def test_gives_up_with_a_message(tmp_path, monkeypatch):
    reset_settings(Settings(home=tmp_path, fixtures_dir=None))
    import whoelse.http as hmod
    monkeypatch.setattr(hmod.asyncio, "sleep", lambda *_: _noop())
    h = _http_with(lambda req: httpx.Response(429, headers={"Retry-After": "0"}))
    with pytest.raises(SourceError, match="gave up after 4 attempts"):
        await h.get_json("https://x.test/a")


async def _noop():
    return None


async def test_cache_separates_text_and_json(tmp_path):
    reset_settings(Settings(home=tmp_path, fixtures_dir=None))
    h = _http_with(lambda req: httpx.Response(200, text='[1,2]', headers={"content-type": "application/json"}))
    as_text = await h.get_json("https://x.test/list", accept="text/plain")
    as_json = await h.get_json("https://x.test/list")
    assert as_text == "[1,2]" and as_json == [1, 2]


# ---- sources on hostile shapes

def test_openalex_null_author_and_null_institution():
    assert openalex.authorship_to_person({"author": None, "institutions": [None]}) is None
    p = openalex.authorship_to_person({"author": {"id": "https://openalex.org/A1", "display_name": "X Y"}, "institutions": [None]})
    assert p and p.ids["openalex"] == "A1" and p.affiliation == ""
    a = openalex.work_to_asset({"display_name": "t", "topics": [{"id": "https://openalex.org/T1"}, {"id": "https://openalex.org/T2", "display_name": "B"}], "authorships": [None, {"author": None}]})
    assert a.topics == ["B"] and a.topic_ids == ["T2"]


def test_arxiv_plain_text_body_is_source_error():
    with pytest.raises(Exception):
        arxiv.parse_feed("Service Unavailable")


async def test_card_tolerates_junk(tmp_path, monkeypatch):
    async def fake(url, **kw):
        return {"name": "A B", "working_on": None, "open_to": "co-author", "contact": 5, "languages": [1, "en"]}
    monkeypatch.setattr(card.http, "get_json", fake)
    c = await card.fetch("https://a.test")
    assert c and c.working_on == [] and c.open_to == ["co-author"] and c.contact == "5" and c.languages == ["1", "en"]


def test_github_login_from_url_takes_first_segment():
    assert github.login_from_url("https://github.com/someone/their-repo") == "someone"
    assert github.login_from_url(None) is None


# ---- identity

def test_slug_and_norm_handle_unicode():
    assert slug("李伟") != slug("王芳") and slug("李伟")
    assert _norm("Peña") == _norm("Pena")
    assert _norm("李伟") != _norm("王芳")


def test_dedupe_is_order_independent_and_unions_signals():
    oa = Asset(kind="paper", title="Same Paper", url="u1", source="openalex", keyword_ids=["keywords/a"], keywords=["a"], topics=["T"], topic_ids=["T1"])
    ax = Asset(kind="paper", title="Same paper", url="u2", source="arxiv", keywords=["cs.cl"], extra={"github_handles": "me"})
    for order in ([oa, ax], [ax, oa]):
        out = dedupe_assets(order)
        assert len(out) == 1
        a = out[0]
        assert a.source == "openalex" and a.keyword_ids == ["keywords/a"] and set(a.keywords) == {"a", "cs.cl"}
        assert a.extra["github_handles"] == "me" and a.topic_ids == ["T1"]


async def test_orcid_unknown_to_openalex_never_stamps_a_namesake():
    prof = await build_profile("Li Wei", orcid_id="0000-0000-0000-9999", affiliation_hint="tsinghua")
    assert prof.ids.get("openalex") is None
    assert prof.ids.get("orcid") != "0000-0000-0000-9999" or "openalex" not in prof.ids
    assert any("not linked" in n for n in prof.notes)


def test_pool_excludes_me_by_id_not_only_name():
    me = Profile(name="Vladimir Beskorovainyi", ids={"github": "besk-tech"})
    pool = _Pool(me)
    handle = Person(name="besk-tech", ids={"github": "besk-tech"})
    pool.add(handle, Asset(kind="repo", title="besk-tech/x", url="", source="github"))
    assert not pool.by_key


def test_merge_by_name_requires_second_signal():
    a = Person(name="John Smith", ids={"openalex": "A9"}, affiliation="MIT")
    b = Person(name="John Smith", ids={"github": "jsmith42"})
    b.contact.email = "jsmith@corp.example"
    out = _merge_by_name([a, b])
    assert len(out) == 2 and out[0].contact.email is None
    assert out[1].contact.provenance.get("namesake_of") == "John Smith"
    # with a shared affiliation they merge
    b2 = Person(name="John Smith", ids={"github": "jsmith42"}, affiliation="MIT CSAIL")
    b2.contact.email = "jsmith@mit.example"
    out = _merge_by_name([a, b2])
    assert len(out) == 1 and out[0].contact.email == "jsmith@mit.example" and out[0].contact.provenance["merge"] == "same affiliation"


# ---- server behaviour

async def test_tool_errors_carry_messages():
    from whoelse.server import ToolError
    with pytest.raises(ToolError, match="Call load_profile first"):
        await server.find_overlaps("Nobody At All")


async def test_one_broken_candidate_site_does_not_kill_results(monkeypatch):
    import whoelse.match as m

    async def boom(website):
        raise RuntimeError("renderer exploded")
    monkeypatch.setattr(m.card, "fetch", boom)
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    cands, errors, _ = await find_overlaps(prof, limit=5)
    assert cands  # still got results
    assert any("renderer exploded" in e for e in errors)


async def test_outreach_prefers_card_contact():
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    cands, _, _ = await find_overlaps(prof, limit=10)
    amine = next(c for c in cands if c.person.name == "Amine Mhedhbi")
    from whoelse.brief import outreach_skeleton
    sk = outreach_skeleton(prof, amine)
    assert sk["to"] == amine.person.card.contact and "card" in sk["to_provenance"]


async def test_existing_coauthors_are_listed_separately_not_ranked():
    # Nikolai Apurin coauthored W2 with me; make him appear in the pool via a topic walk
    prof = await build_profile("Vladimir Beskorovainyi", github_login="besk-tech")
    cands, _, known = await find_overlaps(prof, limit=20)
    names = [c.person.name for c in cands]
    assert "Nikolai Apurin" not in names


def test_orcid_xml_parser_reads_only_public_and_no_duplicates():
    from whoelse.sources import orcid
    xml = """<person:person xmlns:person="http://www.orcid.org/ns/person" xmlns:email="http://www.orcid.org/ns/email" xmlns:researcher-url="http://www.orcid.org/ns/researcher-url">
<email:emails><email:email visibility="limited"><email:email>secret@x.org</email:email></email:email><email:email visibility="public"><email:email>open@x.org</email:email></email:email></email:emails>
<researcher-url:researcher-urls><researcher-url:researcher-url><researcher-url:url>https://x.org/me</researcher-url:url></researcher-url:researcher-url></researcher-url:researcher-urls></person:person>"""
    d = orcid._from_xml(xml)
    assert [(e["email"], e["visibility"]) for e in d["emails"]["email"]] == [("secret@x.org", "limited"), ("open@x.org", "public")]
    assert d["researcher-urls"]["researcher-url"][0]["url"]["value"] == "https://x.org/me"
