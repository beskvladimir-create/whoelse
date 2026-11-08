"""Builds the recorded-response fixtures used by the tests and by the offline demo.
Shapes follow the public APIs (OpenAlex, arXiv Atom, ORCID v3, GitHub REST, HF Hub).
Run: python tests/make_fixtures.py"""

from __future__ import annotations

import json
from pathlib import Path

FX = Path(__file__).parent / "fixtures"
FX.mkdir(exist_ok=True)


EMPTY_FEED = '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def put(name: str, data) -> None:
    (FX / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))


def inv(text: str) -> dict[str, list[int]]:
    idx: dict[str, list[int]] = {}
    for i, w in enumerate(text.split()):
        idx.setdefault(w, []).append(i)
    return idx


T_SQL = {"id": "https://openalex.org/T10181", "display_name": "Natural Language Interfaces to Databases", "score": 0.99}
T_LLM = {"id": "https://openalex.org/T11714", "display_name": "Large Language Models and Applications", "score": 0.8}
T_GOV = {"id": "https://openalex.org/T12345", "display_name": "Text Classification in Public Administration", "score": 0.95}
T_HTR = {"id": "https://openalex.org/T10992", "display_name": "Handwritten Text Recognition", "score": 0.9}


def work(id_, title, date, authors, topics, kws, cites, venue, abstract):
    return {
        "id": f"https://openalex.org/{id_}",
        "doi": f"https://doi.org/10.0000/{id_}",
        "display_name": title,
        "publication_date": date,
        "abstract_inverted_index": inv(abstract),
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{aid}", "display_name": an, "orcid": (f"https://orcid.org/{orc}" if orc else None)},
                "institutions": [{"display_name": inst, "country_code": cc}],
            }
            for aid, an, orc, inst, cc in authors
        ],
        "topics": topics,
        "keywords": [{"id": "https://openalex.org/keywords/" + k.replace(" ", "-"), "display_name": k, "score": 0.5} for k in kws],
        "cited_by_count": cites,
        "primary_location": {"source": {"display_name": venue}, "landing_page_url": f"https://doi.org/10.0000/{id_}"},
        "best_oa_location": {"landing_page_url": f"https://arxiv.org/abs/{id_}"},
    }


ME = ("A5000000001", "Vladimir Beskorovainyi", "0000-0002-0000-0001", "besk.tech", "GE")
PAPOTTI = ("A5000000002", "Paolo Papotti", "0000-0003-0651-4128", "EURECOM", "FR")
MHEDHBI = ("A5000000003", "Amine Mhedhbi", "0009-0000-9342-5144", "Polytechnique Montréal", "CA")
PENA = ("A5000000004", "Alejandro Peña", None, "Universidad Autónoma de Madrid", "ES")
GRAUS = ("A5000000005", "David Graus", "0000-0002-9035-7045", "University of Amsterdam", "NL")
STUDENT = ("A5000000006", "Li Wei", None, "Tsinghua University", "CN")
OLDCOAUTHOR = ("A5000000007", "Nikolai Apurin", None, "Artwell", "RU")

# --- me on OpenAlex
put(
    "openalex_authors_vladimir_beskorovainyi",
    {
        "results": [
            {
                "id": "https://openalex.org/A5000000001",
                "display_name": "Vladimir Beskorovainyi",
                "orcid": "https://orcid.org/0000-0002-0000-0001",
                "works_count": 3,
                "last_known_institutions": [{"display_name": "besk.tech", "country_code": "GE"}],
                "affiliations": [{"institution": {"display_name": "besk.tech"}}],
            }
        ]
    },
)
put(
    "openalex_works_author_A5000000001",
    {
        "results": [
            work("W1", "AI Appeals Processor: Automated Classification of Citizen Appeals in Government Services", "2026-04-03",
                 [ME], [T_GOV, T_LLM], ["citizen appeals", "text classification", "public administration", "deep learning"], 4,
                 "arXiv", "We present a production system classifying citizen appeals at federal scale with a deep learning model."),
            work("W2", "Production Text-to-SQL on Open-Weight Models for Enterprise Data Marts", "2026-01-15",
                 [ME, OLDCOAUTHOR], [T_SQL, T_LLM], ["text-to-sql", "schema linking", "open-weight models", "enterprise bi"], 2,
                 "arXiv", "A deployed NL2SQL system over 500 data marts using Qwen2.5-Coder with schema linking and execution feedback."),
            work("W3", "Machine Transcription of a Historical Scientific Archive", "2025-10-01",
                 [ME], [T_HTR], ["handwritten text recognition", "digital humanities", "archives"], 1,
                 "arXiv", "Full transcription of a historical archive using vision language models and human verification."),
        ]
    },
)

# --- topic walks
put(
    "openalex_works_topic_T10181_p1",
    {
        "results": [
            work("W10", "Think2SQL: Reinforcing LLM Reasoning for Text2SQL", "2026-04-20", [PAPOTTI, STUDENT], [T_SQL, T_LLM],
                 ["text-to-sql", "reinforcement learning", "reasoning"], 40, "VLDB",
                 "We reinforce reasoning capabilities of LLMs for text to SQL with partial rewards."),
            work("W11", "Routing Queries Across SQL Generators", "2025-11-04", [MHEDHBI], [T_SQL],
                 ["text-to-sql", "llm routing", "query optimization"], 15, "arXiv",
                 "Optimizing SQL generation via LLM routing between small and large models."),
            work("W12", "Schema Linking at Scale", "2026-06-01", [STUDENT], [T_SQL],
                 ["schema linking", "text-to-sql"], 3, "arXiv", "Schema linking for very wide enterprise schemas."),
        ]
    },
)
put(
    "openalex_works_topic_T12345_p1",
    {
        "results": [
            work("W20", "Leveraging LLMs for Topic Classification in Public Affairs", "2025-12-12", [PENA], [T_GOV, T_LLM],
                 ["public affairs", "topic classification", "large language models"], 9, "Pattern Recognition Letters",
                 "Topic classification of public affairs documents with large language models."),
            work("W21", "To Redact or Not to Redact? Local LLMs for Deliberative Process Privilege", "2026-05-10", [GRAUS], [T_GOV],
                 ["open government", "local llm", "document classification", "freedom of information"], 6, "arXiv",
                 "A local LLM approach to classifying government documents for release under FOI law."),
        ]
    },
)
put("openalex_works_topic_T11714_p1", {"results": []})
# keyword walks (the sharp path)
put("openalex_works_kw_text-to-sql_p1", {"results": [
    work("W10", "Think2SQL: Reinforcing LLM Reasoning for Text2SQL", "2026-04-20", [PAPOTTI, STUDENT], [T_SQL, T_LLM],
         ["text-to-sql", "reinforcement learning", "reasoning"], 40, "VLDB", "We reinforce reasoning for text to SQL."),
    work("W11", "Routing Queries Across SQL Generators", "2025-11-04", [MHEDHBI], [T_SQL],
         ["text-to-sql", "llm routing", "query optimization"], 15, "arXiv", "LLM routing for SQL generation."),
    work("W31", "Appeals Routing in a Federal Portal", "2026-02-02", [OLDCOAUTHOR, ME], [T_GOV], ["text-to-sql", "citizen appeals"], 1, "arXiv", "Routing appeals."),
    work("W30", "Enterprise Text-to-SQL Without a Cloud", "2026-09-09", [("A5000000030", "Nikhil Rao", "0000-0001-1111-2222", "IIT Madras", "IN")], [T_SQL],
         ["text-to-sql", "on-premise deployment", "open-weight models"], 2, "arXiv", "Text-to-SQL on premises with small open models."),
]})
for k in ("citizen-appeals", "text-classification", "public-administration", "schema-linking", "deep-learning", "open-weight-models", "enterprise-bi"):
    put(f"openalex_works_kw_{k}_p1", {"results": []})
# namesakes: three different "Li Wei"
put("openalex_authors_li_wei", {"results": [
    {"id": "https://openalex.org/A5000000101", "display_name": "Li Wei", "orcid": None, "works_count": 300, "affiliations": [{"institution": {"display_name": "Peking University"}}], "last_known_institutions": [{"display_name": "Peking University"}]},
    {"id": "https://openalex.org/A5000000102", "display_name": "Li Wei", "orcid": "https://orcid.org/0000-0002-2222-3333", "works_count": 12, "affiliations": [{"institution": {"display_name": "Tsinghua University"}}], "last_known_institutions": [{"display_name": "Tsinghua University"}]},
    {"id": "https://openalex.org/A5000000103", "display_name": "Wei Li", "orcid": None, "works_count": 40, "affiliations": [], "last_known_institutions": None},
]})
put("openalex_author_orcid_0000-0002-2222-3333", {"id": "https://openalex.org/A5000000102", "display_name": "Li Wei", "orcid": "https://orcid.org/0000-0002-2222-3333", "works_count": 12, "last_known_institutions": [{"display_name": "Tsinghua University", "country_code": "CN"}]})
put("openalex_works_author_A5000000102", {"results": []})
put("openalex_author_orcid_0000-0000-0000-9999", None)  # 404 from OpenAlex
put("arxiv_au_li_wei", {"__text__": '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'})
put("orcid_person_0000-0002-2222-3333", {"emails": {"email": []}, "researcher-urls": {"researcher-url": []}})
put("orcid_person_0000-0001-1111-2222", {"emails": {"email": [{"email": "nrao@iitm.ac.in", "visibility": "public"}]}, "researcher-urls": {"researcher-url": []}})
put("openalex_works_topic_T10992_p1", {"results": []})
put("openalex_works_search_text-to-sql", {"results": []})
put("openalex_works_search_schema_linking", {"results": []})
put("openalex_works_search_citizen_appeals", {"results": []})
put("openalex_works_search_public_administration", {"results": []})
put("openalex_works_search_text_classification", {"results": []})

# --- arXiv author feed for me
put(
    "arxiv_au_vladimir_beskorovainyi",
    {
        "__text__": """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2604.03672v1</id>
    <published>2026-04-03T00:00:00Z</published>
    <title>AI Appeals Processor: Automated Classification of Citizen Appeals in Government Services</title>
    <summary>We present a production system classifying citizen appeals.</summary>
    <author><name>Vladimir Beskorovainyi</name></author>
    <category term="cs.CL"/><category term="cs.LG"/>
  </entry>
</feed>"""
    },
)

# --- arXiv keyword search (new preprints ahead of OpenAlex)
put("arxiv_all-text-to-sql", {"__text__": """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2611.00001v1</id>
    <published>2026-11-02T00:00:00Z</published>
    <title>Tiny-SQL: a 1B model for enterprise text-to-SQL</title>
    <summary>We train a 1B model for text-to-SQL on enterprise schemas.</summary>
    <arxiv:comment>Code: https://github.com/ppapotti/tiny-sql</arxiv:comment>
    <author><name>Paolo Papotti</name></author><author><name>Giulia Rossi</name></author>
    <category term="cs.DB"/>
  </entry>
</feed>"""})
put("arxiv_all-open-weight_models", {"__text__": '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'})
put("arxiv_all-schema_linking", {"__text__": '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'})
put("arxiv_all-citizen_appeals", {"__text__": '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'})
put("arxiv_all-text_classification", {"__text__": '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'})
put("arxiv_all-public_administration", {"__text__": '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'})

# --- ORCID
put(
    "orcid_person_0000-0002-0000-0001",
    {
        "emails": {"email": [{"email": "vladimir@besk.tech", "visibility": "public"}]},
        "researcher-urls": {"researcher-url": [{"url": {"value": "https://vladimir.besk.tech"}}, {"url": {"value": "https://github.com/besk-tech"}}]},
    },
)
put(
    "orcid_person_0000-0003-0651-4128",
    {
        "emails": {"email": []},
        "researcher-urls": {"researcher-url": [{"url": {"value": "http://www.eurecom.fr/~papotti"}}, {"url": {"value": "https://github.com/ppapotti"}}]},
    },
)
put(
    "orcid_person_0009-0000-9342-5144",
    {
        "emails": {"email": [{"email": "amine.mhedhbi@polymtl.ca", "visibility": "public"}]},
        "researcher-urls": {"researcher-url": [{"url": {"value": "http://amine.io/"}}]},
    },
)
put("orcid_person_0000-0002-9035-7045", {"emails": {"email": [{"email": "secret@example.org", "visibility": "limited"}]},
                                          "researcher-urls": {"researcher-url": [{"url": {"value": "https://graus.nu/"}}]}})

# --- whoelse card published by Amine (connected mode)
put("card_amine.io", {"name": "Amine Mhedhbi", "working_on": ["LLM routing for SQL generation", "graph databases"],
                      "open_to": ["joint benchmark", "co-author"], "contact": "amine.mhedhbi@polymtl.ca", "languages": ["en", "fr"], "updated": "2026-10-01"})

# --- GitHub
put("github_user_besk-tech", {"login": "besk-tech", "name": "Vladimir Beskorovainyi", "html_url": "https://github.com/besk-tech",
                              "email": None, "blog": "vladimir.besk.tech", "company": "besk.tech", "location": "Tbilisi"})
put("github_repos_besk-tech", [
    {"full_name": "besk-tech/pii-roundtrip", "html_url": "https://github.com/besk-tech/pii-roundtrip", "description": "Reversible PII anonymisation for LLM pipelines",
     "topics": ["pii", "anonymization", "llm"], "language": "Python", "stargazers_count": 12, "forks_count": 1, "pushed_at": "2026-10-20T00:00:00Z", "owner": {"login": "besk-tech"}, "fork": False},
    {"full_name": "besk-tech/askbase", "html_url": "https://github.com/besk-tech/askbase", "description": "Text-to-SQL over enterprise data marts with open-weight models",
     "topics": ["text-to-sql", "nl2sql", "qwen"], "language": "Python", "stargazers_count": 30, "forks_count": 4, "pushed_at": "2026-09-01T00:00:00Z", "owner": {"login": "besk-tech"}, "fork": False},
])
put("github_search_text-to-sql", {"items": [
    {"full_name": "ppapotti/think2sql", "html_url": "https://github.com/ppapotti/think2sql", "description": "Code for Think2SQL", "topics": ["text-to-sql", "rl"],
     "language": "Python", "stargazers_count": 210, "forks_count": 20, "pushed_at": "2026-05-01T00:00:00Z", "owner": {"login": "ppapotti"}},
    {"full_name": "sqlbot/sqlbot", "html_url": "https://github.com/sqlbot/sqlbot", "description": "Chat with your database", "topics": ["text-to-sql", "chatbot"],
     "language": "TypeScript", "stargazers_count": 5000, "forks_count": 400, "pushed_at": "2026-11-01T00:00:00Z", "owner": {"login": "sqlbot"}},
]})
put("github_search_schema_linking", {"items": []})
put("github_search_citizen_appeals", {"items": []})
put("github_search_public_administration", {"items": []})
put("github_search_text_classification", {"items": []})
put("github_user_ppapotti", {"login": "ppapotti", "name": "Paolo Papotti", "html_url": "https://github.com/ppapotti", "email": None, "blog": "", "company": "EURECOM", "location": "Sophia Antipolis"})
put("github_user_sqlbot", {"login": "sqlbot", "name": None, "html_url": "https://github.com/sqlbot", "email": "hi@sqlbot.dev", "blog": "https://sqlbot.dev", "company": None, "location": None})
put("card_sqlbot.dev", {})
# GitHub user search by full name (the third reach channel)
put("github_users_paolo_papotti", {"total_count": 1, "items": [{"login": "ppapotti"}]})
put("github_repos_ppapotti", [
    {"full_name": "ppapotti/think2sql", "html_url": "https://github.com/ppapotti/think2sql", "description": "Code for Think2SQL: reasoning for text-to-SQL",
     "topics": ["text-to-sql"], "language": "Python", "stargazers_count": 210, "forks_count": 20, "pushed_at": "2026-05-01T00:00:00Z", "owner": {"login": "ppapotti"}, "fork": False},
])
# Alejandro Peña: unique GitHub hit but the repos are about something else -> must be rejected
put("github_users_alejandro_peña", {"total_count": 1, "items": [{"login": "apena-gamedev"}]})
put("github_repos_apena-gamedev", [
    {"full_name": "apena-gamedev/unity-shooter", "html_url": "https://github.com/apena-gamedev/unity-shooter", "description": "A Unity shooter prototype",
     "topics": ["unity", "game"], "language": "C#", "stargazers_count": 3, "forks_count": 0, "pushed_at": "2026-01-01T00:00:00Z", "owner": {"login": "apena-gamedev"}, "fork": False},
])
# David Graus: many namesakes -> must be skipped
put("github_users_david_graus", {"total_count": 7, "items": [{"login": "dgraus"}, {"login": "davidgraus"}, {"login": "graus"}]})
put("github_users_amine_mhedhbi", {"total_count": 0, "items": []})
put("hf_user_amine-io", {"type": "user", "fullname": "Amine Mhedhbi", "user": "amine-io"})
put("hf_user_defog", {"type": "org", "fullname": "Defog.ai", "user": "defog"})
put("hf_user_sqlbot", None)
put("github_users_nikhil_rao", {"total_count": 40, "items": [{"login": "nikhilrao"}, {"login": "nrao"}, {"login": "nikhil-rao"}]})
put("github_users_li_wei", {"total_count": 900, "items": [{"login": "liwei"}, {"login": "li-wei"}, {"login": "weili"}]})

# --- Hugging Face
put("hf_model_search_text-to-sql", [
    {"id": "defog/sqlcoder-7b-2", "author": "defog", "downloads": 120000, "likes": 300, "tags": ["text-to-sql", "code"], "lastModified": "2026-02-01T00:00:00Z", "pipeline_tag": "text-generation"},
])
put("hf_dataset_search_text-to-sql", [
    {"id": "amine-io/sql-routing-bench", "author": "amine-io", "downloads": 800, "likes": 12, "tags": ["text-to-sql", "benchmark"], "lastModified": "2026-08-15T00:00:00Z"},
])
for q in ("schema_linking", "citizen_appeals", "public_administration", "text_classification"):
    put(f"hf_model_search_{q}", [])
    put(f"hf_dataset_search_{q}", [])

# empty answers for the remaining discovery queries so the offline demo is silent
for q in ("nl2sql", "anonymization", "qwen", "pii"):
    put(f"openalex_works_search_{q}", {"results": []})
    put(f"github_search_{q}", {"items": []})
    put(f"hf_model_search_{q}", [])
    put(f"hf_dataset_search_{q}", [])
    put(f"arxiv_all-{q}", {"__text__": EMPTY_FEED})
# --- the network registry: three people waiting; one malicious file; one expired; one impostor
put("network_repo_beskvladimir-create_whoelse-network", {"default_branch": "main"})
put("network_tree_beskvladimir-create_whoelse-network", {"tree": [
    {"path": "README.md"},
    {"path": "people/ana-ferreira.json", "sha": "a1"}, {"path": "people/kenji-mori.json", "sha": "k1"},
    {"path": "people/expired.json", "sha": "e1"}, {"path": "people/yusuf-demir.json", "sha": "y1"},
    {"path": "people/evil.json", "sha": "v1"}, {"path": "people/yuyu-luo.json", "sha": "i1"}]})
put("network_ana-ferreira", {"name": "Ana Ferreira", "contact": "ana@ufmg.example", "site": "", "ids": {"orcid": "0000-0001-0000-0001", "github": "anaferreira"},
    "working_on": ["text-to-SQL for public data portals"], "keywords": ["text-to-sql", "open data", "portuguese"],
    "wants": [{"format": "compare_note", "topic": "text-to-SQL on closed enterprise data", "by": "2026-12-15"}],
    "has": ["paper", "dataset"], "open_to_strangers": True, "languages": ["pt", "en"], "published": "2026-11-01", "expires": "2027-02-01"})
put("network_kenji-mori", {"name": "Kenji Mori", "contact": "kenji@example.jp", "site": "", "ids": {"github": "kmori"},
    "working_on": ["protein folding"], "keywords": ["protein folding", "alphafold"],
    "wants": [{"format": "joint_benchmark", "topic": "folding benchmarks", "by": ""}],
    "has": ["repo"], "open_to_strangers": True, "languages": ["ja", "en"], "published": "2026-11-01", "expires": "2027-02-01"})
put("network_expired", {"name": "Old Person", "contact": "x@y.example", "keywords": ["text-to-sql"], "wants": [{"format": "compare_note", "topic": "text-to-sql"}], "has": [], "published": "2025-01-01", "expires": "2025-04-01"})
put("network_yusuf-demir", {"name": "Yusuf Demir", "contact": "yusuf@boun.example", "site": "", "ids": {"github": "ydemir"},
    "working_on": ["text-to-SQL for ERP systems"], "keywords": ["text-to-sql", "erp", "turkish"],
    "wants": [{"format": "compare_note", "topic": "text-to-SQL on closed enterprise data", "by": "2026-12-20"}],
    "has": ["paper"], "open_to_strangers": True, "languages": ["tr", "en"], "published": "2026-11-03", "expires": "2027-02-03"})
# malicious: lists where strings go, multi-recipient contact, linefeed in name, huge keyword list
put("network_evil", {"name": ["Evil", "List"], "contact": "a@b.example, c@d.example", "ids": [], "keywords": "text-to-sql",
    "wants": ["compare_note"], "has": ["paper"], "expires": 2099})
# impostor: claims Yuyu Luo's ORCID and a contact, but the GitHub login's profile name is someone else
put("network_yuyu-luo", {"name": "Yuyu Luo", "contact": "attacker@evil.example", "site": "", "ids": {"orcid": "0000-0001-9530-3327", "github": "notluo"},
    "working_on": ["text-to-SQL"], "keywords": ["text-to-sql", "large language models"],
    "wants": [{"format": "compare_note", "topic": "text-to-SQL on closed enterprise data", "by": ""}],
    "has": ["paper"], "open_to_strangers": True, "languages": ["en"], "published": "2026-11-05", "expires": "2027-02-05"})
put("github_user_notluo", {"login": "notluo", "name": "Random Person", "html_url": "https://github.com/notluo", "email": None, "blog": "", "company": None, "location": None, "type": "User"})
put("openalex_author_orcid_0000-0001-9530-3327", None)
put("openalex_authors_yuyu_luo", {"results": []})
put("arxiv_au_yuyu_luo", {"__text__": EMPTY_FEED})
put("github_repos_notluo", [])
# real people's profiles for verification and workspace building
ANA = ("A5000000050", "Ana Ferreira", "0000-0001-0000-0001", "Universidade Federal de Minas Gerais", "BR")
put("openalex_author_orcid_0000-0001-0000-0001", {"id": "https://openalex.org/A5000000050", "display_name": "Ana Ferreira", "orcid": "https://orcid.org/0000-0001-0000-0001", "works_count": 2, "last_known_institutions": [{"display_name": "Universidade Federal de Minas Gerais", "country_code": "BR"}]})
put("openalex_works_author_A5000000050", {"results": [
    work("W50", "Text-to-SQL for Open Data Portals in Portuguese", "2026-05-01", [ANA], [T_SQL], ["text-to-sql", "open data", "portuguese"], 3, "arXiv",
         "We reach 71.2% execution accuracy on 1,200 questions over public data portals with a 7B open model and schema pruning."),
]})
put("arxiv_au_ana_ferreira", {"__text__": EMPTY_FEED})
put("github_user_anaferreira", {"login": "anaferreira", "name": "Ana Ferreira", "html_url": "https://github.com/anaferreira", "email": None, "blog": "", "company": "UFMG", "location": "Belo Horizonte", "type": "User"})
put("github_repos_anaferreira", [{"full_name": "anaferreira/portal-sql", "html_url": "https://github.com/anaferreira/portal-sql", "description": "Text-to-SQL over open data portals", "topics": ["text-to-sql"], "language": "Python", "stargazers_count": 9, "forks_count": 1, "pushed_at": "2026-06-01T00:00:00Z", "owner": {"login": "anaferreira"}, "fork": False}])
put("orcid_person_0000-0001-0000-0001", {"emails": {"email": []}, "researcher-urls": {"researcher-url": []}})
put("openalex_authors_yusuf_demir", {"results": []})
put("arxiv_au_yusuf_demir", {"__text__": EMPTY_FEED})
put("github_user_ydemir", {"login": "ydemir", "name": "Yusuf Demir", "html_url": "https://github.com/ydemir", "email": None, "blog": "", "company": None, "location": None, "type": "User"})
put("github_repos_ydemir", [])
put("github_user_kmori", {"login": "kmori", "name": "Kenji Mori", "html_url": "https://github.com/kmori", "email": None, "blog": "", "company": None, "location": None, "type": "User"})
put("github_me", {"login": "besk-tech"})
# --- duplicates: a slice of the real "sync claude code sessions" cluster (Nov 2026)
def repo(full, desc, lang, stars, pushed, topics=()):
    return {"full_name": full, "html_url": "https://github.com/" + full, "description": desc, "topics": list(topics), "language": lang,
            "stargazers_count": stars, "forks_count": 0, "pushed_at": pushed, "owner": {"login": full.split("/")[0]}, "license": {"spdx_id": "MIT"}}
CLUSTER = [
    repo("tawanorg/claude-sync", "Sync Claude Code sessions across devices using Cloudflare R2 with end-to-end encryption", "Go", 320, "2026-11-06T00:00:00Z"),
    repo("ahmojo/codex-claude-transfer", "Local-first CLI that moves Codex & Claude Code sessions between machines: export, copy, import. No cloud, optional LAN sync.", "Go", 80, "2026-10-29T00:00:00Z", ["claude-code", "codex", "local-first"]),
    repo("songkeys/cc-same", "Keep Claude Desktop's local sessions identical across all your accounts. Desktop app (macOS, Windows, Linux) and CLI.", "Rust", 58, "2026-11-07T00:00:00Z"),
    repo("Vincentvn28/claude-session-sync", "Sync Claude Code sessions (chat history + memory + plans) across machines via Google Drive", "TypeScript", 4, "2026-10-21T00:00:00Z"),
    repo("sirajeddineaissa/claude-session-sync", "Sync Claude Code sessions across machines. Encrypt and back up conversations to a private GitHub repo", "TypeScript", 3, "2026-09-10T00:00:00Z"),
    repo("ikook-wang/cc-sync", "Sync Claude Code sessions & config between machines over SSH", "Shell", 2, "2026-09-25T00:00:00Z", ["ssh", "tailscale"]),
    repo("Voxiven/dotsync", "Sync Claude Code memory, sessions, and dotfiles between machines via Syncthing", "Shell", 2, "2026-10-07T00:00:00Z"),
    repo("mattbirchler/claude-code-obsidian", "An Obsidian plugin that syncs your Claude Code sessions to Obsidian", "TypeScript", 3, "2026-10-03T00:00:00Z"),
    repo("chrisdoc/hevy-mcp", "Manage your Hevy workouts and sessions, stay synced", "TypeScript", 533, "2026-11-07T00:00:00Z", ["fitness"]),  # noise
]
put("github_search_sync_claude_code_sessions_machines", {"items": CLUSTER})
put("github_search_claude_sync_sessions", {"items": CLUSTER})
put("github_search_todo", {"items": []})
print("fixtures:", len(list(FX.glob("*.json"))))
