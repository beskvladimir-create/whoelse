# Changelog

## 0.1.0 — 2026-11-07

First release.

- Profile from OpenAlex, arXiv, GitHub, Hugging Face, ORCID; namesakes are shown, never guessed.
- Discovery across papers (OpenAlex keywords and topics, arXiv preprints), code (GitHub) and models/datasets (Hugging Face); quantisation repacks filtered.
- Ranking with IDF-damped keywords so field-wide terms cannot carry a match.
- Identity guards: self-exclusion by ids, name merges need a second signal, organisations dropped.
- Reach: ORCID public contacts, GitHub profile, GitHub user search by full name (unique hit confirmed by repo subject), whoelse card at /.well-known/whoelse.json.
- joint_work_brief ranks formats by what each side actually has; draft_outreach gives facts and structure, never sends.
- Peers: add_peer, whats_new_from_peers, with concrete ways to support; no automated stars or follows.
- find_duplicates / propose_merge: what already exists for an idea, who won, what nobody has; a merge plan with one issue per author.
  Relevance on job words only; synonyms; search totals and "at least" when capped; four honest verdicts (field / won / cluster / parts exist).
  Merge limits per GitHub's acceptable use: 3-15 repositories, 10 issues a day, ledger, no forks/organisations/winners/own repos,
  approval bound to the exact texts shown (plan_id), rate limit stops the run.
- plugin/: Claude Code plugin with a before-you-build skill; the same text serves as rules for Cursor, Codex and other MCP clients.
- publish_request / start_joint_work / whoelse-watch: an open registry of requests, a workspace with a third of the work done, a watcher that starts joint work on a mutual match.
- 70 offline tests on recorded fixtures; one-command first run.
