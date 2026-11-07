# Decisions log

Kept so the reasoning survives the chat that produced it.

## 2026-11-07, v0.1.0

**Why this exists.** Research into "Код популярности" showed the honest engine of recognition is third-party mentions born from joint work, not self-publishing. Joint work needs the right people. Nobody with overlapping work knows each other. That is the pain; whoelse is the lookup.

**What exists already (checked 2026-11-07).**
Sites: ResearcherCollab (~1.6k people, collab calls, AI matching in PRO), ResearchConnectX, ResearcherNet (Kolkata, ~650 people, institution sales), Collaboratium, Researchmate, CheckMyManuscript collaborator finder. All stop at "here is a person"; none proposes the joint work, none measures reach, none leaves academia.
MCPs: paper search (paper-search-mcp, arxiv-mcp-server, OpenArx), author profiles (OpenAlex MCP, ORCID MCP), AuthorProfileMCP (co-authors you already have, 1 star), sales people-search (Sixtyfour, Apollo). None does "with whom should I work next, and on what".

**Name.** `whoelse`: a question everyone asks. GitHub checked: `coauthor` taken (280 stars, other project, and too narrow); `kindred` noisy; `whoelse` only a 2-star unrelated repo.

**Shape.** MCP server, not a site: spreads through GitHub and MCP registries, works inside an agent that already knows the user, no cold-start registry, data stays local. First user is the author.

**Sources and rules.**
- OpenAlex: CC0 metadata; keyword ids (`keywords.id`) are far sharper than topics (a text-to-SQL paper lands in topic "Topic Modeling"). API key optional but recommended (shared per-IP budget without it).
- arXiv: CC0 descriptive metadata. Submitter emails are behind login, monitored, and forbidden for unsolicited contact. Never used. `arxiv:comment` carries the author's own GitHub/HF links, used to join papers to code.
- ORCID: public API, keyless. Only `visibility: public` emails. Needs `Accept: application/vnd.orcid+json`; XML fallback parser included.
- GitHub: REST, token optional. Acceptable Use names "automated starring or following" as rank abuse: whoelse never stars/follows.
- Hugging Face: keyless. Quantisations/repacks (`base_model:quantized:`, gguf/awq/gptq...) are not the author's work and are filtered.
- Platform rules checked earlier: X (OAuth is not consent for automated actions), LinkedIn (bots/inauthentic engagement banned), Meta (high-frequency account creation banned). Hence: one message, one person, sent by the user.

**Namesakes.** OpenAlex returned three "Vladimir Beskorovainyi" (Kharkiv, Volgograd, MIPT). Guessing by works_count picks the wrong person. whoelse refuses to guess and asks for ORCID/affiliation.

**Connected mode.** `/.well-known/whoelse.json` on the person's own site. No registry: the web is the directory. Card bonus in ranking (+0.2).

**Not built yet.** Joint proposal to both sides when both have cards (needs an inbox convention); per-source rate budgeting UI; Semantic Scholar as a second paper source; a `reach` index (what search/LLMs answer for the user's name) — belongs to the larger product, not this tool.

**Author.** Vladimir Beskorovainyi, sole author of all commits.

## 2026-11-07, review round

Independent review found 25 items; 20 fixed, 2 rejected as non-bugs, 3 deferred. Live measurements on the author's own topics drove three design changes:

- **Reach is the bottleneck, not discovery.** Of 60 ORCID records behind the top text-to-SQL papers, 4 had a public email and 6 any URL. Of 60 fresh arXiv papers, 7 linked GitHub. So: a third channel, GitHub user search by full name, accepted only on a unique hit confirmed by repository subject (3 of 9 real names resolved; common names return 18–142 namesakes and are skipped).
- **Generic terms must not carry a match.** "large language models" was shared by nearly everyone in the pool. Keywords are now IDF-weighted over the candidate pool, with a hard-coded generic set damped to 8%.
- **Identity is guarded, not guessed.** Self-exclusion by ids, not name only; merge of records requires a second signal; organisations are detected on GitHub (type) and Hugging Face (overview) and dropped; an ORCID the user supplies is never stamped onto a namesake; CJK and accented names survive slug/norm.

Robustness: any non-JSON 200 (SPA fallback pages at /.well-known/whoelse.json) is a SourceError; one candidate's broken site cannot take the result down; Retry-After dates parse; arXiv rate-limit text does not crash; per-host concurrency caps; tool errors reach the model as text (ToolError).

Deferred: proposal to both card holders at once; PyPI release; Semantic Scholar as a second index.
