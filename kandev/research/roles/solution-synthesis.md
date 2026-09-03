# Solution Synthesis

> Состояние: локальный корпус разобран полностью. Интернет — 8 запросов
> (WebSearch) + 2 прямых WebFetch по первичному тексту; ничего не упало,
> бюджет не превышен, но глубина по некоторым инструментам (BMAD, MetaGPT,
> SPARC) ограничена вторичными обзорами — это отмечено отдельно там, где
> цитаты не первичные.

## Наш замысел

Третий шаг маршрута Deep, после `Decision Mapping` и `Targeted Research`.
Сводит локальный контекст проекта и принесённые из интернета данные в ОДИН
выбранный вариант решения — не в список альтернатив. Обязана сделать выбор и
обосновать его, а не переложить решение на человека. Следом идёт человеческий
гейт `Solution Approval`, где человек соглашается или возвращает назад.

## Найденные аналоги

| Инструмент | Роль / артефакт | Где |
|---|---|---|
| Anthropic `feature-dev` | агент `code-architect` | `plugins/feature-dev/agents/code-architect.md` |
| Anthropic `feature-dev` | Phase 4 «Architecture Design» команды `feature-dev` (оркестратор вокруг `code-architect`) | `plugins/feature-dev/commands/feature-dev.md:73-82` |
| Anthropic `code-modernization` | Phase C «Architecture (single agent, then critique)» + агент `architecture-critic` | `plugins/code-modernization/commands/modernize-reimagine.md:62-78`, `plugins/code-modernization/agents/architecture-critic.md` |
| Kandev (сам продукт) | встроенный шаблон цепочки «Architecture»: `Ideas → Planning → Review → Approved` | `/tmp/kandev-v0.93.0/docs/public/workflow-tips.md:73-80` |
| Kandev (сам продукт) | режим Plan Mode / default-plan-prefix (одиночный тред, не колонки) | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/plan-mode.md`, `default-plan-prefix.md` |
| GitHub `spec-kit` | Phase 0 `research.md` внутри команды `/plan` | `templates/commands/plan.md` (raw.githubusercontent.com/github/spec-kit/main), первичный текст через WebFetch |
| MADR / ADR-практика | «Considered Options» + «Decision Outcome» | adr.github.io/madr (через WebSearch-агрегатор, не прямой WebFetch) |
| KitLight (наш) | `design.md` — но для UI, и с **обратной** инструкцией | `/home/dev/projects/kit-lite/roles/design.md` |
| KitLight (наш) | `forks.md` / бывшая `options.md` — корзина «нужен выбор человека» | `/home/dev/projects/kit-lite/roles/forks.md`, `options.md` |
| BMAD-METHOD | агент Architect (PRD → Architecture doc) | вторично, через WebSearch-обзоры github.com/bmad-code-org — точный текст промпта не прочитан |
| MetaGPT | роль `Architect`, action `WriteDesign` | вторично, через WebSearch-обзоры (IBM, starlog.is) — Python-класс, не prompt-текст |
| Roo-Code / SPARC | режим Architect | вторично, через WebSearch-обзоры gist'ов — конкретного промпта не прочитано |
| Aider | Architect/Editor mode | прочитано, но это другая ось (разделение «придумать решение» / «сгенерировать diff», не «один вариант против списка») — не аналог по существу |

Три источника прочитаны первично и дают дословные цитаты (Anthropic
feature-dev, Anthropic code-modernization, Kandev сам). Один — первичный текст
через WebFetch (spec-kit). Один — устойчивый агрегированный паттерн отрасли,
не привязан к одному инструменту (MADR). Остальные — вторичные упоминания,
без доступа к точному тексту промпта; их беру как слабый сигнал «направление
существует», не как «так сделано».

## Что кладут всегда

### Один финальный документ, даже когда путь к нему был вариативным — 3 из 3 первичных источников

`code-architect` собирает всё в один response: «Deliver a decisive, complete
architecture blueprint» (`plugins/feature-dev/agents/code-architect.md:24`).
`architecture-critic` не производит второй вариант архитектуры, а
редактирует единственный: «Incorporate the critique. Write the result to
`analysis/$1/REIMAGINED_ARCHITECTURE.md`» (одна выходная запись, не список)
(`modernize-reimagine.md:72-73`). Kandev-шаблон «Architecture» тоже ведёт к
одному state: «the agent starts in plan mode and is instructed to produce
design, not code» — не «designs», единственное число
(`workflow-tips.md:74`).

### Обоснование выбора обязательно, причём именно у выбранного варианта, не у всех — 3 из 3

`code-architect`: «**Architecture Decision**: Your chosen approach with
rationale and trade-offs» (`code-architect.md:27`) — trade-offs здесь
принадлежат уже выбранному подходу, это не сравнительная таблица вариантов.
spec-kit фиксирует то же самое построчно на каждый пункт: «Decision: [what
was chosen] / Rationale: [why chosen]» (`templates/commands/plan.md`,
Phase 0, дословно через WebFetch). Kandev `default-plan-prefix.md` требует
«Step-by-step implementation approach grounded in existing code patterns» —
один approach, не веер (`default-plan-prefix.md`, п.3).

### Опора на прочитанный код/контекст проекта, а не общие советы — 3 из 3

`code-architect.md:14`: «Extract existing patterns, conventions, and
architectural decisions... Find similar features to understand established
approaches» — до всякого дизайна. `default-plan-prefix.md`: «Your plan must
reference actual file paths, function names, types, and patterns from this
project — not generic advice». Это тот же принцип, что уже задокументирован
для `Discovery` («cite everything»), но здесь он применяется к решению, а не
к разведке.

## Что кладут иногда

- **Диаграммы (mermaid) как обязательная часть выходного документа.**
  `modernize-reimagine.md:65` требует Mermaid C4 Container diagram в Phase C;
  Kandev `default-plan-prefix.md`: «When including diagrams (architecture,
  sequence, flowcharts), always use mermaid syntax in code blocks». У
  `code-architect` диаграмм нет вовсе — только текстовые Component
  Design/Data Flow. 2 из 3 первичных источников.

- **Автоматический критик между синтезом и человеком.**
  `modernize-reimagine` вставляет `architecture-critic` между Phase C и
  человеческим Phase D checkpoint (`:70-78`) — синтез получает шанс
  исправиться до того, как его увидит человек. Ни у `code-architect`
  (используется как одноразовый subagent, критики нет в его контракте), ни у
  Kandev-шаблона «Architecture» (там роль критика играет сам человек на шаге
  `Review`, `workflow-tips.md:76`) такого отдельного автоматического шага
  нет. 1 из 3.

- **«Alternatives considered» как формальная запись, а не как приглашение
  выбирать.** spec-kit держит третью строку `Alternatives considered:
  [what else evaluated]` рядом с Decision/Rationale — но это архивная
  запись для трассируемости, не меню для человека. MADR доводит тот же
  импульс до отдельной секции с pros/cons на каждый вариант. У
  `code-architect` и у `modernize-reimagine` эквивалента вообще нет: отвергнутые
  варианты нигде не фиксируются.

## Чего сознательно не кладут

- **`code-architect` прямым текстом запрещает меню вариантов на выходе:**
  «Make confident architectural choices rather than presenting multiple
  options» (`code-architect.md:9`) и «Make decisive choices - pick one
  approach and commit» (`:17`) и ещё раз в конце: «Make confident
  architectural choices rather than presenting multiple options» (`:34`,
  повтор той же формулировки — судя по всему, намеренное усиление).
- **`architecture-critic` не пишет и не переписывает архитектуру сам** —
  только находит проблемы: «You are **read-only**: never create or modify
  files... Your findings are returned as output for the orchestrating
  session to write» (`architecture-critic.md:59-63`). Роль критика и роль
  автора синтеза разведены жёстко.
- **Kandev `plan-mode.md` запрещает реализацию внутри роли планирования:**
  «Do not implement anything — focus on the plan» — тот же принцип границы,
  что нужен и `Solution Synthesis`: решение, не код.
- **MADR, наоборот, запрещает молча выбрасывать отвергнутые варианты** — по
  формату «Considered Options» обязателен даже когда решение очевидно;
  это прямая противоположность запрету `code-architect`, разобрана ниже в
  «Расхождения».

## Формат вывода

- **`code-architect`** (`code-architect.md:24-32`): Patterns & Conventions
  Found (с `file:line`) → Architecture Decision (chosen approach + rationale
  + trade-offs) → Component Design (path, responsibilities, dependencies,
  interfaces на каждый компонент) → Implementation Map (какие файлы
  создать/изменить) → Data Flow → Build Sequence (чеклист по фазам) →
  Critical Details (ошибки, состояние, тесты, производительность,
  безопасность). Без ограничения по длине — «comprehensive» декларируется
  прямо в description агента.
- **spec-kit `research.md`**: построчно на каждый нерешённый пункт —
  Decision / Rationale / Alternatives considered, затем всё консолидируется
  в один файл перед переходом к `plan.md`.
- **MADR**: Context, Decision Drivers, Considered Options (список), Pros/Cons
  каждого варианта отдельной секцией, Decision Outcome в форме «{name of
  option} because {justification}», Consequences.
- **`modernize-reimagine`**: единый файл `REIMAGINED_ARCHITECTURE.md` —
  C4-диаграмма, service boundaries с обоснованием, технологический выбор с
  «one-line justification each», data migration approach — плюс инкорпорированная
  критика `architecture-critic`.
- **KitLight `design.md`** для контраста: жёсткий потолок «60 строк» и
  табличный формат по экранам — но это другая роль (UI), не архитектурная.

Единой конвенции по длине нет ни у одного архитектурного (не UI) источника —
в отличие от, например, `kit-lite/plan.md`, который явно ограничивает секцию
для человека 40 строками.

## Условие завершения

- **`modernize-reimagine.md:75-78`**: «Present the architecture and **stop —
  scaffold nothing until the user explicitly approves**» — синтез
  заканчивается написанием файла и остановкой перед человеком; это
  структурно то же самое место, что у нас занимает переход
  `Solution Synthesis → Solution Approval`.
- **Kandev `plan-mode.md`**: «After saving, save your changes... STOP and
  wait for the user to review» — тот же паттерн «запиши и замри», но это
  старый chat-thread режим Kandev (Plan Mode одного треда), а не колонки
  workflow, которыми построены наши маршруты. Смешивать нельзя: здесь нет
  аналога `step_complete_kandev`, продвижение происходит по факту
  человеческого сообщения в том же треде, а не по явному сигналу агента.
- **`code-architect`** как subagent вообще не имеет понятия «условие
  завершения» — он возвращает ответ вызывающему агенту и на этом его роль
  кончается; решение, что делать дальше (спросить человека, запустить ещё
  агентов), — целиком на оркестраторе (`feature-dev.md`).
- Ни один сторонний источник не описывает эквивалент обязательного вызова
  `step_complete_kandev` — это специфика самого Kandev workflow engine, не
  встречается за его пределами.

## Расхождения и спорное

**Главное расхождение — «выбери один вариант» против «дай список с
trade-off'ами» — существует не столько между разными ролями по разным
инструментам, сколько между уровнем subagent'а и уровнем оркестратора внутри
одного и того же инструмента.** `code-architect.md` прямым текстом запрещает
subagent'у отдавать меню (`:9, 17, 34`). Но команда, которая его вызывает,
`feature-dev.md`, делает прямо противоположное на уровень выше: «Launch 2-3
code-architect agents in parallel with different focuses: minimal changes...,
clean architecture..., or pragmatic balance...» (`feature-dev.md:78`), затем
«Present to user: brief summary of each approach, **trade-offs comparison**,
your recommendation with reasoning» и «**Ask user which approach they
prefer**» (`:80-81`). То есть внутри одного плагина одна и та же формулировка
роли («не давай меню») используется как строительный блок, из которого
оркестратор намеренно собирает меню для человека — каждый вызов
`code-architect` уверен в своём единственном ответе, но их несколько, и
сравнение — уже работа оркестратора, а не архитектора.

Это прямо касается нашей развилки: `Solution Synthesis` в наших цепочках —
не subagent под управлением текстового оркестратора в том же треде, это
отдельный шаг со своим turn и с зафиксированной дорожкой (`Decision Mapping →
Targeted Research → Solution Synthesis → Solution Approval`, см.
`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md`). У неё нет
«оркестратора над собой», который мог бы запустить три параллельных версии и
сравнить — раз мы решили, что маршрут это дорожка, а не текст в промпте с
условными прыжками (`DEVELOPMENT-ROUTES.md`, разделы «Кто выбирает маршрут» и
«Агентские переходы: что осталось в резерве»). Значит `Solution Synthesis`
должна вести себя как `code-architect`, а не как `feature-dev.md`-оркестратор
— потому что у нас нет отдельного шага-оркестратора, который бы стал
запускать несколько версий синтеза параллельно.

**Второе расхождение — что происходит с отвергнутыми вариантами.**
`code-architect` про них не пишет вообще: trade-offs у него — только для
выбранного подхода. spec-kit и MADR, наоборот, требуют письменной записи
отвергнутого — «Alternatives considered» и полноценные pros/cons по каждому
варианту соответственно. Для роли, которая явно получает вход от
`Targeted Research` (то есть в контексте уже реально лежат несколько
исследованных вариантов, не абстрактных), полное молчание про отвергнутое —
как у `code-architect` — рискует выглядеть так, будто исследование было
потрачено впустую, а человек на `Solution Approval` не сможет быстро
проверить «а альтернативу Х агент вообще видел?».

**Третье расхождение — где стоит критик.** `modernize-reimagine` вставляет
автоматического `architecture-critic` строго между синтезом и человеком
(`:70-78`) — синтез правится до показа человеку. Kandev-шаблон «Architecture»
делает ровно наоборот: критиком выступает сам человек на шаге `Review`, и
если он недоволен — задача просто едет обратно в `Planning`
(`workflow-tips.md:75-76`, «A user message there moves the task back to
Planning for another design turn»). Наш маршрут Deep ближе ко второму:
`Solution Approval` не имеет автоматических событий и правка выполняется
только через ручной возврат (`DEVELOPMENT-ROUTES.md`, «Transition safety»).
Автоматического критика в наших четырёх Deep-шагах нет вовсе — это стоит
держать в уме как потенциальный «known gap» в духе уже зафиксированных в
`DEVELOPMENT-ROUTES.md` (разомкнутый review-цикл у `Plan Review`/`Review
Fixes`), но не как готовое решение.

## Выводы для нас

**Взять:**
- Буквальную формулу `code-architect` — «выбери и обоснуй именно выбранное»,
  а не «сравни всё». Применить её на уровне финального артефакта
  `solution-synthesis.md`: одна рекомендация, её обоснование и её trade-offs
  — не таблица из N вариантов.
- Триаду spec-kit Decision / Rationale / Alternatives considered как
  внутреннюю структуру на каждый узел решения. Она ложится на нашу дорожку
  идеально: `Decision Mapping` перечисляет развилки, `Targeted Research`
  наполняет каждую фактами, `Solution Synthesis` обязана на каждую развилку
  дать ровно одну строку Decision+Rationale, а затем связать их в цельный
  текст решения — это буквально то, для чего существует эта роль, и это
  единственный найденный источник, чья внутренняя структура пофайлово
  повторяет наш трёхшаговый пайплайн (хотя у spec-kit это один агент в одном
  проходе, а не три отдельных шага).
- Обязательную остановку после записи артефакта до человеческого решения —
  паттерн общий для `modernize-reimagine` Phase D и самого Kandev
  `plan-mode.md`. У нас это уже прямо задано архитектурой маршрута
  (`Solution Approval` без автоматических переходов), но полезно явно
  прописать в промпте, что `step_complete_kandev` вызывается после записи
  файла, а не вместо согласия человека — это разные вещи, которые в
  chat-thread версии Kandev (`plan-mode.md`) слиты в одно «STOP», а в
  workflow-версии разнесены на «сигнал агента» и «решение человека на
  отдельном шаге».

**Не брать:**
- Паттерн `feature-dev.md` «запусти несколько версий и дай человеку выбрать
  между ними» — это прямо противоречит формулировке задания («сделать выбор,
  а не переложить его на человека») и архитектурному принципу наших
  маршрутов, что решение о том, что показывать человеку, не размазывается по
  промптам, а видно на самой дорожке. Если понадобится сравнение
  вариантов — для этого уже есть отдельная корзина у человека на входе в
  маршрут (`Route Choice`) и явный человеческий выбор внутри `Decision
  Mapping`/`Targeted Research`, а не внутри `Solution Synthesis`.
- Автоматического критика по образцу `architecture-critic` — не потому что
  идея плоха, а потому что в текущих четырёх Deep-шагах для него нет
  отдельного turn'а, и вводить его сейчас — расширение объёма роли за
  пределы брифа. Достаточно отметить как открытый вопрос на будущее, по
  аналогии с уже зафиксированными в `DEVELOPMENT-ROUTES.md` «Known gaps»
  (разомкнутый review-цикл `Plan Review`).

**Чего в источниках нет, а нам нужно из-за особенностей Kandev:**
- **Файловый handoff между шагами с возможным сбросом контекста.** Ни один
  найденный аналог не описывает синтез как отдельный агентный turn, который
  стартует с чистого контекста и обязан сначала прочитать артефакты
  предшественников с диска (`decision-mapping.md`, `targeted-research.md`).
  Везде либо один агент делает разведку и синтез в одном проходе
  (`code-architect`, spec-kit `/plan`), либо состояние живёт в памяти одного
  чата (`feature-dev.md`). У нас `Solution Synthesis` может получить
  контекст только через artifact protocol — это нужно прописать явно,
  ни у одного источника такой фразы позаимствовать не получится.
- **Явное разделение двух источников фактов внутри одного документа.** Наш
  замысел прямо требует «свести локальный контекст проекта и принесённые из
  интернета данные» — то есть в тексте `solution-synthesis.md` должна быть
  видна метка происхождения факта (аналог `web` / `frame` / `assumed` у
  kit-lite `plan.md`). Ни один прочитанный внешний источник не размечает
  факты по происхождению внутри итогового архитектурного документа: у
  `code-architect` источник один (сам код), у spec-kit — тоже один агент на
  оба этапа. Разметку происхождения придётся вводить самим, ориентируясь на
  уже принятую в kit-lite конвенцию, а не на найденные внешние образцы.
- **Условие завершения через явный вызов инструмента.** Ни у кого из
  сторонних источников нет эквивалента `step_complete_kandev` — это чисто
  инфраструктурное требование Kandev, которое придётся сформулировать с
  нуля, без опоры на аналоги.
