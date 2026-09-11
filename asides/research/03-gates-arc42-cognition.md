Поиск остановлен по запросу координатора; ниже итог по собранному. Даты релизов и статус «archived» проверены через GitHub API (`gh api`) 2026‑09‑10, остальное — по страницам/статьям; непроверенное помечено.

# Отчёт

## 1. Fitness‑функции по стекам

**Java**
- ArchUnit: **1.3 реальна, но устарела** — v1.3.0 апрель 2024; далее 1.4.0 (фев 2025), 1.4.1, 1.4.2 (апр 2026), **последний релиз v1.5.0 — 2026‑08‑04**, репозиторий активен (push 2026‑09‑08, 3.8k★). https://www.archunit.org/news
- Spring Modulith: 1.4 GA — 2025‑05‑28 (Boot 3.5), уже не текущая ветка: 2.0.x, 2.1.1, 2.2 M1 (авг 2026), 1.4.13 в поддержке. https://spring.io/blog/2025/05/28/spring-modulith-1-4-1-3-6-and-1-2-13-released/ , https://spring.io/blog/2026/08/26/spring-modulith-2-2-m1-2-1-1-2-0-8-and-1-4-13-released/
- jMolecules: 2.0 (ноя 2025, «stereotype metamodel»), 2.0.1 — 2025‑11‑20; последний push фев 2026. Жив, но темп низкий. http://odrotbohm.github.io/2025/11/jmolecules-2.0-stereotypical/

**TypeScript**
- dependency-cruiser: v18.2.0 (2026‑08‑10), 7.1k★, активен.
- eslint-plugin-boundaries: v7.2.0 (2026‑08‑09), flat config ESLint 9 поддержан, ~1k★, активен. https://github.com/javierbrea/eslint-plugin-boundaries
Оба живы; рекомендация без изменений.

**Python**
- import-linter: релизов на GitHub нет (только теги/PyPI); по release notes 2.7 — ноябрь 2025 (новый контракт `acyclic_siblings`, `protected`, Python 3.14); push 2026‑09‑04. Жив. https://seddonym.me/2025/11/12/six-lines-of-code/
- tach: переехал gauge-sh → **tach-org**, v0.35.0 (2026‑05‑12), 2.8k★, push сент 2026, Rust‑ядро. Сравнение с import-linter в их discussion #72 (tach: `tach sync`, strict interfaces; import-linter: ручные контракты). https://github.com/tach-org/tach/discussions/72

**PHP**
- deptrac: `qossmic/deptrac` на Packagist помечен abandoned → **`deptrac/deptrac`**; 4.7.1 — 2026‑07‑23, 3k★, PHP ≥8.2, push авг 2026. Жив. https://packagist.org/packages/deptrac/deptrac
- phpat: плагин PHPStan ^2.1, 0.12.4 (2026‑03‑17), 1.3k★, push авг 2026. Жив.
- PHPArkitect: 1.3.0 (2026‑07‑31), 0.9k★, baseline, phar. Жив.

**Go**
- go-arch-lint: v1.19.0 — **2026‑09‑07**, 553★. Жив.
- arch-go: v2.1.2 (2026‑02‑03), 273★, push сент 2026. Жив.
- depguard (OpenPeeDeeP): v2.0.0 (2023), последний push март 2025 — де‑факто «готовый» линтер внутри golangci-lint, не архитектурный инструмент; только запрет импортов.

**Rust**
- cargo-modules: 1.3k★, push сент 2026, но **это визуализация**, не enforcement (есть `orphans --deny` и `dependencies --acyclic`). Релизов через GitHub нет (crates.io — не проверял). https://github.com/regexident/cargo-modules
- cargo-deny: 0.20.2 (2026‑07‑09), 2.4k★, Embark. Это лицензии/advisories/бан крейтов, **не** слои архитектуры.

**.NET**
- ArchUnitNET (TNG): 0.13.4 — **2026‑08‑19** (страницы релизов давали 2024 — ошибочно, API подтверждает 2026), 1.4k★, push 2026‑09‑10. Жив.
- NetArchTest (BenMorris): последний релиз v1.3.2 — **2021**, push июль 2024. Мёртв. Замена — NetArchTest.eNhancedEdition v1.4.5 (июнь 2025, 53★, Slices API для циклов). https://github.com/NeVeSpl/NetArchTest.eNhancedEdition
Рекомендация: ArchUnitNET.

**«AI architecture drift» как термин.** Точной устойчивой формы «AI architecture drift» не нашёл. Есть:
- Thoughtworks Radar Vol. 34 (апр 2026), техника **«Architecture drift reduction with LLMs»**, кольцо Assess: ArchUnit/Spectral/Modulith + LLM‑оценка, «garbage collection» для энтропии. https://www.thoughtworks.com/radar/techniques/architecture-drift-reduction-with-llms
- arXiv 2604.04990 «Architecture Without Architects» (апр 2026) — термин **«vibe architecting»**, 5 механизмов неявных архитектурных решений агентов. https://arxiv.org/abs/2604.04990
- arXiv 2606.27045 «The Spec Growth Engine» (Grabowski, июнь 2026) — «silent spec‑code drift», drift gate, walking skeleton, fitness functions. https://arxiv.org/abs/2606.27045
- Вендорские посты (Mneme HQ на dev.to — без данных, реклама), GitHub Action «Drift — Architectural Erosion Check» (mick-gsk/drift, 15★, MIT, одиночный автор).
Итого: тема реальная, термин ещё не устоялся; «architectural drift» + «AI‑assisted» — рабочая формулировка.

## 2. Copy‑paste детекторы
- **jscpd v5.2.0 (2026‑09‑08)**: переписан на Rust (нативный бинарник через npm optionalDependencies), 224 языка, `--threshold` — процент дублирования, при превышении падает CI; репортеры SARIF/CodeClimate/Markdown/«AI». Лучший кандидат для CI с порогом. https://github.com/kucherenko/jscpd
- **PMD CPD**: PMD 7.27.0 (2026‑08‑28). Падает при любом дубле (`--fail-on-violation`, exit 4), порог — только `--minimum-tokens`; **процентного порога нет**, 25+ языков. https://pmd.github.io/pmd/pmd_userdocs_cpd.html
- phpcpd (sebastianbergmann): **архив с 2023**. Преемник phpcpd-next (v1.4, авг 2026, 34★, PHP 8.5+, Type‑3 клоны) — молодой. https://github.com/phpcpd-next/phpcpd
- Simian: **open‑sourced под Apache 2.0** (quandarypeak/simian, v4.2.1 апр 2026, 18★). Раньше был коммерческим. https://simian.quandarypeak.com/

## 3. GSD и context rot
- Репозиторий `gsd-build/get-shit-done` (бывш. glittercowboy) **archived: true**, уведомление на странице — 26 июня 2026; последний релиз v1.42.3 (2026‑05‑16), 64.6k★.
- Преемник: **open-gsd/gsd-core** («Git, Ship, Done!»), v1.13.0 (2026‑09‑06), 9.3k★, активен. Причина форка (discussion #109, 2026‑05‑22): автор TÂCHES молчит с 2026‑04‑01, соцсети удалены, токен $GSD публично связан с rug‑pull; npm переименован в `get-shit-done-redux`. https://github.com/open-gsd/gsd-core/discussions/109
- Ключевая идея подтверждена: план верифицируется «на вместимость в свежее окно», каждый executor стартует с чистым 200k контекстом, план — файл. Цикл discuss → plan → execute → verify → ship. https://github.com/open-gsd/gsd-core
- Практика:
  - Atomic Object (Sydney Cole, 2026‑06‑09): первый план фазы почти идеален, **к Plan 03–04 качество падает** (миграция тихо удалила индекс); вывод — фазы короче, дольше discuss. https://spin.atomicobject.com/get-shit-done-gsd/
  - Vitor Norton (2026‑06‑15): автокоммиты на каждую задачу и «красноречивый дрейф» от требований — из 70 фаз переделал 50; ушёл на GitHub Spec Kit. https://dev.to/vtnorton/i-tried-to-fork-gsd-or-its-for-vibe-coders-not-real-devs-kkl
  - HN‑тред: работает на рефакторингах и «мелких надоедливых задачах в отдельном worktree», плохо для архитектурных решений. https://news.ycombinator.com/item?id=46746231
- Context rot — исследования есть: Chroma «Context Rot» (2025‑07‑14, 18 моделей, NIAH‑расширение, LongMemEval, repeated words) https://www.trychroma.com/research/context-rot ; NoLiMa (ICML 2025): при 32k **11 из 13 моделей ниже 50% от короткого контекста**, GPT‑4o 99.3→69.7 https://arxiv.org/abs/2502.05167 ; свежее: arXiv 2605.12366 «Classifier Context Rot». Cognition в 2026 ссылается на context rot как «well‑documented».

## 4. Cognition
- Оригинал (Walden Yan, 2025‑06‑12): share full traces, actions carry implicit decisions, single‑threaded linear agent, компрессия контекста. Резюме верно. https://cognition.com/blog/dont-build-multi-agents
- Эволюция: **«Multi‑Agents: What's Actually Working» (2026‑04‑22)** — в проде: clean‑context reviewer (~2 бага на PR, 58% серьёзных), «smart friend» (вызов сильной модели), manager‑child (map‑reduce‑and‑manage через MCP). Формула: «writes stay single‑threaded, additional agents contribute intelligence rather than actions». Параллельные писатели по‑прежнему нет. https://cognition.com/blog/multi-agents-working
- Продукт: parallel agents (дек 2025), «Devin manages Devins» (2026‑03‑19, изолированные VM), Windsurf → Devin Desktop (2026‑06‑02) с subagents. То есть позиция не отменена, а сужена до «один писатель + помощники».
- Статистика 25 264 PR: **arXiv 2607.14037** «Early Adoption of Agentic Coding Tools by GitHub Projects» (Raida, Hou, июль 2026), 2 361 репозиториев. Точная цитата: «1 Reviewer + 1 Committer (Same Person) … 19,488 PRs (78.9%)»; single‑human в сумме 88.7%; ≥2 человек — 11.3%. Формулировка «в 79% один человек и ревьюит, и правит» корректна (округление 78.9). https://arxiv.org/abs/2607.14037

## 5. arc42 / ADR
- Подтверждено: §8 Crosscutting Concepts, §9 Architecture Decisions. https://arc42.org/overview
- «Не покрывать всё»: Starke, «Everything is optional — there is no need to fill in every section… like the compartments of a cabinet» https://dev.to/arc42/brief-introduction-to-arc42-1c0l ; docs §5: «prefer relevance over completeness… leave out normal, simple, boring or standardized parts».
- arc42 + агенты: официальной адаптации не нашёл. Есть: MSiccDev/arc42-toolkit (skills для Claude Code/Copilot/Cursor), MCP‑сервер arc42, статья ceaksan «Living Architecture» (arc42 для людей vs architecture.md для контекста модели). Важно: ETH Zurich (arXiv 2602.11988, 138 задач, 4 модели): **LLM‑сгенерированные AGENTS.md снижают успех на ~3% и +20% стоимости; человеческие +4% и до +19% шагов** — аргумент против объёмных контекст‑файлов. https://www.infoq.com/news/2026/03/agents-context-file-value-review/
- MADR: **4.0.0 (2024‑09‑17) — текущая**, новее нет; репо активно (push авг 2026). https://adr.github.io/madr/
- log4brains: v1.1.0 — 2024‑12‑17, с тех пор ни одного push. **Замер.**
- adr-tools (npryce): 3.0.0 — 2018, push апр 2024. **Заморожен**, но работает.

## 6. Living Documentation
Подтверждено (Martraire, Addison‑Wesley 2019): stable vs volatile knowledge, evergreen documents с нулевым сопровождением, knowledge augmentation (аннотации — «why»), генерация документов/диаграмм из кода, living curation. https://www.oreilly.com/library/view/living-documentation-continuous/9780134689418/

## 7. Context Store
InfoQ, **«Comprehension at AI Speed: Building a Context Store for Evolutionary Architecture»**, 2026‑07‑14, авторы Berhe, Bragner, Maran, Jayaraman (ревью Mezzalira). **Концепт, не продукт**: версионированное, привязанное к репозиторию хранилище из четырёх слоёв (Structure, Lineage, Behavior, Conformance), собранное из spec‑anchored SDD + TDD + fitness functions (ArchUnit, dependency‑cruiser, CI‑гейты). Первые шаги: спек‑файлы на фичу, test‑first, три блокирующие fitness‑функции. https://www.infoq.com/articles/ai-speed-context-store-architecture/

## 8. VSDD и EARS
- VSDD — **два источника, brief их смешал**:
  - Gist dollspace-gay (обновлён 2026‑08‑28): 6 фаз, роли Architect (человек) / Builder (Claude) / Adversary (другая модель) / **Tracker** (Chainlink), «Zero‑Slop», Kani/CBMC/Dafny/TLA+/фаззинг. https://gist.github.com/dollspace-gay/d8d3bc3ecf4188df049d7a4726bb2a00
  - adamdaw/VSDD: «7 phases, 5 gates», Architect/Builder/Adversary, плагин v0.1.0, **2★**. https://github.com/adamdaw/VSDD
  - «Accountant» не нашёл ни там, ни там. Практических отзывов нет; комментарии к gist — «водопад в upfront‑спеке». Ниша, не практика.
- EARS/Kiro: McAree (дек 2025) — специи снижают галлюцинации, но полный цикл для мелких правок избыточен, поддержка спек — дисциплина. https://petermcaree.com/posts/kiro-agentic-ide-hype-hope-and-hard-truths/ ; Reddit‑консенсус (через codemyspec, вендор): любят для сложных фич, бросают из‑за overhead на простых. EARS — синтаксис, не исполняемый критерий. HN‑тред по EARS пустой (1 коммент).

## 9. Что brief мог упустить
- «Skeleton first» в агентной разработке живёт под именем **tracer bullet / walking skeleton**: TracerKit (helderberto), spec-kit-tracer (расширение Spec Kit), skills «slicing-into-tracer-bullets», aihero «Tracer Bullets: Keeping AI Slop Under Control»; Spec Growth Engine (arXiv) — «vertical‑slice growth, hardest first». Термина «cross‑cutting concerns first» в этой среде не нашёл.
- Hooks «стоп перед схемой»: Claude Code PreToolUse с `permissionDecision: ask|deny` (deny > defer > ask > allow); есть готовые примеры блокировки миграций/.env через `Edit|Write` matcher. https://code.claude.com/docs/en/hooks
- Docs drift в CI: **fiberplane/drift** (v0.10.1, июнь 2026, 144★) — якорит markdown к символам через tree‑sitter, падает при изменении AST https://fiberplane.com/blog/drift-documentation-linter/ ; lychee (Rust, относительные пути через `--root-dir`) для битых ссылок; GitLab `docs-lint links` + rubocop/eslint‑docs как образец «ссылки из кода в доки»; Swimm — коммерческий auto‑sync сниппетов с CI‑проверкой. Готового «тест падает, если док ссылается на несуществующий путь» кроме lychee/GitLab‑скриптов не нашёл — обычно пишут свой.

**Не проверено / не нашёл:** точная версия cargo-modules на crates.io; import-linter версия свежее 2.7; кто такой `gsd-build` до архивации (переезд репо с glittercowboy — по редиректу GitHub); «Accountant» в VSDD; устойчивость термина «AI architecture drift» за пределами Thoughtworks/вендоров.
