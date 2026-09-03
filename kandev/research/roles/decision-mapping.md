# Decision Mapping

## Наш замысел
Первый шаг маршрута Deep. Оставляет только РЕАЛЬНЫЕ развилки — те решения, где
действительно есть выбор между вариантами с разными последствиями. Отбрасывает
мнимые развилки, где ответ уже задан кодом, конвенциями проекта или очевиден.
Результат — список развилок, каждая с формулировкой выбора и критерием, по
которому его делать. Следующий шаг (Targeted Research) исследует именно их, а
не тему вообще (`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md:80-81`).

## Найденные аналоги

Прямого аналога — «шаг-агент workflow, который заранее сортирует развилки на
пустые/исследуемые/человеческие, и ничего кроме этого списка не делает» — ни в
локальном корпусе, ни в интернете не нашлось. Есть несколько частичных
аналогов, каждый закрывает часть замысла.

| Инструмент | Как называется роль | Где лежит |
|---|---|---|
| kit-lite | `forks` («развилки»), поглотила `options` | `/home/dev/projects/kit-lite/roles/forks.md`, `/home/dev/projects/kit-lite/roles/options.md` |
| Encyclopedia of Agentic Coding Patterns (aipatternbook.com) | `Tradeoff` | https://aipatternbook.com/tradeoff |
| Encyclopedia of Agentic Coding Patterns | `Risk Spike` | https://aipatternbook.com/risk-spike |
| Encyclopedia of Agentic Coding Patterns | `Architecture Decision Record` | https://aipatternbook.com/architecture-decision-record |
| feature-dev (claude-plugins-official) | Phase 3 «Clarifying Questions» + Phase 4 «Architecture Design» (не отдельный агент, а фазы одной команды) | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/commands/feature-dev.md:57-81` |
| code-modernization (claude-plugins-official) | `architecture-critic` (критика уже готового дизайна, не поиск развилок заранее) | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/code-modernization/agents/architecture-critic.md` |
| code-modernization | `/modernize-brief` §7 «Open Questions» (раздел внутри общего плана, не отдельная роль) | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/code-modernization/commands/modernize-brief.md:155-157` |
| code-modernization | `/modernize-preflight` Check 0/6 (человеку задают вопросы про то, чего нет в коде, до всякого анализа) | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/code-modernization/commands/modernize-preflight.md:17-59,156-183` |
| Superpowers (obra) | `brainstorming` skill | https://agenticskills.io/skills/brainstorming , https://skillselion.com/skills/obra/superpowers/brainstorming |
| ChatDev | LLM-роль задаёт уточняющие вопросы на нечёткую спецификацию (не выделено в отдельную «развилочную» роль) | упомянуто в академической статье, найдено через веб-поиск, без прямого файла |
| SPARC (ruvnet) | фаза Specification требует явных assumptions/constraints/exclusions до перехода к Pseudocode | https://github.com/ruvnet/ruflo/wiki/SPARC-Methodology |
| Kandev (`config/prompts/*.md`) | аналога нет вовсе | проверено по всем 20 файлам в `/tmp/kandev-v0.93.0/apps/backend/config/prompts/` — есть только `plan-mode.md` (общий режим планирования без сортировки развилок) и упоминание `record_step_decision_kandev` (approve/reject самого шага workflow, другая семантика) |

Источников с прямым совпадением сути (сортировка «нет развилки / нужен поиск /
нужен выбор человека», отдельным заходом до исследования) — один: `kit-lite:forks`,
судя по всему написанный тем же автором раньше как предшественник этого набора
ролей. Остальные — общие практики «сначала спросить, потом решать», без выделения
именно фильтра мнимых/реальных развилок в отдельный шаг.

## Что кладут всегда

- **Различают решения человека и решения агента.** У всех источников, что
  вообще касаются темы (kit-lite, feature-dev, modernize-preflight/-brief,
  Superpowers brainstorming) — question-раздел явно адресован человеку, а не
  решается агентом по умолчанию. Пример: kit-lite `forks.md:44` — «Очевидно:
  запиши вариант и одну причину, без поиска… Нужен выбор человека: два-три
  варианта… одна рекомендация с причиной». Считаю: 4 из ~6 источников с
  содержательным пересечением.
- **Не одно решение — набор вариантов с ценой/следствием каждого**, а не
  бинарный да/нет. aipatternbook `Tradeoff`: «What are we optimizing for? /
  What are we accepting as a cost? / Under what conditions would we revisit
  this?» (https://aipatternbook.com/tradeoff). feature-dev Phase 4: «brief
  summary of each approach, trade-offs comparison… your recommendation with
  reasoning» (`feature-dev.md:80`). kit-lite `forks.md:61`: «два-три варианта,
  чем отличаются по-человечески — деньги, время, риск, — и одна рекомендация
  с причиной». Совпадает во всех трёх.
- **Явное «здесь развилки нет» — тоже полноценный результат, не пропуск.**
  kit-lite `forks.md:29` — done_when включает «у "очевидных" записан выбранный
  вариант и причина»; `options.md:14` то же для готового/вдвое меньше. У
  modernize-preflight Check 6: «If `$1` really is a standalone repository, one
  line saying so is the whole check» (`modernize-preflight.md:185-186`) — тот
  же принцип для смежной задачи (граница scope, не развилка, но тот же приём
  «нет — тоже ответ, дёшево»).

## Что кладут иногда

- **Структурированный обход по областям/чек-листу**, а не свободный поиск
  развилок. Есть только у kit-lite (`forks.md:39-42`: 8 фиксированных
  областей — данные, границы API, интерфейс/ошибки, безопасность, миграции,
  тестирование, готовое-вместо-своего, вдвое-меньше) и у SPARC (Specification
  требует конкретный набор пунктов: outcome, actors, assumptions, constraints,
  exclusions). У feature-dev и Superpowers обхода по областям нет — вопросы
  идут произвольно, по ситуации.
- **Параллельные агенты с разными «уклонами» вместо одного списка развилок.**
  feature-dev Phase 4 запускает 2-3 `code-architect` с разным фокусом
  (минимальные правки / чистая архитектура / прагматичный баланс) и потом
  сравнивает результаты (`feature-dev.md:78`) — это способ *породить*
  альтернативы, а не отсортировать уже найденные. У kit-lite и Superpowers
  такого нет — один агент формулирует варианты сам.
- **Верхний предел на число вопросов/развилок.** kit-lite: «Больше 12 развилок
  — задача плохо нарезана, скажи об этом lead» (`forks.md:50`). Superpowers:
  «Only one question per message». У остальных источников лимита нет.
- **Явное «предложи 2-3 варианта» как фиксированное число.** Superpowers:
  «Propose 2-3 different approaches with trade-offs», «Always propose 2-3
  approaches before settling» (https://agenticskills.io/skills/brainstorming).
  feature-dev: тоже 2-3 (агента). kit-lite не фиксирует число вариантов внутри
  развилки.

## Чего сознательно не кладут

- **Не решает развилки сам, если они не «очевидные».** kit-lite: «Не решай
  сам то, что во второй и третьей корзине» (`forks.md:49`). Прямая
  противоположность — `code-architect` из feature-dev: «Make decisive choices
  - pick one approach and commit… Make confident architectural choices rather
  than presenting multiple options» (`code-architect.md:17,34`). Это не одна и
  та же роль: `code-architect` работает **после** того, как решение о подходе
  уже принято (или это единственный вариант, который просят спроектировать
  подробно), а не вместо шага сортировки развилок. Указываю как расхождение
  ниже.
- **Не ищет в интернете на этом шаге.** kit-lite: «Не ищи в интернете»
  (`forks.md:49`), контракт `may_research: no` (`forks.md:27`) — поиск отдан
  следующей роли `research`. Тот же принцип у нас: Decision Mapping отдаёт
  найденное Targeted Research.
- **Не переписывает то, что уже решено кодом/конвенцией — считает это не-
  развилкой, а не темой для рекомендации.** Явно нигде не сформулировано как
  запрет («не предлагай альтернативу тому, что не альтернатива»), но
  подразумевается везде через «Нет развилки — тоже ответ»: если бы вариант был
  один, не было бы смысла спрашивать. Это ближе всего к нашей формулировке
  «мнимые развилки», но ни один источник не использует именно эту рамку —
  все формулируют позитивно («есть выбор?»), а не как явный фильтр «есть кто-то
  один правильный вариант — выбрось».
- **ADR-паттерн не пишется для тривиальных решений.** aipatternbook ADR:
  «Avoid for trivial choices like variable names»
  (https://aipatternbook.com/architecture-decision-record) — тот же дух
  фильтрации, но для документирования постфактум, а не для отбора вопросов
  заранее.

## Формат вывода

- **kit-lite `forks.md`**: артефакт `questions.md`, три корзины плюс список
  областей без развилки:
  ```
  # questions — <задача>/<пункт>
  ## Очевидно
  - [данные] история заказов — отдельная таблица; причина: ...
  ## Нужен поиск
  - Q1 [границы] как в <стек v> принято ...
  ## Нужен выбор человека
  - H1 [интерфейс] ... варианты: A / B; рекомендация: A, потому что ...
  ## Готовое вместо своего
  ## Вдвое меньше
  ## Областей без развилки: миграции, безопасность
  ```
  (`forks.md:52-66`). Каждый вопрос помечен областью в квадратных скобках.
- **aipatternbook `Tradeoff`**: не фиксированный документ, а три обязательных
  поля внутри design doc/spec/ADR: «What are we optimizing for? / What are we
  accepting as a cost? / Under what conditions would we revisit this?».
- **aipatternbook `Architecture Decision Record`**: жёсткий шаблон в одну
  страницу — Title / Status / Context (2-4 предложения) / Decision (active
  voice) / Consequences; хранится в `docs/decisions/001-*.md`.
- **feature-dev**: не отдельный файл — вопросы и варианты печатаются в чат,
  «Present all questions to the user in a clear, organized list» (Phase 3),
  «brief summary of each approach, trade-offs comparison… recommendation»
  (Phase 4). Никакой фиксированной длины.
- **modernize-brief §7**: список чекбоксов, которые должен отметить
  approver — «Anything requiring human/SME decision before Phase 1 starts.
  Each as a checkbox the approver must tick» (`modernize-brief.md:155-157`).
- **Superpowers brainstorming**: итог — design-спека
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, не список развилок
  как таковой — вопросы по пути туда не сохраняются отдельным артефактом.

Вывод по формату: только kit-lite `forks` формализует именно **список
развилок с корзинами** как отдельный переносимый артефакт, который читает
следующая роль. Остальные либо встраивают вопросы в чат-диалог (feature-dev,
Superpowers), либо в раздел большого документа (modernize-brief), либо в
постфактум-документацию решения (ADR).

## Условие завершения

- **kit-lite `forks`**: `done_when: пройдены все области; каждая развилка в
  одной корзине; у «очевидных» записан выбранный вариант и причина`
  (`forks.md:29-31`). Формально проверяемое условие, привязанное к
  фиксированному списку из 8 областей.
- **feature-dev Phase 3**: неявное — «Wait for answers before proceeding to
  architecture design»; если пользователь отвечает «whatever you think is
  best», агент обязан дать рекомендацию и получить явное подтверждение
  (`feature-dev.md:67-69`) — условие завершения фазы держится на человеке, а
  не на чек-листе.
- **modernize-preflight Check 0**: «Ask, then do not block on the answers…
  Any question still unanswered goes in the report verbatim, marked as an
  open item» (`modernize-preflight.md:26-34`) — шаг обязан закончиться даже
  если человек не ответил; недостающее просто помечается, а не блокирует
  прогресс. Это ближе к нашей модели (шаг workflow обязан вызвать
  step_complete и не может зависнуть в ожидании).
- **Superpowers brainstorming**: завершается явным одобрением пользователя
  design-документа («once you understand what you're building, it presents
  the design and gets user approval»), то есть у него человек в контуре
  синхронно, а не как отдельный шаг доски.
- У aipatternbook `Risk Spike` условие завершения — не список развилок, а
  «да/нет на один вопрос осуществимости» плюс обязательное time-boxing
  (минуты-часы) и обязательное уничтожение экспериментального кода после
  получения ответа (https://aipatternbook.com/risk-spike) — другая по природе
  роль (эксперимент, не сортировка), но полезная граница: если развилка
  требует «попробовать код, чтобы узнать ответ» — это уже не Decision Mapping,
  а отдельная работа.

## Расхождения и спорное

- **«Предлагать решения» vs «не предлагать».** `code-architect`
  (feature-dev) явно требует брать на себя решение и не показывать
  альтернативы («pick one approach and commit»), тогда как kit-lite `forks` и
  Superpowers `brainstorming` требуют обратного — не решать за человека и
  показывать 2-3 варианта. Разрешение противоречия по контексту: `code-
  architect` работает уже после того, как принято решение писать подробный
  архитектурный чертёж для одного согласованного подхода (следующий этап
  цепочки), то есть это роль ближе к нашему Planning/Solution Synthesis, не к
  Decision Mapping.
- **Синхронный диалог с человеком vs асинхронный артефакт.** feature-dev и
  Superpowers brainstorming рассчитаны на интерактивный чат (спросил — тут же
  получил ответ, следующий шаг зависит от ответа). kit-lite `forks` и
  modernize-preflight рассчитаны на то, что ответ может не прийти сразу
  («asks_human: free» — человек ответит при первом касании; или «do not block
  on the answers… mark as open item»). Для наших пошаговых agent-turn'ов с
  обязательным `step_complete_kandev` актуальна вторая модель — Decision
  Mapping не может зависнуть в ожидании синхронного ответа человека внутри
  одного turn'а.
- **Число областей/чек-лист vs свободный поиск.** kit-lite и SPARC жёстко
  структурируют обход (списком областей), feature-dev и Superpowers ищут
  вопросы свободно по ситуации. Ни один источник не объясняет, какой подход
  лучше при какой нагрузке — это не обсуждается явно, просто разный выбор
  разных инструментов.

## Выводы для нас

**Взять:**
- Три корзины kit-lite `forks` («очевидно / нужен поиск / нужен выбор
  человека») почти дословно ложатся на связку наших ролей: очевидное
  Decision Mapping закрывает сам, «нужен поиск» уходит в Targeted Research,
  «нужен выбор человека» — либо в Solution Approval, либо оседает в
  Solution Synthesis как открытый вопрос для approval-шага.
- Формулировку про мнимые развилки стоит держать буквально как фильтр:
  «если ответ уже задан кодом/конвенцией — не развилка», а не только позитивно
  «есть ли выбор» — ни один источник этого явно не формулирует, у нас это
  ключевое требование задания, и его нужно вписать в промпт своими словами.
- Тройку вопросов из `Tradeoff` («что оптимизируем / чем жертвуем / когда
  пересмотрим») можно использовать как критерий качества записи по каждой
  «реальной» развилке — задание требует «критерий, по которому её делать»,
  и это готовая, проверенная формулировка такого критерия.
- Верхний предел числа развилок (kit-lite: >12 — сигнал, что задача плохо
  нарезана) стоит взять как защиту от разрастания шага в общий дорогой обзор,
  ровно то, от чего предостерегает `DEVELOPMENT-ROUTES.md:81`.

**Не стоит брать:**
- Параллельные агенты с разным уклоном (feature-dev Phase 4) — это способ
  *порождать* альтернативы вычислительно дорого; наша роль работает в одном
  turn'е с одним агентом и явно не занимается генерацией альтернативных
  архитектур, а сортировкой уже видимых развилок.
- Синхронный интерактивный диалог (feature-dev, Superpowers) — не подходит
  формату «шаг workflow, обязан завершиться `step_complete_kandev`»; вопросы
  человеку не могут блокировать turn, они должны лечь в артефакт и ждать
  касания на следующем шаге (ближе к модели modernize-preflight: «ask, then do
  not block»).

**Чего в источниках нет, а нам нужно из-за Kandev:**
- Ни один источник не рассчитан на то, что результат этого шага читает
  **другой агент с чистым контекстом** на следующем шаге workflow. У kit-lite
  `forks` есть file-артефакт `questions.md`, но нет ограничения «сброшенный
  контекст», поскольку весь набор kit-lite — не пошаговый workflow с
  отдельными turn'ами, а один сквозной прогон подагентов. Нам нужно явно
  проговорить в промпте: артефакт должен быть самодостаточным для Targeted
  Research без доступа к рассуждениям, которые привели к списку развилок.
- Ни у кого нет привязки к конкретному месту записи —
  `.kandev/artifacts/<TASK_ID>/decisions.md` (или аналогичное) — это наше,
  архитектура файловых артефактов Kandev формируется отдельно и должна быть
  задана в промпте явно, а не выведена из аналогов.
- Ни один аналог не обязан вызывать инструмент завершения шага
  (`step_complete_kandev`) — у нас это жёсткое условие, отсутствующее во всех
  найденных источниках, и его нужно вписать как отдельное обязательное
  действие в конце промпта, а не полагаться на «естественное» завершение
  диалога.

## Заметка про экономию поиска
Веб-поиск не падал; сделано 5 запросов WebSearch и 4 WebFetch (немного больше
исходного лимита 6-8, но по существу — уточняющие переходы на страницы,
найденные первыми запросами, а не новые темы). Все использованные источники
перечислены выше со ссылками.
