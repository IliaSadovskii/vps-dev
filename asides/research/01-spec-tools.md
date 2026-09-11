Итог: ландшафт SDD-инструментов жив, но практики массово сползли к «plan mode + короткие спеки»; главная нерешённая проблема — дрейф спек, и её никто из большой тройки (OpenSpec / Spec Kit / Kiro) толком не закрыл.

## 1. OpenSpec (Fission-AI)

**Жив, активно.** Проверено через GitHub API 2026-09-10: 67 876 звёзд, 4 665 форков, 228 открытых issues (115 из них — issue, остальное PR), последний push 2026-09-09. Релизы еженедельно: v1.13.0 (09-09, «Apply warnings, safer archives»), v1.12.0 (09-03, «Findings Reports»), v1.11.0 (08-26, «Spec Diffs»), v1.10.0 (08-19, Zed), v1.9.0, v1.8.0. npm `@fission-ai/openspec` тот же ритм, 1.0.0 вышел 2026-01-26.
- https://github.com/Fission-AI/OpenSpec/releases

**Заявленные фичи — все реальны:**
- `/opsx:*` — propose, explore, apply, archive (core); new, continue, ff, update, verify, sync, bulk-archive, onboard (expanded). https://github.com/Fission-AI/OpenSpec/blob/main/docs/opsx.md
- Дельты `## ADDED / MODIFIED / REMOVED` (+ RENAMED) Requirements; `/opsx:sync` и `archive` вливают их в главные спеки.
- `openspec validate` есть: `--all/--changes/--specs/--archived/--strict/--json`, с 1.12 `--report findings`; сверяет MODIFIED с главной спекой, падает если у change нет дельт (если не `skip_specs: true`). https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md
- Brownfield-first — прямо в README: «built for brownfield not just greenfield», «fluid not rigid».
- Новое: `openspec show --diff` (1.11), Stores (кросс-репо спеки, beta), «Findings reports» (1.12).

**Практики (реальные посты):**
- **layandreas** (Andreas Lay) — https://layandreas.github.io/personal-blog/posts/beyond-videcoding/ (2026-06-26). **Позитивный**: OpenSpec = «fancier plan mode», использует и на greenfield, и на legacy, плюс параллельные ревью-агенты (Open Code Review). Не он бросал ради Instructions.md — это смешение двух авторов.
- **Эксперимент с фронтенд-редизайном и Instructions.md** — автор **«Incomplete Developer»** (dev.to/@incomplete_developer, 2026-04-01): https://dev.to/incomplete_developer/openspec-spec-driven-development-failed-my-experiment-instructionsmd-was-simpler-and-faster-3a5d. .NET Razor Pages, 3 попытки (OpenSpec+GPT-5.3 Codex; OpenSpec+Copilot+Haiku 4.5; просто Instructions.md). Вывод: «introduced a lot of overhead without delivering better results», редизайн UI вышел «почти идентичен оригиналу». Конкретных чисел токенов нет — только «a lot of tokens».
- **kd05** — https://kd05.com/p/openspec-opencode-experience/ (2026-03-24), «several weeks», **остался на OpenSpec**, хвалит дельты для legacy. Чисел нет.
- **Peng Qian (qtalen)**, полгода командного использования, ушёл на AWS AIDLC: https://dev.to/qtalen/from-openspec-to-aidlc-how-i-improved-my-teams-ai-code-quality-3mn2 (2026-09-09). Проблемы: путаница explore vs propose → команда откатилась к vibe coding; спеки не хранят исходное «почему»; **дрейф — код не возвращается в спеки**; непонятно когда вообще запускать процесс; нет командных гейтов ревью.
- **HN, alasano** (2026-05-03, в треде «Specsmaxxing», 287 очков / 295 комм.): «When you do the sync process, it just keeps drifting and drifting until you have duplication and contradictions across specs» — отказался от sync, архивирует сразу. https://news.ycombinator.com/item?id=47994433
- **«Bugfix → 4 user stories, 16 acceptance criteria»** — есть у Zarar Siddiqi (2026-02-25) https://zarar.dev/spec-driven-development-from-vibe-coding-to-structured-development/, но относится к **Kiro**, не к OpenSpec, и подано как «One developer reported…» без ссылки. Первоисточник не нашёл.
- **«2M tokens/day»** — **не нашёл** ни в HN-комментариях (algolia), ни в блогах, ни в issues. Считать непроверенным. Что есть по токенам: бенчмарк Jamie Telin — Spec Kit ~2× дороже OpenSpec (57.7k vs 120.9k и 91.7k vs 181k токенов на задачу) https://medium.com/it-chronicles/is-your-safe-choice-burning-your-budget-1cfddf8782e4 (сам пост не открылся, цифры из сниппета).
- Ran the Builder (Itzhak Eretz Kdosha, Palo Alto Networks, 2026-04-13): OpenSpec 4.00 > BMAD 3.74/3.65 > Spec Kit 2.77. https://ranthebuilder.cloud/blog/i-tested-three-spec-driven-ai-tools-here-s-my-honest-take/

**Дрейф в issues самого проекта:** #880 (открыт с марта) — просят `/opsx:validate` для сверки кода с живыми спеками, до сих пор нет; #1387 — сторонний `concord` (lucinate-ai, 2 звезды) ловит drift/overlap параллельных changes до archive; #1430 — fitness functions. То есть валидация в OpenSpec структурная (формат дельт), не «код ↔ спека».

## 2. GitHub Spec Kit

134 549 звёзд, 304 открытых, push ежедневно; **v1.0.0 вышел 2026-08-21**, сейчас 1.0.6 (09-10). Заметная эволюция: presets / extensions / bundles / workflows, 30+ агентов, `/speckit.constitution|specify|plan|tasks|implement|converge` + clarify/analyze/checklist. https://github.com/github/spec-kit/releases

Критика (устойчивая, повторяется год):
- Discussion #1784 «SpecKit creates the illusion of work» (NaikSoftware): тонны текста топят LLM, игнор структуры проекта, сотни ненужных тестов; мейнтейнер scotteveritt признаёт — для мелочи лучше Plan Mode. https://github.com/github/spec-kit/discussions/1784
- Issue #1401 (15 реакций): команды съедают заметную часть контекста в каждой сессии; #620 «как держать спеки актуальными» — открыт с 2025-09.
- Marmelab: одна фича «показать дату» = 8 файлов, ~1 300 строк.
- HN «Understanding SDD» (128 очков): yoaviram — 10 дней на первый проект, «massive gaps with failing tests». https://news.ycombinator.com/item?id=45610996
- HN «Waterfall Strikes Back»: ErrantX — «many many hours tweaking» до первой строки кода.
- Общий консенсус практиков: окупается на крупных/регулируемых/командных изменениях, overkill для фиксов. Есть форк spec-kitty с положительным отзывом (HN 46966273).

## 3. Kiro (AWS)

- **Steering files** — да: `.kiro/steering/` и `~/.kiro/steering/`, product/tech/structure.md, режимы always/fileMatch/manual/auto; **в CLI режимы включения не поддерживаются — грузится всё**. AGENTS.md поддерживается. https://kiro.dev/docs/steering/
- **Hooks** — да: PostFileSave/Create/Delete (IDE only), PromptSubmit (может блокировать), AgentStop, Pre/PostToolUse, SessionStart/AgentSpawn; глобальные хуки в `~/.kiro/hooks/` (CLI 2.13). https://kiro.dev/docs/hooks/
- **«Review mode»** — под этим именем нет. Есть **Supervised mode** (IDE, пауза после каждой правки, hunk-и принять/отклонить) vs Autopilot, и **spec review screen** в CLI 2.18 (2026-08-12, Ctrl+X — читать документ фазы и ставить построчные комментарии). Открыт запрос на гибрид #6705. https://kiro.dev/changelog/cli/2-18/
- **Не Claude-only.** Модели: Claude Opus 5 / 4.8 / 4.7…, Sonnet 5, Haiku 4.5; **OpenAI GPT-5.6 Sol/Terra/Luna (experimental), GPT-5.4**; open weights MiniMax M2.5, GLM-5, DeepSeek 3.2, Qwen3 Coder Next; Nemotron 3 Super; «Kiro Router Auto». https://kiro.dev/docs/models/available-models/ . Через Bedrock — да для GPT-5.4 (AWS what's-new 2026-06-30: «runs on Amazon Bedrock's next-generation inference engine»); для остальных прямого подтверждения в доках нет, только сторонние обзоры. BYOK нигде не упомянут.
- **kiro-cli** — самостоятельный, `curl -fsSL https://cli.kiro.dev/install | bash`, headless/CI, ACP, специ/steering/hooks/MCP/subagents; версия 2.21.0 (09-01), «V3» через `kiro-cli --v3`. https://kiro.dev/docs/cli/
- Обратная связь: Gartner — от 5.0 до 3.0 («Good CLI, but not as feature full»); безопасность — CVE-2026-10591 (steering/MCP overwrite через скрытый текст на странице), ещё 4 CVE, обзор drel.ai 2026-08-06 https://drel.ai/blog/kiro-security-review . Kiro issue #9435 (июнь) просит записывать git ref в спеку для детекта дрейфа — открыт, 0 реакций.
- Утверждение о «May 2026 TDD spec flow» — из сниппета, в доках не подтвердил. **Не уверен.**

## 4. HN-треды и Marmelab

- **«Ask HN: What Happened to Spec-Driven Development?»** — существует, но крошечный: 3 очка, 4 комментария, 2026-08-06. https://news.ycombinator.com/item?id=49182353 . OP (vivekyyy): инструменты «kinda fell off», все жалобы остались, все сели на /plan mode. Комменты: единственный source of truth — код (mikgp); «agents are already too good», хватит plan.md + verification loop (thiago_fm); спеки нужны против «invent features» (2dera).
- **«Spec-Driven Development: The Waterfall Strikes Back»** — Marmelab, François Zaninotto, 2025-11-12; HN 225 очков / 191 комм. https://marmelab.com/blog/2025/11/12/spec-driven-development-waterfall-strikes-back.html , https://news.ycombinator.com/item?id=45935763 . Тезисы: 80% времени читаешь markdown, агенты спеки всё равно игнорируют, ревью ×2, на больших кодовых базах не работает; альтернатива — «Natural Language Development», мелкие тестируемые куски. Ключевые комменты: podgorniy «specs are great for grounding»; constantcrying — поддержка спек↔код растёт экспоненциально; macrolime — SDD выгоден примерно от ~100k строк; ErrantX — фрустрация со Spec Kit. Контр-посты: Marc Brooker (AWS) «Spec Driven Development isn't Waterfall» https://brooker.co.za/blog/2026/04/09/waterfall-vs-spec.html .
- Смежные: «Ask HN: SDD where the specs go stale» (2025-12, 46362091), «Are you still using SDD?» (2026-02, 46864948 — «spec kit works in brownfield», предупреждения о context bloat), «Why SDD when code IS spec?» (2026-02-28, 47194035), «Are you using SDD?» (2026-06-12, 48510002 — OP жалуется на гигиену кода даже с OpenSpec; люди уходят на compound-engineering, gsd, «сильная модель пишет спеку, дешёвая реализует»).

## 5. Tessl

Пивот подтверждён: **2026-01-29 «Skills on Tessl: the package manager for agent skills»**, позиционирование «Agent Enablement Platform» (enterprise/governance). https://tessl.io/blog/skills-are-software-and-they-need-a-lifecycle-introducing-skills-on-tessl . Spec Registry (open beta 2025-09-16) стал Skills Registry; Framework (spec-as-source) — по обзору codemyspec от 2026-06-03 всё ещё closed beta, только JS. Текущее: `@tessl/cli` релизится почти ежедневно (0.107.0 2026-09-09), в августе — Tessl Code Review (free beta, стандарты как версионированные файлы в репо) и Tessl Agent (private beta). $125M поднято, ~59 сотрудников (Tracxn, май). Layoffs/закрытие не нашёл.

## 6. Что мимо большой тройки: подходы к дрейфу

- **Spec-as-executable / equivalence harness**: Berkeley EECS-2026-158 (Sida Wang, 2026-05-15) — синтез исполняемых спек (генератор входов + reference, equivalence-тесты на уровне функций, Syzygy: C→Rust 3k строк с 1M equivalence-входов). https://www2.eecs.berkeley.edu/Pubs/TechRpts/2026/EECS-2026-158.pdf
- **Spec как quality gate для ревью**: arXiv 2603.25773 (Zietsman) — без исполняемой спеки генератор и ревьюер рассуждают из одного артефакта и коррелированно ошибаются; порядок: спека → детерминированная верификация → AI-ревью только для остатка.
- **Инструменты drift detection**: fiberplane/drift (144 звезды, «bind specs to code», tree-sitter AST-fingerprint; последний push 2026-06-22 — похоже заглох) https://github.com/fiberplane/drift ; asmuelle/spec-drift (0 звёзд, Rust); concord для OpenSpec (см. выше). Все — маргинальные.
- **Verification loop** как продуктовая фича: Traycer (после реализации сверка с спекой, расхождения по severity) https://docs.traycer.ai/tasks/verification ; Intent (living specs). Отзывы сторонние (Augment Code — маркетинг конкурента), независимых практиков не нашёл.
- **Практики из HN без инструментов**: YAML-спеки с нумерованными тегами, по которым grep-ится код (jochem9/arikrahman в «Specsmaxxing»); git-trailer с UUID сессии Claude для восстановления «почему» (bizzletk); OpenSpec-issue #900 — тест-генерация как мост SDD→TDD.
- Kiro #9435 — git ref в метаданных спеки, чтобы предупреждать «3 commits touched related files since spec created» — идея простая и ни у кого не реализована.

## Непроверено / не нашёл
- «2M tokens/day» — источник не найден после 4 запросов.
- Первоисточник «4 user stories / 16 AC» — только пересказ у Zarar, про Kiro.
- Reddit-треды по OpenSpec — поиск ничего содержательного не выдал.
- HackerNoon-статьи (showdown, AIDLC) — 403; данные по ним из сниппетов и dev.to-зеркала.
- Kiro TDD spec flow (май 2026) и «все модели через Bedrock» — только сторонние сниппеты.
