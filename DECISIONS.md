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

## 2026-11-07, verification round

Second independent pass (verifying the fixes) found one serious regression I had introduced: arXiv coauthors were keyed by the paper's GitHub link and collapsed into one person. Fixed: the link stays on the paper; a person merges only on a second signal. Also fixed: outreach now cites the overlapping work, not the newest; affiliation match is token-based (no "MIT" ⊂ "Smith College"); same paper is a merge signal; a full name the person typed into their own GitHub/HF profile is a merge signal except for common family names; Hugging Face profile is a reach channel; card `open_to` lifts matching formats (full paper still after a smaller step); user's namesakes are not dropped as "me"; by-name GitHub lookups capped at 8 without a token; 403+Retry-After retried; semaphores per event loop; headline grammar; namesake flag in lines. 40 tests.

## 2026-11-08, connecting strangers

Vladimir's correction: finding people is not the product; two strangers ending up in one piece of work, fast, is. Knowing each other is a side effect. So: `start_joint_work` (a repository with a third of the work done, both names on it), `publish_request` (an open registry of what people want to build; one JSON per person in a public GitHub repo; no server), `whoelse-watch` (reads the registry, matches, creates the repository, invites, emails both; the user only has to not remove the tool). The honest waiting text keeps people in the queue: "37 are waiting, none on your topic yet; when one joins the work starts by itself and a link goes to you".

Two review rounds on this layer found and fixed: registry files are hostile input (strict schema; control and invisible characters stripped; names with markup rejected); impersonation by file (verification against the GitHub profile; CI requires ids.github == PR author AND that an existing file belongs to the author; workflow runs from base via pull_request_target); what verification cannot prove (that the account is the named researcher), answered by creating the repository private and publishing only after "in"; two watchers creating two repositories (one creator per pair by sorted name; repo name from the pair and the matched keyword, with a hash, never from either side's topic text); overwriting a collaborator's pushes (never write into an existing repo; check .whoelse.json sides); registry read from a 72-hour cache (tree uncached; files by blob sha through the git/blobs API, since raw.githubusercontent does not serve blob shas); SMTP sender forgery (no From → inbox only); state corruption and dry runs starting clocks. 65 tests, the registry CI script is executed in the test suite.

Known limit, stated in README: display-name verification is weak by itself; privacy-until-"in" is the real guard.

## 2026-11-08, before you build it

Vladimir's observation: open source has twenty repositories for every idea, each with ten stars,
each author alone and wanting the same thing: a response. And agents happily build the 21st.
So: `find_duplicates` (GitHub search on the idea; keep what is actually the same thing by token
similarity; order by stars; feature matrix from a fixed vocabulary of feature words, so repository
descriptions can label but never speak; verdict first) and `propose_merge` (base = the living
leader, pushed within 90 days with the most stars, so its stars and users carry over; what each
repository brings is its `only_here` features; one issue per author in their own repository).

Live check on "sync Claude Code sessions across machines": 233 repositories, leader
tawanorg/claude-sync (320 stars, Go, R2 + end-to-end encryption), ~40 at 2–13 stars with disjoint
backends (Drive, SSH, Syncthing, Tailscale, Obsidian, git vault, LAN). Early mistakes fixed: queries
from stop-word-stripped phrases were too weak (now product names and distinctive tokens); cluster
ordered by similarity put 2-star repos above the leader (now stars); base chosen by recency picked a
fresh fork over the leader (now living leader); default `max_stars=200` excluded the leader (now
none).

GitHub's Acceptable Use Policies (read 2026-11-08) prohibit "automated excessive bulk activity",
"unsolicited advertising or solicitation" and "excessive bulk content in issues". The limits are
code, not advice: 3–15 living repositories per proposal, 10 issues a day, 3 s pacing, a ledger so
no repository is asked twice, archived and issues-disabled repositories skipped, the plan inline or
at a URL the user owns (no placeholder links in anything sent), opened only on the user's explicit
yes from the user's own account. 74 tests.

Independent review of the layer (same day) found the engine confidently wrong on ordinary inputs:
product-name mentions counted as overlap ("a Claude Code plugin to back up sessions" → claude-mem,
114k stars, "already won"); core query words picked by length ("closed-contour" over "nl2sql" → "this
is new" for the most crowded field on GitHub); capped, star-sorted counts presented as medians; a
failed search reported as novelty; `max_stars` hiding the leader. On the merge side: no cluster
bound, a placeholder link in every public issue, the user's own and 3k-star repositories asked,
approval not bound to the texts shown. All fixed; the fixes are in the tests. Three rules came out
of it: relevance is measured on job words only, with all of them required for a short idea; a
cluster is reported with its search total and "at least" when capped; an empty cluster next to a
related field says "the parts exist", never "new". Claude Code plugin added (`plugin/`) so the check
runs before the agent writes the first line.

## 2026-11-08, analogues checked again

GitHub topic `idea-validation` (8 repositories) and web search: `mnemox-ai/idea-reality-mcp` (created
2026-02-24, 830 stars, maintenance mode since 2026-08) scores an idea against GitHub, HN, npm, PyPI,
Stack Overflow and lists similar repositories with pivot hints; `Smartulf123/check-before-you-build`
(2026-10, 0 stars) is an agent skill that writes "what exists, where the gap is". Neither builds a
feature matrix, proposes a merge to the authors, or finds the people. Nearest for people:
ResearcherCollab, CollabFinder (sites with manual profiles), openalex-research-mcp (co-authorship
data). The section "Before you build it" was renamed "Don't build it alone" to stop sharing a name
with a stranger's project and to say what is different: whoelse starts where idea checkers stop.
Searched in English only, GitHub and the open web; closed products and other languages not covered.

## 2026-11-08, first live run on the author's profile (reported from his machine)

The list was dominated by one lab (Emory) that shared a single OpenAlex topic with the author,
"Topic Modeling", a bucket that holds half of NLP. Two causes: the pool was seeded with 100 works
from each of the five top topics, bucket included; and topics were scored without document
frequency, so a bucket counted as much as a specific topic, with recency (up to 0.2) added on top.
Fixes, mirrored from what keywords already had: topic document frequency over the pool and damping
of the known bucket topics; the pool is seeded from the author's specific topics only (two of
them), with more keyword queries instead; recency multiplies overlap rather than adding to it;
the gate needs a shared keyword, a keyword-search hit, a card or a specific topic, and a score
above 0.05. A keyword-search hit with no OpenAlex keywords counts as one shared keyword, so arXiv
preprints found on the author's own terms keep their place.

Second live run (same day, from the author's machine) showed the first fix overshot: narrowing
the topic seed from five to two dropped the people who were only reachable through the third
topic (they were not demoted, they were no longer found), and single-word keywords sent as
literal queries to GitHub and Hugging Face returned VPN configs, an archiver and a game, each
pushed today and lifted by freshness above real scientists. Corrected: the seed is all specific
(non-bucket) topics up to five, since the df damping in score() is what makes buckets harmless;
only phrases of two or more words go to code, model and preprint search, and a hit must carry the
phrase contiguously in its name, description or tags; the keyword-search floor (0.15) earns no
freshness. Lesson kept: a unit test on score() does not catch a loss at the discovery stage;
the live run does.

## 2026-11-08, distribution

Vladimir's constraint, stated plainly: posting on his own channels has never moved anything, for any
of his products. So the channels used are the ones where other people's audiences or the product
itself bring the reader: a pull request to awesome-mcp-servers (Research section, #18892), a listing
request on mcp.so (#6933), a release pipeline that publishes to PyPI by trusted publishing and to the
official MCP Registry by GitHub OIDC on one tag (the user must register the pending publisher on PyPI
once), six cluster pages under docs/clusters generated from real runs (pages people search for, each
pointing back), and the product's own hands: propose_merge rounds to real authors, 10 issues a day,
every text shown to the user first. Not done, by rule: Glama and Smithery need an account sign-in
(his action); awesome-agent-skills refuses new skills without usage (submit in a month). The
ceiling in this niche is known: idea-reality-mcp, 830 stars in eight months.

Preparing the first round exposed four more things in the matcher and the plan: a cluster over 15
is split into a batch (the living leader plus the most recently active) rather than refused; a
sender who is not one of the authors says so in the first line ("Who is asking"); what a repository
brings is its own description when no feature is unique, never an invented "working implementation";
the merge target is the base repository, not a repository that does not exist. In the matcher: the
verb of the idea is required but not counted (a note-UID generator is not a site generator), a
distinctive job word must match (sessions-to-a-wearable is about the wearable), technical tokens
(pii, nl2sql) are sharp for membership but cannot alone name a related repository ("mcp server"),
and no merge is proposed where a 1000+-star leader has decided the field.
