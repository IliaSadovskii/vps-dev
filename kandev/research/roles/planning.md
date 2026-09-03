# Planning

## Наш замысел

Первый шаг маршрута Standard и середина маршрута Deep. Создаёт реализационный
план: границы, риски, этапы, проверки. Шаг включает `enable_plan_mode` на
входе и `disable_plan_mode` на выходе. Пишет план в нативный Kandev Plan через
MCP — и это единственная роль с правом записи в него, потому что план у
задачи один, а `create_task_plan_kandev`/`update_task_plan_kandev` заменяют
его содержимое целиком (`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md:167-176`).

## Найденные аналоги

| Инструмент | Как называется роль | Где лежит |
|---|---|---|
| Kandev (встроенный) | Plan mode — общий режим для любого шага с `enable_plan_mode` | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/plan-mode.md` |
| Kandev (встроенный) | `[PLANNING PHASE]` — префикс, добавляемый к промпту шага в plan mode | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/default-plan-prefix.md` |
| Kandev (продуктовые шаблоны) | Шаг `Plan` в шаблоне «Plan & Build», шаг `Planning` в шаблоне «Architecture», шаг `Spec` в шаблоне «Feature Dev» | `/tmp/kandev-v0.93.0/docs/public/workflow-tips.md:61-91` |
| Claude Code plugin `feature-dev` | Субагент `code-architect` — архитектурный blueprint | `/home/dev/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/agents/code-architect.md` |
| Claude Code plugin `feature-dev` | Команда `/feature-dev`, Phase 4 «Architecture Design» | `/home/dev/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/commands/feature-dev.md:73-83` |
| kit-lite | Роль `plan` (поглотила `spec`) | `/home/dev/projects/kit-lite/roles/plan.md`, `/home/dev/projects/kit-lite/roles/spec.md` |
| GitHub spec-kit | Команда `/plan` (или `/speckit.plan`) + `plan-template.md` | https://github.com/github/spec-kit/blob/main/templates/commands/plan.md , https://github.com/github/spec-kit/blob/main/templates/plan-template.md |
| obra/superpowers | Skill `writing-plans` | https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md |
| BMAD-METHOD | Agent «Architect» (Winston), принимает PRD от PM-агента | https://github.com/bmad-code-org/BMAD-METHOD (страница агентов), https://docs.bmad-method.org/reference/agents/ |
| Cline | Plan Mode (переключатель режимов Plan/Act) | https://docs.cline.bot/features/plan-and-act |

Не найдено прямого аналога в: CrewAI/AutoGen/AG2/MetaGPT/ChatDev/OpenHands/Aider —
поиск по ним не проводился отдельно из-за лимита запросов; экономия направлена
на инструменты, ближе всего к «единый документ плана перед кодом» (spec-kit,
superpowers, BMAD, Cline), которые и дали содержательный материал.

## Что кладут всегда

**Конкретные пути и имена вместо общих советов** — 4 из 4 источников, где это
вообще обсуждается:
- Kandev: «Your plan must reference actual file paths, function names, types,
  and patterns from this project — not generic advice.»
  (`default-plan-prefix.md:10`), и повтор в `plan-mode.md:11`: «Make your
  additions specific to this project — reference actual file paths, function
  names, types, and architectural patterns. Avoid adding generic or boilerplate
  content.»
- code-architect: «Be specific and actionable — provide file paths, function
  names, and concrete steps.» (`code-architect.md:32`)
- kit-lite: «Пути точные.» (`plan.md:51`)
- superpowers: явный запрет на плейсхолдеры и требование точных путей вида
  `exact/path/to/file.py` (SKILL.md, см. цитаты ниже).

**Запрет писать код на этом шаге** — 3 из источников, где шаг вообще
отделён от реализации:
- Kandev: «You are in planning mode. Do not implement anything — focus on the
  plan.» (`plan-mode.md:2`)
- Cline: план-режим не может «изменять файлы или выполнять команды» —
  https://docs.cline.bot/features/plan-and-act
- kit-lite: `writes_never: [код, тесты]` (`plan.md:29`)

**Чтение уже существующего плана перед записью / достраивание, а не
затирание** — тот же набор, что и «единый источник правды»:
- Kandev: «Read the current plan using the get_task_plan_kandev MCP tool.» и
  «Build on what already exists. Only replace or discard the user content if
  it is clearly irrelevant or incorrect.» (`plan-mode.md:8-9`); дублируется в
  `default-plan-prefix.md:7-8`: «First check if a plan already exists...If the
  user has already started writing the plan, build on their content — do not
  replace it.»
- kit-lite: правки человека к плану («да, но…») применяет `lead`, «без
  второго касания», а не Planning заново (`gate.md:26`), то есть человеческий
  слой поверх плана защищён процессом, а не только промптом.

**Явная структура вывода: понимание задачи → файлы → шаги → риски** —
встречается везде, где формат вообще специфицирован:
- Kandev: пронумерованный список из 4 пунктов, оканчивающийся рисками
  (`default-plan-prefix.md:12-16`).
- code-architect: 7 обязательных секций, включая «Critical Details» с рисками
  (`code-architect.md:24-32`).
- kit-lite: план из двух секций, риски и допущения — отдельным пунктом
  (`plan.md:66-67`).
- spec-kit: артефакты Phase 0/1 включают `research.md` (разрешение
  неясностей) и `quickstart.md` (сценарии валидации), то есть тоже
  «понимание → структура → проверка».

**STOP после сохранения, ожидание человека** — см. отдельный раздел
«Условие завершения» ниже, но паттерн настолько общий, что дублирую здесь:
Kandev дважды подряд формулирует его явно (`plan-mode.md:13`,
`default-plan-prefix.md:21`), продуктовые шаблоны Kandev не ставят
автоматический переход после Plan/Planning (`workflow-tips.md:65-70, 76-78`),
а kit-lite выносит одобрение в отдельный шаг `gate`.

## Что кладут иногда

**Уточняющие вопросы до написания плана** — 2 прямых источника:
- Kandev: «Before creating the plan, ask the user clarifying questions if
  anything is unclear. Use the ask_user_question_kandev MCP tool to get
  answers before proceeding.» (`default-plan-prefix.md:4-5`)
- feature-dev команда: отдельная Phase 3 «Clarifying Questions», с пометкой
  «CRITICAL... DO NOT SKIP» (`feature-dev.md:57-69`)

kit-lite делает по-другому — открытые вопросы не блокируют шаг `plan`
отдельным касанием, а едут вместе с планом на `gate`: «asks_human: free —
открытые вопросы едут на ворота, не отдельным касанием» (`plan.md:30`). Это
разные модели: Kandev/feature-dev блокируют сам шаг планирования до ответа,
kit-lite откладывает решение до утверждающего гейта.

**Mermaid-диаграммы** — только у Kandev: «When including diagrams
(architecture, sequence, flowcharts), always use mermaid syntax in code
blocks.» (`default-plan-prefix.md:18`). Ни в одном другом источнике формат
диаграмм не специфицирован отдельной строкой.

**Обязательные сигнатуры новых публичных интерфейсов** — 3 источника:
- kit-lite делает это «новым обязательным требованием»: «Интерфейсы: каждая
  новая публичная функция, класс, эндпоинт, таблица, команда — сигнатура,
  типы, какие ошибки бросает.» (`plan.md:15-17, 47`)
- superpowers: блок Interfaces с `Consumes`/`Produces`, «exact function names,
  parameter and return types».
- spec-kit: отдельная папка `/contracts/` в артефактах плана.

Kandev-промпты сигнатуры отдельно не требуют — только «function names, types»
в общем списке (`default-plan-prefix.md:10`), без выделенной секции.

**Несколько вариантов решения на выбор пользователю** — встречается только у
feature-dev команды: Phase 4 явно запускает 2-3 параллельных
`code-architect`-агента с разными приоритетами (минимальные изменения / чистая
архитектура / баланс) и просит пользователя выбрать (`feature-dev.md:73-81`).
Сам `code-architect` как агент, наоборот, требует обратного: «Make confident
architectural choices rather than presenting multiple options.»
(`code-architect.md:34`) — расхождение внутри одного и того же плагина между
оркестрирующей командой и самим агентом.

**Атомарная нарезка на шаги по 2-5 минут** — только superpowers: «Each step
is one action (2-5 minutes)», примеры вроде «Write the failing test» → «Run
it» → «Implement minimal code» → «Commit». kit-lite явно рассматривала и
отвергла эту идею (см. «Расхождения»).

## Чего сознательно не кладут

- **Реализацию/код в плане.** Kandev (`plan-mode.md:2`), Cline (план-режим не
  меняет файлы), kit-lite (`writes_never: [код, тесты]`, `plan.md:29`).
- **Тесты в плане.** kit-lite прямо запрещает писать тесты на этом шаге
  (`plan.md:29`); в Kandev-маршрутах тесты — обязанность `Test Authoring`
  дальше по цепочке (`DEVELOPMENT-ROUTES.md:85-87`).
- **Файлы помимо самого плана.** Kandev: «Do not create any other files
  during this phase — only use the MCP tools to save the plan.»
  (`default-plan-prefix.md:21-22`). Это прямое ограничение, специфичное для
  Kandev — ни у одного другого источника такого запрета нет (у spec-kit и
  superpowers план как раз обычно и есть файл на диске).
- **Плейсхолдеры и обобщения.** superpowers перечисляет запрещённые паттерны
  дословно: «TBD», «TODO», «implement later», «Add appropriate error
  handling», «Similar to Task N» (вместо повторения кода). kit-lite: «Без
  заглушек: никаких «TBD», «добавить обработку ошибок», «как в шаге N».»
  (`plan.md:50-51`) — почти дословное совпадение с superpowers, несмотря на
  независимое происхождение.
- **Затирание правок пользователя без разбора.** Kandev формулирует это как
  прямой запрет-с-исключением: «Only replace or discard the user content if it
  is clearly irrelevant or incorrect.» (`plan-mode.md:9`)

## Формат вывода

- **Kandev**: одно текстовое поле `content` (+ опционально `title`), которое
  целиком заменяется при `update_task_plan_kandev`. Рекомендуемая внутренняя
  структура из 4 пунктов: «1. Understanding of the requirements; 2. Specific
  files...; 3. Step-by-step implementation approach...; 4. Potential risks or
  considerations» (`default-plan-prefix.md:12-16`), плюс код-блоки mermaid для
  диаграмм.
- **kit-lite**: один файл `plan.md` из двух секций — §1 для человека (жёстко
  ≤40 строк, цель/что сделаем/что не делаем/решённые развилки/допущения) и §2
  для исполнителя (файлы create/изменить, сигнатуры интерфейсов, порядок
  шагов, «не трогать») (`plan.md:58-78`).
- **code-architect**: семь фиксированных секций — Patterns & Conventions
  Found, Architecture Decision, Component Design, Implementation Map, Data
  Flow, Build Sequence (чек-лист по фазам), Critical Details
  (`code-architect.md:24-32`).
- **spec-kit**: не один файл, а набор артефактов — `plan.md` плюс
  `research.md`, `data-model.md`, `/contracts/`, `quickstart.md` — то есть
  план физически распределён по нескольким документам одной фичи.
- **superpowers**: один markdown-файл по пути
  `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`, с заголовком Goal /
  Architecture / Tech Stack / Spec и списком коротких (2-5 минут) шагов с
  Consumes/Produces.

## Условие завершения

- **Kandev**: явный, дважды продублированный STOP. `plan-mode.md:13`:
  «After saving, STOP and wait for the user to review.» и
  `default-plan-prefix.md:21`: «After saving, STOP and wait for user review.
  The user may edit the plan before approving it.» Ни один из двух файлов не
  упоминает `step_complete_kandev` напрямую — общий контракт вызова
  прописан отдельно, в `kandev-context.md`/`office-context.md`
  (`step_complete_kandev: Signal that every requirement for the current
  workflow step is satisfied...`). Продуктовые шаблоны Kandev подтверждают
  этот же паттерн снаружи: у `Plan & Build` и `Architecture` переход после
  шага планирования — ручной, шаблон «does not define automatic transitions
  between these steps» (`workflow-tips.md:68-70, 76-78`).
- **spec-kit**: завершение формализовано как чек-лист из трёх пунктов —
  workflow выполнен и артефакты созданы, extension-хуки (`after_plan`)
  отработаны, пользователю отдан отчёт с веткой и путями к артефактам; плюс
  проверка «gates» (constitution) с ошибкой при нарушении до сохранения.
- **superpowers**: план считается завершённым, когда сохранён по фиксированному
  пути и агент предлагает пользователю выбрать способ исполнения
  (Subagent-Driven или Inline Execution) — то есть условие включает не только
  сохранение, но и следующий шаг диалога.
- **Cline**: явного автоматического условия нет вообще. Переход в Act Mode —
  ручное решение пользователя; документация вместо условия завершения даёт
  эвристику «возвращайтесь в Plan Mode при неожиданной сложности».

## Расхождения и спорное

- **Один решительный план vs несколько вариантов на выбор.** `code-architect`
  как агент требует «Make confident architectural choices rather than
  presenting multiple options» (`code-architect.md:34`), а команда
  `/feature-dev`, которая этот агент использует, наоборот, штатно запускает
  2-3 параллельных `code-architect` с разными акцентами и отдаёт выбор
  пользователю (`feature-dev.md:73-81`). BMAD, spec-kit и Kandev-промпты
  такого ветвления не делают — они производят один документ. Для наших
  маршрутов это прямо решается архитектурой: выбор между решениями уже сделан
  раньше, в `Decision Mapping`/`Solution Synthesis` (Deep) или отсутствует
  вовсе (Standard) — `DEVELOPMENT-ROUTES.md:30-34`. Значит, `Planning` не
  должен переоткрывать развилки в духе `feature-dev`, это чужая обязанность.
- **Гранулярность шагов.** superpowers настаивает на шагах по 2-5 минут с
  конкретным кодом внутри плана; kit-lite сознательно отверг эту идею именно
  потому, что заимствовал остальные принципы writing-plans: «Не взято: «task
  = 2–5 минут с готовым кодом в плане» — это реализация в плане; у нас код
  пишет `build` по сигнатурам, а тесты — `test-author`» (`plan.md:83-85`).
  Kandev-промпты вообще не специфицируют размер шага («Step-by-step
  implementation approach», без единицы измерения) — то есть вопрос у нас
  тоже открыт и требует отдельного решения, а не копирования одного из
  источников.
- **План как один MCP-документ vs план как файловый бандл.** Kandev прямо
  запрещает создавать что-либо кроме самого плана через MCP
  (`default-plan-prefix.md:21-22`), тогда как spec-kit по умолчанию
  раскладывает план на 4-5 файлов (`plan.md`, `research.md`, `data-model.md`,
  `contracts/`, `quickstart.md`). Это несовместимые модели хранения, а не
  два способа сказать одно и то же — совмещать их напрямую нельзя.
- **Блокировать шаг вопросами или откладывать их до гейта.** Kandev и
  feature-dev просят агент остановиться и спросить пользователя ещё до
  написания плана; kit-lite сознательно не тратит на это отдельное касание и
  копит открытые вопросы прямо в плане, доводя их до `gate`
  (`spec.md`, `plan.md:30`). У нас это имеет технические последствия: если
  `Planning` вызовет `ask_user_question_kandev`, задача, по документированной
  семантике Kandev, зависнет в текущей колонке в ожидании ответа («A pending
  clarification always blocks completion», `workflow-tips.md:166`) — то есть
  вопрос не «эстетический», а меняет, где физически стоит карточка, пока ждёт
  человека.

## Выводы для нас

**Взять:**
- Требование конкретных путей/сигнатур вместо общих советов — не подтверждаемая
  ни одним контрпримером норма (Kandev x2, code-architect, kit-lite,
  superpowers).
- Read-before-write и «не затирай правки человека без разбора» — это не
  просто хорошая практика, а прямое следствие того, что `update_task_plan_kandev`
  заменяет план целиком: без явного шага «сначала `get_task_plan_kandev`,
  затем построй поверх» вторая запись Planning уничтожит первую собственную
  же правку или правку человека. Единственный источник, формулирующий это
  операционно — сам `plan-mode.md:8-9`; его стоит взять почти дословно.
- STOP после сохранения плана и ожидание ревью человеком — согласуется и с
  Kandev-промптами, и с архитектурой наших маршрутов (`Plan Review` и
  `Plan Approval` — отдельные последующие шаги, `DEVELOPMENT-ROUTES.md:20,83-84`).
  Формально в наших маршрутах «STOP» — это вызов `step_complete_kandev`, а не
  просто окончание ответа (`auto_advance_requires_signal: true`,
  `DEVELOPMENT-ROUTES.md:102-103`), это нужно прописать явно, потому что сами
  Kandev built-in промпты этот вызов не упоминают вовсе.
- Структуру «граница/риски/этапы/проверки» из брифа стоит собирать из трёх
  разных источников сразу, ни один в одиночку не покрывает всё: секция
  «риски» — из `default-plan-prefix.md`/code-architect; явные «что не делаем»
  (границы) — из kit-lite, ни один Kandev-промпт слова «границы»/«scope» не
  использует; связка «шаг → команда, которая его проверяет» — тоже только у
  kit-lite (`доказано: команда — что она поймает`, `plan.md:65`) и важна нам
  особенно, потому что дальше по маршруту `Test Authoring` и `Verification`
  должны опираться на план, а не гадать.
- Сигнатуры новых публичных интерфейсов — брать из kit-lite/superpowers/
  spec-kit; в built-in Kandev-промптах это требование слабее («function
  names, types» одной строкой), а нашим `Test Authoring` (свежий контекст,
  читает план через MCP, `DEVELOPMENT-ROUTES.md:169`) сигнатуры нужны не
  расплывчато, а операционально, иначе первый прогон тестов будет красным не
  по делу — тот же аргумент, что и у kit-lite (`plan.md:17`).
- Mermaid для диаграмм — дёшево и специфично для Kandev, разумно взять как
  есть.

**Не брать:**
- Атомарную нарезку по 2-5 минут с готовым кодом внутри плана (superpowers) —
  это фактически перенос части работы `Implementation`/`build` в план;
  kit-lite уже проверил эту идею и отверг её по той же причине, что актуальна
  и для нас: у нас план и реализацию физически разносят разные роли и разные
  turn'ы, писать код заранее — не сокращать работу, а дублировать решения.
- Многофайловый бандл вывода (spec-kit: `research.md` + `data-model.md` +
  `contracts/` + `quickstart.md`) — прямо противоречит ограничению Kandev
  «only use the MCP tools to save the plan» и списку артефактов в
  `DEVELOPMENT-ROUTES.md:130-145`, где для `Planning` вообще нет отдельного
  файла (следующий по списку — `plan-review.md`, который пишет уже `Plan
  Review`). Единственный источник истины по плану должен остаться один.
- Параллельный запуск нескольких вариантов архитектуры на выбор пользователю
  (`feature-dev.md` Phase 4) — конфликтует с уже принятой у нас лестничной
  моделью маршрутов, где развилки решаются заранее (`Decision Mapping`,
  `Solution Synthesis`) или отсутствуют вовсе; повторное открытие вариантов
  внутри `Planning` дублировало бы уже сделанную работу и ломало бы
  однопроходную природу Standard-маршрута.

**Чего в источниках нет, а нам нужно из-за особенностей Kandev:**
- Ни один источник не рассчитан на сценарий, где план читает *другой* агент в
  *другом* turn'е с уже сброшенным контекстом (у нас — `Plan Review`,
  `Test Authoring`, `Code Review`, все свежие, `DEVELOPMENT-ROUTES.md:67-73,
  169`). Cline/superpowers/spec-kit пишут план в рамках одной непрерывной
  сессии с тем же агентом, что потом реализует; ближе всего Kandev
  `plan-mode.md`, но и он написан для одной длинной plan-mode-беседы (шаблон
  `Plan & Build`), а не для контракта между независимыми ролями. Нужно
  отдельно прописать, что план должен быть самодостаточным текстом без
  отсылок к «как мы это обсуждали выше» — этого нет ни в одном разобранном
  источнике буквально, это следствие только нашей artifact-протокольной
  архитектуры.
- Ни один источник не обсуждает, что `enable_plan_mode`/`disable_plan_mode` —
  это события шага workflow (`on_enter`/`on_turn_complete`/`on_exit` в
  редакторе Kandev, `workflow-tips.md:131, 164-167`), а не инструкция внутри
  промпта роли. Это значит, что промпту `Planning` не нужно самому «включать
  и выключать» plan mode текстом — это забота конфигурации шага, и в тексте
  роли эту фразу из задания не стоит превращать в императив агенту.
- Семантика "план — единственная точка записи" у нас жёстче, чем в любом
  источнике: ни у superpowers (git-файл, обычные diff/append), ни у spec-kit
  (несколько файлов, тоже через git) нет ограничения «update заменяет
  содержимое целиком и второй писатель гарантированно затирает первого». Это
  чисто Kandev-специфичный риск, и единственный источник, который вообще
  адресует именно эту операционную проблему — `plan-mode.md:8-9` (build on
  existing, replace only if irrelevant); его инструкцию нужно усилить, а не
  просто скопировать, потому что у Kandev, в отличие от продуктовых шаблонов
  с непрерывным plan-mode-диалогом, `Planning` может быть единственным
  вызовом за всю жизнь плана (в Standard он ни разу больше не заходит в
  колонку `Planning` без ручного возврата).

**Не проверено (честно):** аналоги в CrewAI, AutoGen/AG2, MetaGPT, ChatDev,
OpenHands, Aider, roo-code/SPARC — веб-поиск по ним не делался, лимит в 6-8
запросов был исчерпан на инструментах, давших более прямой материал
(spec-kit, superpowers, BMAD, Cline). Веб-поиск не падал технически, просто
не расходовался на весь список из брифа.
