"""Shared data shapes. Everything the tools return is built from these."""

from __future__ import annotations

from datetime import date as _date
from typing import Literal

from pydantic import BaseModel, Field

AssetKind = Literal["paper", "repo", "model", "dataset", "space"]


class Asset(BaseModel):
    """One thing a person made: a paper, a repository, a model, a dataset."""

    kind: AssetKind
    title: str
    url: str
    date: _date | None = None
    source: str  # openalex | arxiv | github | huggingface
    summary: str = ""  # abstract / description, trimmed
    keywords: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)  # OpenAlex topic display names
    topic_ids: list[str] = Field(default_factory=list)  # OpenAlex topic ids (T10xxx)
    stats: dict[str, int] = Field(default_factory=dict)  # citations, stars, downloads, likes
    coauthors: list[str] = Field(default_factory=list)  # names
    extra: dict[str, str] = Field(default_factory=dict)


class Contact(BaseModel):
    """Only what the person themselves made public."""

    email: str | None = None
    website: str | None = None
    orcid: str | None = None
    github: str | None = None
    huggingface: str | None = None
    scholar: str | None = None
    linkedin: str | None = None
    other: list[str] = Field(default_factory=list)
    # Where each contact came from, so the user can check it.
    provenance: dict[str, str] = Field(default_factory=dict)


class Person(BaseModel):
    name: str
    ids: dict[str, str] = Field(default_factory=dict)  # openalex, orcid, github, huggingface
    affiliation: str = ""
    country: str = ""
    assets: list[Asset] = Field(default_factory=list)
    contact: Contact = Field(default_factory=Contact)
    # Aggregates
    topics: dict[str, float] = Field(default_factory=dict)  # topic name -> weight
    topic_ids: dict[str, float] = Field(default_factory=dict)
    keywords: dict[str, float] = Field(default_factory=dict)
    last_active: _date | None = None
    card: "Card | None" = None  # if they publish a whoelse card, they're "connected"


class Card(BaseModel):
    """The decentralised opt-in. A person publishes this JSON at
    https://<their site>/.well-known/whoelse.json. If it exists, whoelse treats them as
    reachable and shows what they say they're open to. No central server."""

    name: str
    working_on: list[str] = Field(default_factory=list)
    open_to: list[str] = Field(default_factory=list)  # e.g. "co-author", "joint benchmark", "podcast"
    contact: str = ""
    languages: list[str] = Field(default_factory=list)
    updated: _date | None = None
    url: str = ""


class Profile(Person):
    """The user's own profile, built from their public work."""

    built_at: _date | None = None
    sources_used: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Overlap(BaseModel):
    shared_topics: list[str] = Field(default_factory=list)
    shared_keywords: list[str] = Field(default_factory=list)
    # Things they have that you don't (and vice versa) — the seed of a joint work.
    they_have: list[str] = Field(default_factory=list)
    you_have: list[str] = Field(default_factory=list)
    already_coauthors: bool = False


class Candidate(BaseModel):
    person: Person
    score: float
    overlap: Overlap
    why: str  # one sentence, in plain words
    reachable: Literal["card", "email", "website", "profile_only"]
