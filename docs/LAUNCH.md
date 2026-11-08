# Launch texts

All numbers below are from a real run on 2026-11-08 (see docs/demo.png). Replace nothing unless the run changes.

## Show HN

**Title:** Show HN: whoelse – before your agent builds the 21st copy, find the other 20 and merge

**Text:**

I asked Claude Code to build a CLI that syncs sessions across machines. whoelse answered before the first line: it exists at least 40 times, the leader has 320 stars, the other 39 have a median of 1. Between them they already have encryption, R2, git, Drive, LAN; none has a TUI, hooks or cost tracking.

Idea checkers exist (idea-reality-mcp is good and I use the same GitHub search). whoelse starts where they stop:

- a feature matrix across the cluster: who has what, what only one has, what none has;
- `propose_merge`: the living leader as base, what each repo brings, every author a maintainer, a release date, and one issue drafted per author in their own repo. Nothing is sent without your yes; 3–15 repos, 10 a day, never twice, never to archived/forks/orgs/1000+ stars, per GitHub's acceptable use;
- the other half: who is working on the same thing right now (OpenAlex, arXiv, GitHub, Hugging Face), what the two of you could build, and a repository with a third of the work done before the first message.

MCP server, Python, MIT, no account, no server; a Claude Code plugin with a skill that runs the check before the agent starts building.

What it is not: it matches one-line descriptions, not READMEs. It will miss a project whose description doesn't say what it does. On my ten test ideas it got nine right and one incomplete; the misses are in DECISIONS.md.

https://github.com/beskvladimir-create/whoelse

## Reddit (r/ClaudeAI, r/cursor, r/opensource)

**Title:** I made my agent check who already built it before it builds it, and draft the merge

**Text:**

Every "build me X" prompt produces the 21st copy of X. Twenty people each get ten stars and nobody wins.

whoelse is an MCP server + Claude Code plugin. Before writing code the agent calls it and says: this exists 40 times, the leader is claude-sync (320★), the rest have a median of 1 star, here is what only one of them has and what none has. Then three options: contribute to the leader, build only the missing part, or propose a merge: one repo, every author a maintainer, one issue per author drafted for you to approve.

Screenshot is a real run. Free, MIT, no account. Limits are in the code so it can't become spam (3–15 repos, 10 issues a day, your explicit yes for every text).

Also finds who is working on the same research problem right now and drafts the first message. That half needs your ORCID/GitHub and is slower.

github.com/beskvladimir-create/whoelse

## X / LinkedIn (short)

Asked my agent to build a session-sync CLI. whoelse answered first: "exists 40 times, leader 320★, the rest median 1★, none has a TUI or cost tracking. Contribute, build the gap, or merge the 39?"

Before you build it alone. MCP server, MIT.
github.com/beskvladimir-create/whoelse

---

## Русские переводы (для себя; публиковать английские)

**Show HN.** Заголовок: whoelse, прежде чем агент построит 21-ю копию, найди остальные 20 и объедини.

Текст: Попросил Claude Code сделать CLI для синхронизации сессий между машинами. whoelse ответил до первой строки: это есть не меньше 40 раз, у лидера 320 звёзд, у остальных 39 медиана 1. Вместе у них уже есть шифрование, R2, git, Drive, LAN; ни у одного нет TUI, хуков и учёта стоимости.

Проверки идей существуют (idea-reality-mcp хорош, я использую тот же поиск GitHub). whoelse начинается там, где они заканчиваются: матрица фич по кластеру; `propose_merge` с живым лидером как базой, вкладом каждого репозитория, каждым автором в мейнтейнерах, датой релиза и одним issue на автора в его репозитории (ничего не отправляется без вашего «да»; 3–15 репозиториев, 10 в день, никогда дважды, никогда в архивные, форки, организации и 1000+ звёзд, по правилам GitHub); и вторая половина: кто прямо сейчас делает то же самое (OpenAlex, arXiv, GitHub, Hugging Face), что вы могли бы сделать вместе, и репозиторий с третью работы до первого письма.

MCP-сервер, Python, MIT, без аккаунта и сервера; плагин для Claude Code с навыком, который запускает проверку до того, как агент начнёт строить.

Чем это не является: сопоставляет однострочные описания, не README. Пропустит проект, в описании которого не сказано, что он делает. На десяти тестовых идеях девять верных, одна неполная; промахи записаны в DECISIONS.md.

**Reddit.** Заголовок: Я заставил агента проверять, кто уже это сделал, прежде чем строить, и готовить слияние.

Текст: Каждый запрос «сделай мне X» рождает 21-ю копию X. Двадцать человек получают по десять звёзд, и никто не выигрывает. whoelse это MCP-сервер и плагин для Claude Code. До кода агент вызывает его и говорит: это есть 40 раз, лидер claude-sync (320★), у остальных медиана 1 звезда, вот что есть только у одного и чего нет ни у кого. Дальше три варианта: вклад в лидера, строить только недостающее, или слияние: один репозиторий, каждый автор мейнтейнер, по одному issue на автора, которые вы утверждаете. Скриншот с реального прогона. Бесплатно, MIT, без аккаунта. Ограничения зашиты в код, чтобы это не стало спамом. Ещё находит, кто сейчас работает над той же исследовательской задачей, и готовит первое письмо; эта половина требует ORCID/GitHub и медленнее.

**X / LinkedIn.** Попросил агента сделать CLI для синхронизации сессий. whoelse ответил первым: «есть 40 раз, лидер 320★, у остальных медиана 1★, ни у кого нет TUI и учёта стоимости. Вклад, пробел или слияние 39?» Прежде чем строить в одиночку. MCP-сервер, MIT.
