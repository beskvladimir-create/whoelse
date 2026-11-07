# Publishing checklist (author only)

```bash
# 1. repository
gh repo create beskvladimir-create/whoelse --public --source=. --push \
  --description "Who else is working on what you're working on? An MCP server that finds them, says what you could build together, and drafts the first message. Papers, code, datasets, models. Local. Free."
gh repo edit beskvladimir-create/whoelse --add-topic mcp --add-topic mcp-server --add-topic research --add-topic collaboration \
  --add-topic openalex --add-topic arxiv --add-topic huggingface --add-topic claude --add-topic cursor --add-topic codex --add-topic ai-agents

# 2. the author's own card (so the first user of connected mode is the author)
#    put .well-known/whoelse.json at https://vladimir.besk.tech/.well-known/whoelse.json

# 3. first live run, then paste 3 real lines of output into README under "What you get"
WHOELSE_MAILTO=vladimir@besk.tech python -m whoelse.scripts.first_run "Vladimir Beskorovainyi" --orcid 0009-0004-7005-6242

# 4. PyPI (optional, after the run)
python -m build && twine upload dist/*

# 5. registries: submit to modelcontextprotocol/servers (community list), Smithery, mcp.so, PulseMCP, Glama
```

Launch post (one paragraph, no hype): what the pain is, what the tool did on the author's own name
(N people, M reachable, first replies), the install line, the card.
