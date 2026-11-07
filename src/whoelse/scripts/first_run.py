"""First live run on your own machine. Prints what the agent would see, and saves it.

    pip install git+https://github.com/beskvladimir-create/whoelse
    WHOELSE_MAILTO=you@example.org python -m whoelse.scripts.first_run "Your Name" --orcid 0000-0000-0000-0000

Nothing is sent anywhere. The output is a list of people with reasons and public contacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from whoelse import server


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--orcid")
    ap.add_argument("--github")
    ap.add_argument("--huggingface")
    ap.add_argument("--affiliation")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--out", default="whoelse-first-run.json")
    a = ap.parse_args()

    prof = await server.load_profile(a.name, orcid=a.orcid, github=a.github, huggingface=a.huggingface, affiliation_hint=a.affiliation or "")
    if prof.get("status") == "ambiguous":
        print("Several people share this name. Re-run with --orcid or --affiliation. Options:")
        for o in prof["options"]:
            print(f"  {o['openalex']}  {o['name']}  works={o['works']}  {o['institutions']}  orcid={o['orcid']}")
        return
    print(f"Profile: {prof['name']} | {prof['assets']} | topics: {', '.join(prof['top_topics'][:5])}")
    for n in prof.get("notes", []):
        print("  note:", n)

    res = await server.find_overlaps(a.name, limit=a.limit)
    print()
    print(res["headline"])
    print()
    for line in res["lines"]:
        print(line)
    if res["source_errors"]:
        print("\nsource errors:", *res["source_errors"], sep="\n  ")

    briefs = []
    for c in res["candidates"][:5]:
        b = await server.joint_work_brief(a.name, c["index"])
        d = await server.draft_outreach(a.name, c["index"], b["formats"][0]["id"])
        briefs.append({"candidate": c, "brief": b, "draft": d})
        if d["to"]:
            reach = f"to: {d['to']}"
        elif d["to_fallbacks"]:
            reach = "via " + ", ".join(d["to_fallbacks"][:2])
        else:
            reach = "no public contact; find them through their work: " + (c["top_work"][0]["url"] if c["top_work"] else "?")
        print(f"\n--- {c['name']}: best format {b['formats'][0]['label']} ({b['formats'][0]['effort']}); {reach}")

    Path(a.out).write_text(json.dumps({"profile": prof, "overlaps": res, "briefs": briefs}, indent=2, ensure_ascii=False, default=str))
    print(f"\nSaved to {a.out}")


if __name__ == "__main__":
    asyncio.run(main())
