# whoelse as a plugin

Install the MCP server first (`pip install git+https://github.com/beskvladimir-create/whoelse`).

**Claude Code**: `claude --plugin-dir ./plugin` from this repository (one session), or copy
`skills/dont-build-it-alone/SKILL.md` into `~/.claude/skills/dont-build-it-alone/` and add the server with
`claude mcp add whoelse -- whoelse`. The skill makes the agent call `find_duplicates` before it
starts building anything.

**Cursor / Codex / any MCP client**: add `{ "mcpServers": { "whoelse": { "command": "whoelse" } } }`
to the MCP config and paste the text of `skills/dont-build-it-alone/SKILL.md` into your rules file
(`.cursor/rules`, `AGENTS.md`).

What the user then sees, before a single line is generated:

> This exists 10 times; the top has 28 stars, the median 6. chunxue-ai/cc-archive is the most used;
> ccvault has encryption, cowork-backup-plugin has restore, none has both. Contribute, build the
> missing part, or propose a merge?
