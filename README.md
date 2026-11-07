# whoelse

**Who else is working on what you're working on?**
Your AI agent finds them, works out what you could build together, and drafts the first message.
Papers, code, datasets, models. Runs locally. Free.

---

You've been working on something for months. Somewhere, three other people are working on the same thing. You don't know each other.

whoelse is an MCP server for Claude, Cursor, Codex and any other MCP client. Give it your name. It reads your papers, your repos and your models, finds the people whose current work overlaps yours, and for each one tells you **what you could do together**: a comparison note, a joint benchmark, a merged dataset, a tool one of you has half-built. Then it drafts the message. You decide who gets it.

No sign-up. No profile to fill in. No server. Your data stays on your machine.

## Install

```bash
uvx whoelse            # or: pip install whoelse
```

Claude Desktop / Claude Code (`claude mcp add whoelse -- uvx whoelse`), Cursor, Codex: add to your MCP config:

```json
{ "mcpServers": { "whoelse": { "command": "uvx", "args": ["whoelse"] } } }
```

Optional environment:

| variable | what it does |
|---|---|
| `WHOELSE_MAILTO` | your email, sent only to OpenAlex's polite pool for faster responses |
| `GITHUB_TOKEN` | raises GitHub search limits; read-only is enough |
| `WHOELSE_HOME` | where profiles and cache live (default `~/.whoelse`) |

## Use

Ask your agent:

> Load my profile: Ada Example, ORCID 0000-0002-1825-0097, GitHub adax. Then: who else is working on this?

You get a ranked list. Each line is one person, one reason, and how to reach them (only contacts they published themselves, each with its source):

```
1  Paolo Papotti      EURECOM     same topic: Natural Language Interfaces to Databases; active 2026-04     website, github
2  Amine Mhedhbi      Polytechnique Montréal   same topic; publishes a whoelse card (open to: joint benchmark)   card ✓
3  Alejandro Peña     UAM Madrid  same topic: Text Classification in Public Administration                   profile only
```

Then:

> What could Amine and I do together?

```
Fit  Format               Effort   Why
1.8  Joint benchmark      weeks    he has a routing benchmark dataset, you have a production system to run on it
1.3  Comparison note      days     both of you have a recent paper on the same problem
1.1  Talk together        days     fastest way to put both names next to each other
```

> Draft the message.

The agent writes it in your voice: under 180 words, one concrete artefact from each side, the format in a sentence, one yes/no question. You read it, you send it, from your own address, to one person.

## What it does

| tool | what |
|---|---|
| `load_profile` | builds your profile from OpenAlex, arXiv, GitHub, Hugging Face, ORCID |
| `find_overlaps` | people whose recent papers, code or models overlap yours, ranked, with public contacts and provenance |
| `joint_work_brief` | for one person: shared topics, what each side has, formats ranked by fit and effort, venues in common |
| `draft_outreach` | facts and structure for the first message; your agent writes it, you send it |
| `add_peer`, `whats_new_from_peers` | your people, and what they shipped this month, with concrete ways to support it |
| `make_card` | your whoelse card (see below) |

## The card

Put a small JSON file on your own site at `/.well-known/whoelse.json`:

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

Anyone running whoelse now sees you as **connected**: reachable, and open to exactly what you said. When both of you have a card, your agents can propose the joint work to both sides at once. There is no registry and no server; the web is the directory.

## Your people

Once someone is one of yours (`add_peer`), whoelse watches what they publish and tells you when there is something to support: a repo to try and star, a paper to cite or argue with, a model to run on your data. It never stars, follows or likes anything for you. GitHub's acceptable use policy names "automated starring or following" as rank abuse, and a network that fakes its own signal is worth nothing to the people in it.

## What it will not do

- Send anything. Every message leaves from your own address, one person at a time, by your hand.
- Use contacts a person did not publish. Every contact carries its provenance (ORCID public email, GitHub profile, their own site).
- Touch arXiv's submitter emails. arXiv's terms forbid harvesting them, and we don't need them.
- Keep anything anywhere but your machine.

## Sources

[OpenAlex](https://openalex.org) (CC0 metadata), [arXiv](https://arxiv.org) (CC0 descriptive metadata), [ORCID](https://orcid.org) public API, [GitHub](https://docs.github.com/en/rest) REST, [Hugging Face Hub](https://huggingface.co/docs/hub/api). All keyless.

## Develop

```bash
git clone https://github.com/besk-tech/whoelse && cd whoelse
pip install -e ".[dev]"
pytest                               # offline, runs on recorded fixtures
WHOELSE_FIXTURES=tests/fixtures python -m whoelse.server   # offline demo server
```

## License

MIT
