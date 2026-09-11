Хватит — пишу итог по собранному. Непроверенное помечено.

## Итог одной строкой
Основные тезисы верны с поправками: Claude Code **не** читает AGENTS.md нативно и на сентябрь 2026 (issue #6235 закрыт 2026-08-17 самим bcherny как «completed» с отсылкой к `@AGENTS.md`/symlink — не реализацией); symlink имеет подтверждённую проблему записи; цифры «150 инструкций» — интерпретация IFScale, а не результат; заявленной «Stack Overflow/O'Reilly март 2026» статьи в приписанном виде нет.

---

## 1. AGENTS.md: спецификация, AAIF, кто читает

**Подтверждено.**
- Спека от OpenAI, август 2025; AAIF под Linux Foundation объявлен 2025-12-09; MCP + goose + AGENTS.md — якорные проекты. Платиновые: AWS, Anthropic, Block, **Bloomberg, Cloudflare**, Google, Microsoft, OpenAI (в вопросе два пропущены). «60 000+ проектов» — цифра из пресс-релиза LF. [LF press](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation), [OpenAI](https://openai.com/index/agentic-ai-foundation/)
- Нативно читают (по пресс-релизу LF): Amp, Codex, Cursor, Devin, Factory, Gemini CLI, Copilot, Jules, VS Code. Уточнения по своим докам:
  - **Cursor**: да, включая вложенные AGENTS.md по подкаталогам. [docs](https://cursor.com/docs/rules)
  - **Codex**: да, `~/.codex/AGENTS.md` → от git-root вниз, `AGENTS.override.md` приоритетнее, лимит `project_doc_max_bytes` 32 KiB по умолчанию, `project_doc_fallback_filenames` для альтернатив. [docs](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
  - **VS Code/Copilot**: `chat.useAgentsMdFile` (в одних источниках включён по умолчанию, в других «экспериментально и выключен» — **не уверен**, какое состояние актуально); вложенные — `chat.useNestedAgentsMdFiles`, экспериментально. [VS Code docs](https://code.visualstudio.com/docs/agent-customization/custom-instructions)
  - **Gemini CLI**: по умолчанию **только GEMINI.md**. AGENTS.md — через `context.fileName: ["AGENTS.md","GEMINI.md"]`. Issue #12345 «добавить AGENTS.md в дефолты» закрыт **not planned** 2026-05-08. Пресс-релиз LF считает Gemini CLI «поддерживающим» — фактически это «настраиваемо». [docs](https://geminicli.com/docs/cli/gemini-md/), [#12345](https://github.com/google-gemini/gemini-cli/issues/12345)
  - **OpenCode**: да, нативно. Порядок: локальные `AGENTS.md` → `CLAUDE.md` (fallback), затем `~/.config/opencode/AGENTS.md`, затем `~/.claude/CLAUDE.md`. Если есть оба локально — берётся только AGENTS.md. Скиллы: `.opencode/skills`, `.claude/skills`, `.agents/skills` (проект и глобально). [rules](https://opencode.ai/docs/rules/), [skills](https://opencode.ai/docs/skills/)
  - **Cline**: да, `AGENTS.md` и `~/.agents/AGENTS.md`, показывается в панели Rules (issue #11063 закрыт completed 2026-05-29). [docs](https://docs.cline.bot/customization/cline-rules)

**Claude Code — нативно НЕ читает (сентябрь 2026).**
- Официальная страница памяти: «Claude Code reads `CLAUDE.md`, not `AGENTS.md`». Рекомендуемый путь — `CLAUDE.md` с `@AGENTS.md` (+ Claude-специфика ниже), symlink «тоже работает, если не нужен Claude-специфичный контент». `/init` с `CLAUDE_CODE_NEW_INIT=1` и `/import` (v2.1.213+) делают одноразовую копию. [docs](https://code.claude.com/docs/en/memory#agentsmd)
- #6235 (5135 👍, 393 комментария) закрыт 2026-08-17 bcherny как `completed` с комментарием про `@AGENTS.md`/symlink — фактически «won't do, есть workaround». HN-тред 18.08.2026 назвал закрытие вводящим в заблуждение. #31005 (357 👍) открыт; #34235 открыт; #50778, #56193, #66352 (`.agents/skills`) закрыты как дубли/not planned ботом. Никакого сигнала о планах. [#6235](https://github.com/anthropics/claude-code/issues/6235), [#31005](https://github.com/anthropics/claude-code/issues/31005), [HN](https://news.ycombinator.com/item?id=49367350)

**Проблемы symlink CLAUDE.md → AGENTS.md (подтверждённые):**
1. **Запись через symlink отвергается**: `Edit`/`Write CLAUDE.md` → «Refusing to write through symlink». bcherny 2026-08-18: это намеренная защита, не баг; чтение работает; «treating this as a documentation gap»; если ждёте, что Claude будет сам править файл — используйте `@AGENTS.md`. Issue #66559 открыт. Та же ошибка при `.claude/` → symlink на `.agents/` (settings.json, mcp add). [#66559](https://github.com/anthropics/claude-code/issues/66559)
2. Windows: symlink требует admin/Developer Mode — доки прямо советуют import.
3. Cowork-сессии пропускают `~/.claude/CLAUDE.md`, если это symlink (из доков).
4. Двойная загрузка контекста: в HN-треде разработчик отмечал, что Claude сам находит и читает и symlink, и оригинал (**единичное свидетельство, не проверял**). [HN](https://news.ycombinator.com/item?id=48632144)
5. Нельзя добавить Claude-специфичные инструкции — только через import.
6. `/init` в `~/.claude` перезаписывал существующий CLAUDE.md (#21795, старый; актуальные доки говорят, что `/init` «предлагает улучшения, не перезаписывает»).

Вывод: `@AGENTS.md` в CLAUDE.md надёжнее symlink.

## 2. Red Hat, июль 2026

**Подтверждено дословно.** Dejan Bosanac, Red Hat Developer, 2026-07-27, «Standardize project context with AGENTS.md and Agent Skills»:
- «Aim for fewer than 150 lines; for smaller repos, 30 to 50 lines is plenty.»
- «The AGENTS.md content is sent with every prompt, so every unnecessary line dilutes the signal.»
- Индекс, а не свалка: «a directory for finding information rather than a place to dump everything», ссылки вида `docs/ARCHITECTURE.md`.
- Скрытое знание: «small invariants (things that fail silently) and core decision-making guardrails».
- Автогенерация: «auto-generated context files can hurt agent performance when they're full of generic information the model already knows»; «Review it, remove anything the agent can already figure out on its own... add the things only you know.»
- Скиллы: `.agents/skills/`, progressive disclosure.
[статья](https://developers.redhat.com/articles/2026/07/27/standardize-project-context-agentsmd-and-agent-skills)

Смежная: Red Hat Emerging Tech 2026-07-28 «Building skills for AI agents: pitfalls» — SKILL.md < 500 строк, 1–3 скилла на задачу, нерелевантные скиллы активно вредят, «hybrid» скрипты+LLM дал −26% cost. [ссылка](https://next.redhat.com/2026/07/28/building-skills-for-ai-agents-pitfalls-and-best-practices/)

Основа для «150 строк» — не собственное исследование Red Hat, а ETH-работа (см. п. 4).

## 3. «Stack Overflow / O'Reilly, март 2026»

**Частично.** Найдена Stack Overflow Blog, Ryan Donovan, 2026-03-26, «Building shared coding guidelines for AI (and people too)»:
- Явно: «Provide explicit examples of both correct and incorrect implementations of the code guidelines.» ✔
- Про эталонный файл — осторожнее, чем в утверждении: предлагает «gold standard» файл как end-to-end тест, но «there's some discussion on whether you only need the gold standard file, or whether it can work in concert with individual examples. We suggest testing.» Утверждения «работает лучше, чем проза» там **нет**.
- O'Reilly в ней упомянут только ссылкой на статью августа 2026. Отдельной O'Reilly-статьи марта 2026 с этим тезисом **не нашёл**. Ближайшее: O'Reilly Radar / Addy Osmani «Agent Skills», 2026-05-27 — «Process over prose», таблицы «неправильно → правильно». [SO](https://stackoverflow.blog/2026/03/26/coding-guidelines-for-ai-agents-and-people-too/), [O'Reilly](https://oreillyradar.substack.com/p/agent-skills)
- GitHub Blog (Matt Nigh, 2025-11-19, 2500+ репо): «real code snippets demonstrating style rather than descriptions», good/bad образцы, границы «Always / Ask first / Never». [ссылка](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/)

## 4. Размер CLAUDE.md, «150 инструкций», измерения

- **Anthropic docs (актуально)**: «target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence»; конкретика вместо расплывчатого («Use 2-space indentation» vs «Format code properly»); противоречия — «Claude may pick one arbitrarily»; `@import` не экономит контекст; `/doctor` (v2.1.206+) предлагает вырезать то, что выводится из кода. [docs](https://code.claude.com/docs/en/memory#write-effective-instructions)
- **HumanLayer «Writing a good CLAUDE.md»**: «Frontier thinking LLMs can follow ~150–200 instructions with reasonable consistency» со ссылкой на IFScale; «системный промпт Claude Code ≈ 50 инструкций» (оценка HumanLayer, **источника нет**); свой корневой файл < 60 строк; общий совет < 300 строк; против `/init`. [ссылка](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- **IFScale (arXiv 2507.11538, Jaroslawicz et al., Distyl, июль 2025)**: 500 keyword-инструкций в задаче отчёта. Порога «150» в статье **нет** — это интерпретация. Данные: o3 97.8% на 250 → 62.8% на 500; gemini-2.5-pro 98.4% (100) → 84.8% (250); claude-sonnet-4 94.8% (100) → 80% (250) → 39.9% (500); claude-opus-4 81.8% уже на 100. Паттерны: threshold decay (o3, gemini), linear (gpt-4.1, sonnet-4), exponential. Primacy bias пикует на 150–200. Важно: это простые keyword-инструкции, не правила поведения в коде; на актуальные модели 2026 не переносится напрямую. [arXiv](https://arxiv.org/abs/2507.11538)
- **ETH Zürich / LogicStar «Evaluating AGENTS.md» (arXiv 2602.11988, Gloaguen et al., фев. 2026, ревизия июнь 2026)**: контекстные файлы «не улучшают success rate в целом», стоимость +20%+; LLM-сгенерированные ≈ −3% успеха, написанные людьми ≈ +4% при +19% стоимости (цифры из пересказов Upsun/Medium — **в abstract не приведены**, не уверен); «repository overviews... are not helpful»; вывод: «human-written context files should describe only minimal requirements». Агенты: Claude Code/Sonnet 4.5, Codex/GPT-5.2 и 5.1-mini, Qwen Code. Именно на неё опираются Red Hat и «150 строк». [ETH](https://www.sri.inf.ethz.ch/publications/gloaguen2026agentsmd), [Upsun](https://developer.upsun.com/posts/ai/agents-md-less-is-more)
- Вторая работа (arXiv 2601.20404, Treude et al., янв. 2026, 124 PR / 10 репо): наличие AGENTS.md связано с −28.6% runtime и −16.6% output tokens — корреляционная, противоречит ETH по стоимости. [arXiv](https://arxiv.org/abs/2601.20404)
- Про скиллы: O'Reilly 2026-05-18 — курируемые скиллы +16.2%, написанные моделью — без стабильного эффекта, 26% community-скиллов с уязвимостями. [ссылка](https://www.oreilly.com/radar/agent-skills-work-but-the-research-shows-most-teams-are-building-them-wrong/)

## 5. Cline Memory Bank

- **Подтверждено**: шесть файлов, иерархия от projectbrief, команда «update memory bank» (MUST review ALL files), страница жива в официальных доках, без deprecation. Сам Cline позиционирует его как «методологию через custom instructions/.clinerules, не фичу». [docs](https://docs.cline.bot/features/memory-bank)
- Не «заменён», но окружён альтернативами: Cline Rules (`.clinerules/`, куда рекомендуют класть инструкции memory bank), Workflows (`.clinerules/workflows/`), Auto Compact, `/newtask`, `/smol`, lifecycle hooks (на них строятся сторонние memory-интеграции вроде Hindsight, июнь 2026, аргумент — «нет tool-call, который модель может забыть»). [Hindsight](https://hindsight.vectorize.io/blog/2026/06/09/cline-persistent-memory)
- Слабость «всё зависит от дисциплины агента» подтверждена практиками: «works only as well as your discipline at updating it. No automatic capture, no conflict resolution»; известный старый баг #1911 (Cline «обновил» файлы только в чате). Токены: Cline сам признаёт стоимость («Yes, reading memory files costs tokens»), в discussion #1727 жалоба $30 → $230/мес при memory bank. Заметка про тормоза при файлах > 2000 строк — из японского блога, **не проверял**.
- Длинных практических ретроспектив «через полгода дрейфует ли» **не нашёл**; найденный обзор августа 2026 (thinkdifferent.blog) — общий, без данных.
- **Roo Code**: memory bank — community-проект GreatScottyMac (roo-code-memory-bank / RooFlow), не в ядре; автор намекал на «возможно последнее обновление». Roo встроил Codebase Indexing и context condensing, но это не замена. Roo Code при этом поддерживает Agent Skills. [repo](https://github.com/GreatScottyMac/roo-code-memory-bank)

## 6. SKILL.md / agentskills.io

- **Подтверждено**: стандарт от Anthropic, открыт (декабрь 2025 — по внешним источникам, на сайте даты нет); на витрине сайта **~45 клиентов**; спека: name ≤ 64, description ≤ 1024, body «< 5000 tokens recommended», «under 500 lines», progressive disclosure в 3 уровня. [spec](https://agentskills.io/specification)
- Где ищут:
  - **Claude Code**: `~/.claude/skills`, `.claude/skills` (в т.ч. вложенные подкаталоги, `--add-dir`, managed, плагины). `.agents/skills` **не читает**, запросы закрыты not planned. Лимит description+when_to_use 1536 символов в листинге; после compaction сохраняются первые 5000 токенов скилла, общий бюджет 25 000. [docs](https://code.claude.com/docs/en/skills)
  - **Codex**: `.agents/skills` от cwd вверх до git-root, `~/.agents/skills`, `/etc/codex/skills`, системные. Про `.codex/skills` в текущих доках **нет** (старые статьи упоминают — вероятно устарело). [docs](https://learn.chatgpt.com/docs/build-skills)
  - **Gemini CLI**: `~/.gemini/skills` или `~/.agents/skills`; `.gemini/skills` или `.agents/skills`; `.agents` приоритетнее в своём уровне. `.claude/skills` не читает. [docs](https://geminicli.com/docs/cli/skills/)
  - **OpenCode**: все три — `.opencode/skills`, `.claude/skills`, `.agents/skills` (проект + глобально).
- **Общего каталога для всех четырёх нет.** `.agents/skills` покрывает Codex + Gemini + OpenCode; Claude Code — только `.claude/skills`. Практика: держать `.agents/skills`, а `.claude/skills` — symlink на него (или наоборот); учесть, что Claude Code отказывается **писать** через symlink-каталог `.claude/` (settings, mcp add — см. #66559).

## 7. llms.txt

- Спека (llmstxt.org): «The 'Optional' section is used, by convention, for secondary information: links an agent can skip when a shorter context is needed.» Структура: H1 → blockquote → произвольные секции → H2-списки файлов.
- Статус 2026: файлов стало 36 120 (было 4 088 в июне 2025), но Ahrefs (137k доменов, май 2026): 97% llms.txt получили ноль запросов, AI-боты — 1.1% от пришедших. Google не поддерживает (июль 2025, планов нет), OpenAI не упоминает, Anthropic публикует свой, но парсинг чужих не подтверждён; Perplexity — единственный заявивший, что использует. Итог: «публикуется быстрее, чем читается». Реальная польза — как индекс для агентов, которых вы сами направляете (у Claude Code docs и agentskills.io он есть, и мой WebFetch его видел). [mecanik](https://mecanik.dev/en/posts/does-llms-txt-do-anything-yet/)

## 8. Compound Engineering (Every)

- Репо `EveryInc/compound-engineering-plugin`: 25 001 ⭐, релиз v3.24.0 от 2026-08-31, push 2026-09-10, 14 хостов (Claude Code, Cursor, Codex, Copilot, Cline, OpenCode, Pi, Devin, Factory и др.). Цикл: `/ce-brainstorm → /ce-plan → /ce-work → /ce-simplify-code → /ce-code-review → /ce-compound`, `/lfg` — всё автоматом. Пространство команд переименовано (`/workflows:*` → `/ce-*`), релизы почти ежедневно — доки и привычки устаревают. [repo](https://github.com/EveryInc/compound-engineering-plugin)
- «Каждый баг → правило»: тезис Klaassen'а («Every bug becomes a rule that stops it from happening twice»). Но `/ce-compound` пишет в **`docs/solutions/`** (и `docs/plans/`, `todos/`), а не в CLAUDE.md; гайд Every при этом говорит «CLAUDE.md — самый важный файл, кладите preferences/patterns туда» и «add a note so the agent learns» — **ничего о прунинге**. Есть `/ce-compound-refresh`. [guide](https://every.to/guides/compound-engineering)
- Критика:
  - Issue #1265 (июль 2026, закрыт PR #1399): проверка конфликтов сравнивала только docs/solutions между собой и пропускала противоречия со скиллами/runbook/AGENTS.md — агент нарушил задокументированное правило, потому что скилл говорил обратное. «A document that disagrees with the skill an agent loads is actively steering behaviour the wrong way.» [#1265](https://github.com/EveryInc/compound-engineering-plugin/issues/1265)
  - Энциклопедия паттернов (апр. 2026): сценарий «через два месяца 200 правил и 40 скиллов, половина противоречит, агент следует первому увиденному»; лечение — GC-проход, кодифицировать на третьем повторе. [ссылка](https://aipatternbook.com/compound-engineering)
  - Обзор Ry Walker (июнь 2026): рост с 26 до 50+ агентов и 23 → 38+ команд, параллельные ревью-агенты жрут контекст, «overkill for quick fixes»; рекомендует только solo/малым командам. [ссылка](https://rywalker.com/research/compound-engineering-plugin)
  - wotai.co: CLAUDE.md распухает до 800 строк, если валить процесс и контекст кодовой базы в один файл; совет — процесс в AGENTS.md, код-контекст в CLAUDE.md. [ссылка](https://wotai.co/blog/compound-engineering-agents-md)
- Итог: «CLAUDE.md bloat» — реальная жалоба, но в самом плагине рост идёт в `docs/solutions/`; конфликты правил — задокументированная проблема с частичным фиксом.

## Что не проверил / не нашёл
- «Stack Overflow / O'Reilly март 2026» с тезисом «эталонный файл лучше прозы» — в таком виде нет.
- Точные −3%/+4% ETH — из пересказов, не из abstract.
- Дата «декабрь 2025» для agentskills.io и «~40 клиентов» — по внешним источникам; на сайте ~45 логотипов.
- Состояние `chat.useAgentsMdFile` по умолчанию в VS Code.
- Amp: страница AGENTS.md в мануале есть, содержимое не вытащил.
- Долгосрочные ретроспективы Cline Memory Bank с данными о дрейфе.
