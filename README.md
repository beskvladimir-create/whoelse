# whoelse

**You've been working on something for months. Somewhere, three other people are working on the same thing. None of you know.**

whoelse finds them. It reads your papers, your repos and your models, finds the people whose current work overlaps yours, tells you what the two of you could build together, and drafts the first message. You decide who gets it.

Runs inside Claude, Cursor, Codex or any MCP client. No sign-up, no profile to fill in, no server. Free.

```bash
pip install git+https://github.com/beskvladimir-create/whoelse
```

---

## The problem

Nobody is working alone on purpose. It just turns out that way: you publish, nothing happens, you go back to work. The person who would have cited you, tried your code, co-written the next paper with you, is two time zones away and has never heard your name. Discovery runs on conferences and luck, and most people get neither.

whoelse replaces luck with a lookup.

## What you get

Ask your agent:

> Load my profile: Ada Example, ORCID 0000-0002-1825-0097. Who else is working on this?

```
7 people are working on what Ada Example is working on (text-to-SQL; schema linking).
4 can be written to today, 1 of them published a whoelse card and said what they're open to.

 0. Nikhil Rao (IIT Madras): same topic; active 2026-09; they have a dataset you don't.   reach: email
 1. Amine Mhedhbi (Polytechnique Montréal): same topic; publishes a whoelse card.         reach: card ✓
 2. Paolo Papotti (EURECOM): same topic; active 2026-05.                                   reach: site/github
```

> What could Amine and I do together?

```
 Fit  Format             Effort  Why
 1.8  Joint benchmark    weeks   he has a routing benchmark, you have a production system to run on it
 1.3  Comparison note    days    both of you have a recent paper on the same problem
 1.1  Talk together      days    fastest way to put both names next to each other in public
```

> Draft the message.

Your agent writes it in your voice: under 180 words, one concrete artefact of theirs, one of yours, the format in a sentence, one yes/no question. You read it. You send it, from your own address, to one person.

## How it finds people

Three directions at once, then merged into people:

| direction | source | what it catches |
|---|---|---|
| papers | OpenAlex keywords and topics; arXiv for preprints OpenAlex hasn't indexed yet | who published on your exact problem in the last 24 months |
| code | GitHub repository search | who is building it |
| models and data | Hugging Face Hub | who released weights or a dataset (quantisations and repacks are filtered out) |

A GitHub login, a Hugging Face account and an OpenAlex author become one person only when a second signal says so: the same affiliation, a link from their paper to that account, the same website. A shared name alone keeps them apart, flagged as possible namesakes, so one person's email never lands next to another's work. Organisations (a company's GitHub, a lab's Hugging Face) are recognised and left out. Authors who link their own code in an arXiv comment are joined automatically, including you: give whoelse your name and it usually finds your handles itself.

If several people share your name, whoelse does not guess. It shows you the namesakes and asks for an ORCID or an affiliation.

A third reach channel, GitHub user search by full name, is used only when it returns exactly one account whose repositories are about the same subject; otherwise it is ignored. On real data it finds roughly one in three researchers who left nothing on ORCID.

## How it reaches them

Only through what the person published about themselves, and every contact says where it came from:

- ORCID: public email, personal site, GitHub, Scholar, LinkedIn (limited-visibility emails are never read)
- GitHub profile: public email, website
- Their own website: a whoelse card, if they have one

arXiv submitter emails are never touched. arXiv's terms forbid using them for unsolicited contact, and we don't need them.

## The card: connected mode without a server

Put this on your own site at `/.well-known/whoelse.json`:

```json
{
  "name": "Ada Example",
  "working_on": ["text-to-SQL on open-weight models", "schema linking"],
  "open_to": ["co-author", "joint benchmark", "talk together"],
  "contact": "ada@example.org",
  "languages": ["en", "pt"],
  "updated": "2026-11-07"
}
```

Anyone running whoelse now sees you as **connected**: reachable, and open to exactly what you said. When both sides have a card, both of you are one `joint_work_brief` away from the same proposal; sending it to both at once is on the roadmap. No registry, no account, no central anything. The web is the directory. `make_card` writes yours.

## Your people

Once you've decided someone is one of yours (`add_peer`), whoelse watches what they ship and tells you when there is something to support: a repo to try and star, a paper to cite or argue with, a model to run on your data and report back. It never stars, follows or likes anything for you. GitHub names automated starring and following as rank abuse, and a circle that fakes its own signal is worth nothing to the people in it.

## Tools

| tool | what |
|---|---|
| `load_profile` | your profile from OpenAlex, arXiv, GitHub, Hugging Face, ORCID |
| `find_overlaps` | people whose recent work overlaps yours, ranked, with reasons and public contacts |
| `joint_work_brief` | one person: the evidence, what each side has, formats ranked by fit and effort, venues in common |
| `draft_outreach` | facts and structure for the first message; your agent writes it, you send it |
| `add_peer`, `remove_peer`, `whats_new_from_peers` | your people and what they shipped this month |
| `make_card` | your `/.well-known/whoelse.json` |
| `list_known` | profiles and peers on this machine |

## Install

```bash
pip install git+https://github.com/beskvladimir-create/whoelse      # PyPI release to follow
```

Claude Code: `claude mcp add whoelse -- whoelse`

Claude Desktop, Cursor, Codex and others, in the MCP config:

```json
{ "mcpServers": { "whoelse": { "command": "whoelse" } } }
```

Optional environment:

| variable | effect |
|---|---|
| `WHOELSE_OPENALEX_KEY` | free key from openalex.org/settings/api; without it you share a small per-IP daily budget |
| `WHOELSE_MAILTO` | your email for OpenAlex's polite pool; sent nowhere else |
| `GITHUB_TOKEN` | raises GitHub search limits; read-only scope is enough |
| `WHOELSE_HOME` | where profiles, peers and cache live (default `~/.whoelse`) |

## What it will not do

- Send anything. Every message leaves from your own address, one person at a time, by your hand.
- Use a contact the person did not publish.
- Star, follow, like or post on your behalf.
- Keep anything anywhere but your machine.

## First run on your own name

```bash
WHOELSE_MAILTO=you@example.org python -m whoelse.scripts.first_run "Your Name" --orcid 0000-0000-0000-0000
```

Prints the people, the reasons, the best format for each, and how to reach them; saves everything to `whoelse-first-run.json`. Nothing is sent.

## Develop

```bash
git clone https://github.com/beskvladimir-create/whoelse && cd whoelse
pip install -e ".[dev]"
pytest                                                      # offline, on recorded fixtures
WHOELSE_FIXTURES=tests/fixtures python -m whoelse.server    # offline demo server
```

Sources: [OpenAlex](https://openalex.org) (CC0), [arXiv](https://arxiv.org) (CC0 metadata), [ORCID](https://orcid.org) public API, [GitHub](https://docs.github.com/en/rest), [Hugging Face Hub](https://huggingface.co/docs/hub/api). All keyless.

MIT.
