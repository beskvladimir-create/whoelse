"""Builds the recorded-response fixtures used by the tests and by the offline demo.
Shapes follow the public APIs (OpenAlex, arXiv Atom, ORCID v3, GitHub REST, HF Hub).
Run: python tests/make_fixtures.py"""

from __future__ import annotations

import json
from pathlib import Path

FX = Path(__file__).parent / "fixtures"
FX.mkdir(exist_ok=True)


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

print("fixtures:", len(list(FX.glob("*.json"))))
