"""From a match to a concrete thing two people could do together, and the first message.

whoelse returns structured evidence and a ranked set of formats. The host model (Claude,
Cursor, Codex) turns that into prose in the user's own voice; it has the context, we have
the facts. Nothing here sends anything."""

from __future__ import annotations

from collections import Counter
from datetime import date

from .models import Asset, Candidate, Profile

FORMATS = [
    # (id, label, effort, needs, description)
    ("compare_note", "Comparison note", "days", ["paper"],
     "A short joint write-up comparing your two approaches on the same problem: what each gets right, where they differ, one table. Easy to place on arXiv or a workshop."),
    ("joint_benchmark", "Joint benchmark", "weeks", ["dataset", "repo"],
     "Pool your data or evaluation code into one benchmark with a leaderboard. Benchmarks get cited by everyone who uses them."),
    ("replication", "Cross-replication", "weeks", ["paper", "repo"],
     "Each of you re-runs the other's method on your own data and you publish the result together. Reviewers love it; it costs little new work."),
    ("merge_tools", "Merge tools", "weeks", ["repo"],
     "One of you has half-built what the other needs. Combine into a single repo with both as maintainers."),
    ("shared_dataset", "Shared dataset release", "weeks", ["dataset"],
     "Release one documented dataset on Hugging Face with both names on the card."),
    ("joint_paper", "Joint paper", "months", ["paper"],
     "A full paper. Pick this only after a smaller format worked."),
    ("talk_together", "Talk or podcast together", "days", [],
     "A joint conference proposal, a two-person talk, or a podcast episode where you interview each other. Fastest way to put both names next to each other in public."),
    ("review_each_other", "Review each other's drafts", "days", ["paper"],
     "Exchange drafts before submission. Not a public artefact, but it is how most lasting collaborations start."),
]


def _top_assets(assets: list[Asset], n: int = 5) -> list[dict]:
    def key(a: Asset) -> tuple:
        s = a.stats
        return (a.date or date.min, s.get("citations", 0) + s.get("stars", 0) + s.get("likes", 0))

    return [
        {"kind": a.kind, "title": a.title, "url": a.url, "date": a.date.isoformat() if a.date else None, "stats": a.stats}
        for a in sorted(assets, key=key, reverse=True)[:n]
    ]


def _venues(assets: list[Asset], n: int = 5) -> list[str]:
    c = Counter(a.extra.get("venue", "") for a in assets if a.kind == "paper" and a.extra.get("venue"))
    return [v for v, _ in c.most_common(n)]


def joint_work_brief(me: Profile, c: Candidate) -> dict:
    p = c.person
    my_kinds = {a.kind for a in me.assets}
    their_kinds = {a.kind for a in p.assets}
    both = my_kinds | their_kinds

    ranked = []
    for fid, label, effort, needs, desc in FORMATS:
        fit = sum(1 for k in needs if k in both) / (len(needs) or 1)
        # reward complementarity: formats that use what only one side has
        uses_gap = any(k in c.overlap.they_have or k in c.overlap.you_have for k in needs)
        s = fit + (0.5 if uses_gap else 0.0) + (0.3 if effort == "days" else 0.1 if effort == "weeks" else 0.0)
        if c.overlap.already_coauthors and fid in ("joint_paper", "compare_note"):
            s += 0.4
        ranked.append((round(s, 2), fid, label, effort, desc))
    ranked.sort(key=lambda x: -x[0])

    return {
        "you": {"name": me.name, "top_topics": list(me.topics)[:5], "assets": _top_assets(me.assets), "venues": _venues(me.assets)},
        "them": {
            "name": p.name,
            "affiliation": p.affiliation,
            "ids": p.ids,
            "last_active": p.last_active.isoformat() if p.last_active else None,
            "top_topics": list(p.topics)[:5],
            "assets": _top_assets(p.assets),
            "venues": _venues(p.assets),
            "card": p.card.model_dump(mode="json") if p.card else None,
        },
        "overlap": c.overlap.model_dump(),
        "why": c.why,
        "formats": [
            {"id": fid, "label": label, "effort": effort, "fit": s, "what": desc} for s, fid, label, effort, desc in ranked[:5]
        ],
        "venues_in_common": sorted(set(_venues(me.assets)) & set(_venues(p.assets))),
        "how_to_reach": {k: v for k, v in p.contact.model_dump().items() if v and k != "provenance"},
        "contact_provenance": p.contact.provenance,
        "guidance": (
            "Write the proposal in the user's own voice, under 180 words. Name one concrete artefact from each side, "
            "state the format in one sentence, say what each person brings, and end with a single yes/no question. "
            "No flattery, no résumé, no call invitation unless the user asks. If the person publishes a whoelse card, "
            "respect its 'open_to' list and prefer its contact."
        ),
    }


def outreach_skeleton(me: Profile, c: Candidate, format_id: str | None = None) -> dict:
    p = c.person
    fmt = next((f for f in FORMATS if f[0] == format_id), None) if format_id else None
    mine = _top_assets(me.assets, 1)
    theirs = _top_assets(p.assets, 1)
    subject = f"{(fmt[1] if fmt else 'Working on the same thing')}: {', '.join(c.overlap.shared_topics[:1] or c.overlap.shared_keywords[:1])}".strip(": ")
    return {
        "to": p.contact.email or p.card.contact if p.card else p.contact.email,
        "to_fallbacks": [u for u in (p.contact.website, p.contact.github, p.contact.linkedin, p.contact.orcid) if u],
        "subject": subject,
        "facts": {
            "their_work": theirs[0] if theirs else None,
            "my_work": mine[0] if mine else None,
            "shared": c.overlap.shared_topics[:2] or c.overlap.shared_keywords[:3],
            "format": {"id": fmt[0], "label": fmt[1], "what": fmt[4]} if fmt else None,
            "they_have": c.overlap.they_have,
            "you_have": c.overlap.you_have,
        },
        "structure": [
            "1. One sentence: what of theirs you read and the one thing in it that matters to you.",
            "2. One sentence: what you did on the same problem, with the link.",
            "3. Two sentences: the format and what each of you brings.",
            "4. One question they can answer with yes or no.",
        ],
        "rules": [
            "Send from your own address, one person at a time. The user decides who gets it.",
            "Use only contacts the person made public themselves (see contact_provenance).",
            "Do not mention this tool. Do not flatter. Do not propose a call unless asked.",
        ],
    }
