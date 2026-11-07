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


def _relevant_asset(assets: list[Asset], c: Candidate) -> dict | None:
    """The piece of work that actually overlaps, not merely the newest one."""
    wanted = {k.lower() for k in c.overlap.shared_keywords} | {t.lower() for t in c.overlap.shared_topics}
    if not assets:
        return None

    def hits(a: Asset) -> int:
        bag = {k.lower() for k in a.keywords} | {t.lower() for t in a.topics} | set((a.title + " " + a.summary).lower().split())
        return sum(1 for w in wanted if w in bag or any(w in x for x in bag))

    best = max(assets, key=lambda a: (hits(a), a.date or date.min))
    if hits(best) == 0:
        best = max(assets, key=lambda a: a.date or date.min)
    return {"kind": best.kind, "title": best.title, "url": best.url, "date": best.date.isoformat() if best.date else None, "stats": best.stats}


def _top_assets(assets: list[Asset], n: int = 5) -> list[dict]:
    def key(a: Asset) -> tuple:
        s = a.stats
        return (a.date or date.min, s.get("citations", 0) + s.get("stars", 0) + s.get("likes", 0))

    return [
        {"kind": a.kind, "title": a.title, "url": a.url, "date": a.date.isoformat() if a.date else None, "stats": a.stats}
        for a in sorted(assets, key=key, reverse=True)[:n]
    ]


def _venues(assets: list[Asset], n: int = 5) -> list[str]:
    skip = {"arxiv", "arxiv (cornell university)", "zenodo", "zenodo (cern european organization for nuclear research)", "ssrn", "biorxiv", "medrxiv"}
    c = Counter(a.extra.get("venue", "") for a in assets if a.kind == "paper" and a.extra.get("venue") and a.extra["venue"].lower() not in skip)
    return [v for v, _ in c.most_common(n)]


def joint_work_brief(me: Profile, c: Candidate) -> dict:
    p = c.person
    my_kinds = {a.kind for a in me.assets}
    their_kinds = {a.kind for a in p.assets}
    both = my_kinds | their_kinds

    runnable = {"repo", "dataset", "model"}
    ranked = []
    for fid, label, effort, needs, desc in FORMATS:
        have = {k for k in needs if k in both}
        fit = len(have) / len(needs) if needs else 1.0  # a format that needs nothing is always possible
        s = fit + (0.35 if effort == "days" else 0.1 if effort == "weeks" else 0.0)
        if fid in ("replication", "joint_benchmark", "merge_tools"):
            # these only work when BOTH sides have something runnable
            if not (my_kinds & runnable and their_kinds & runnable):
                s -= 0.8
        if fid == "shared_dataset" and "dataset" not in their_kinds and "dataset" not in my_kinds:
            s -= 0.8
        if fid in ("compare_note", "joint_paper", "review_each_other") and "paper" not in their_kinds:
            s -= 0.5  # they have no paper to compare or review
        # reward using what only one side has: that's the reason to collaborate at all
        if any(k in c.overlap.they_have or k in c.overlap.you_have for k in needs):
            s += 0.4
        if fit == 0:
            s -= 0.6
        if p.card and p.card.open_to:
            wants = " ".join(p.card.open_to).lower()
            if label.lower() in wants or fid.replace("_", " ") in wants:
                s += 0.7  # they said so themselves
            elif fid == "joint_paper" and "co-author" in wants:
                s += 0.3  # welcome, but a full paper still comes after a smaller first step
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
    mine = _relevant_asset(me.assets, c)
    theirs = _relevant_asset(p.assets, c)
    from .match import GENERIC
    sharp = [k for k in c.overlap.shared_keywords if k not in GENERIC][:1] or c.overlap.shared_topics[:1]
    subject = f"{(fmt[1] if fmt else 'Working on the same thing')}: {', '.join(sharp)}".strip(": ")
    to, to_prov = None, None
    if p.card and p.card.contact:
        to, to_prov = p.card.contact, "whoelse card on their own site"
    elif p.contact.email:
        to, to_prov = p.contact.email, p.contact.provenance.get("email", "")
    return {
        "to": to,
        "to_provenance": to_prov,
        "to_fallbacks": [u for u in (p.contact.website, p.contact.github, p.contact.huggingface, p.contact.linkedin, p.contact.orcid) if u],
        "subject": subject,
        "facts": {
            "their_work": theirs,
            "my_work": mine,
            "shared": [k for k in c.overlap.shared_keywords if k not in GENERIC][:3] or c.overlap.shared_topics[:2],
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
