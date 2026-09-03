# Artifact protocol

## Наш замысел

Общий контракт передачи результатов между шагами цепочек Kandev. Роли работают в разных
turn'ах агента, часть шагов стартует со сброшенным контекстом (см.
`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md`, раздел «Границы контекста»), поэтому
передача идёт через файловые артефакты в `.kandev/artifacts/<KANDEV_TASK_ID>/`. Каждый шаг
владеет своим файлом (имя = имя колонки, без номера — одна роль стоит в трёх маршрутах на
разных позициях), читает только перечисленные входы и не переписывает чужой результат.
`README.md` — индекс: task title, workflow, исходный commit, список артефактов, статусы,
зависимости. Артефакт создаётся только при содержательном результате — обязательные пустые
файлы не создаются. Артефакты — рабочая память, не часть продукта: не версионируются (Discovery
добавляет каталог в локальный Git exclude, не трогая версионируемый `.gitignore`), решения,
которые должны пережить workspace, переносятся в docs/ADR/PR description. Kandev Plan (через
`create_task_plan_kandev`/`update_task_plan_kandev`) остаётся отдельным source of truth для
утверждённого плана — не файловый артефакт, пишет его только `Planning`. Секреты и credentials
в артефакты не пишутся. На этом этапе (`DEVELOPMENT-ROUTES.md`) сам протокол — только описание
намерения и заглушка `@custom-artifact-protocol`; данное исследование — вход для его написания.

## Найденные аналоги

| инструмент | как называется роль/механизм | где лежит |
|---|---|---|
| kit-lite (`/home/dev/projects/kit-lite`) | матрица `reads.always/may/never`, `writes`, `writes_never`, метки `frame`/`web`/`assumed`/`stale`, файл `assumptions.md`, статусы возврата подагента | `/home/dev/projects/kit-lite/roles/README.md` (правила 3–10), `lead.md`, `build.md`, `intake.md`, `plan.md`, `research.md:62-66` |
| Claude Code plugin `project-artifact` | конфиг проекта `config.md` + рендер `page.html`, state-блок для дельт, freshness/trust правила | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/project-artifact/skills/project-artifact/SKILL.md` |
| Claude Code plugin `code-modernization` | каталог `analysis/$1/` и `modernized/$1*/` по стадиям, `/modernize-status` — инвентарь артефактов, проверка staleness по mtime, secrets hygiene | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/code-modernization/commands/modernize-status.md`, `modernize-reimagine.md:126-138` |
| Claude Code plugin `plugin-dev` (advanced-workflows) | state file `.claude/*.local.md` с YAML frontmatter, flag/lock файлы, checkpoint log, atomic write | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:300-635` |
| Claude Code plugin `ralph-loop` | state file `.claude/ralph-loop.local.md`: YAML frontmatter, session isolation, самолечение при порче (удалить и начать заново) | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/ralph-loop/hooks/stop-hook.sh`, `scripts/setup-ralph-loop.sh` |
| Kandev (сам продукт) | `session-handover.md` — предупреждение новой сессии о предыдущей работе в том же workspace; `write_task_document_kandev`/`get_task_document_kandev`/`list_task_documents_kandev` — MCP-документы на родительской/связанной задаче (Office-режим) | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/session-handover.md`, `office-context.md:9-11` |
| Cline | Memory Bank — папка `memory-bank/` с файлами `projectbrief.md`, `productContext.md`, `activeContext.md`, `systemPatterns.md`, `techContext.md`, `progress.md`; агент обязан прочитать их «before you do any work» | https://docs.cline.bot/features/memory-bank |
| BMAD-METHOD | цепочка персон, каждая производит один версионированный документ и передаёт следующей (Analyst → Project Brief → PM → PRD → Architect); document sharding для story-level работы | https://bmad-code-org-bmad-method-6.mintlify.app/advanced/shard-documents (описание вторично, по агрегированным поисковым выжимкам) |
| MetaGPT | общий message pool + publish/subscribe по ролям (Architect публикует System Design, Engineer подписан на него, QA — на код) | вторично, по агрегированным поисковым выжимкам (arxiv.org/abs/2308.00352) |
| AutoGen/AG2 | Swarm/handoff: `HandoffMessage` в общем контексте разговора, а не файл; это другая модель — расширяемый общий контекст, а не файловая память | вторично, docs.ag2.ai (Swarm pattern) |
| Anthropic (инженерный блог) | Lead agent + subagents: субагенты пишут большие результаты во внешнюю файловую систему и передают лид-агенту только ссылки/пути, а не пересказ — «avoiding the game of telephone» | вторично, по агрегированным поисковым выжимкам (anthropic engineering blog "How we built our multi-agent research system") |
| Blackboard architecture (общая CS-концепция, множество LLM-реализаций 2025-2026) | общая доска, на которую независимые Knowledge Sources пишут и с которой читают; координация асинхронная и косвенная | вторично, по агрегированным поисковым выжимкам (несколько статей и репозиториев, см. запрос "blackboard architecture LLM shared state") |

Superpowers `subagent-driven-development` упоминается в kit-lite (`lead.md`, `build.md`) как
источник статусов отчёта и правила «implementer никогда не спавнит subagents», но сам плагин
локально не найден (не оказался в `claude-plugins-official`) — цитирую только то, что
приведено в kit-lite, как вторичную ссылку, не как самостоятельно прочитанный текст.

## Что кладут всегда

- **Один файл — один владелец, остальные только читают.** У всех пяти основных источников
  (kit-lite, project-artifact, code-modernization, Cline Memory Bank, BMAD). kit-lite формулирует
  это как правило №4 «Один файловый артефакт на роль» (`README.md`); code-modernization держит
  по файлу на стадию в `analysis/$1/` (`PREFLIGHT.md`, `ASSESSMENT.md`, `BUSINESS_RULES.md`…);
  BMAD — «Each persona is a bounded role that produces one versioned artifact».
- **Явный список того, что роль обязана прочитать, прежде чем начать.** kit-lite формализует
  это в `reads: { always, may, never }` в шапке контракта каждой роли (`README.md`, раздел
  «Шапка контракта»); Cline Memory Bank требует прочитать весь набор файлов «before you do any
  work» (docs.cline.bot); Anthropic-паттерн — субагент получает путь/ссылку, не пересказ лида.
  У 3 из 3 источников, где вообще формализован входной контракт (kit-lite, Cline, Anthropic).
- **Timestamp/freshness как первая проверяемая вещь.** project-artifact пишет UTC as-of в
  статус-баннер каждого рендера («Put the as-of timestamp (UTC) in the status banner — it's
  the first thing a reader needs to calibrate everything else», SKILL.md); code-modernization
  строит отдельный раздел «Staleness» в `/modernize-status`, сравнивая mtime производного
  артефакта с артефактом-источником. У 2 из источников, у которых вообще есть механизм
  повторного прогона (project-artifact, code-modernization).
- **Провал источника — это `stale`, а не выдумка.** project-artifact: «A failed fetch... makes
  that data stale, not invented: keep the previous values, mark exactly which rows or sections
  are stale, and never fill gaps from memory». kit-lite — та же идея как метка `stale` в
  `assumptions.md` (правило №8). У 2 источников, оба независимо приходят к одному слову.
- **Секреты/credentials никогда не попадают в артефакт.** code-modernization —
  отдельный раздел «Secrets hygiene» с проверкой `.gitignore` и `git log --all` на утечку;
  code-modernization Phase F — «connection details and credentials appear only as env-var names
  ... never as values»; project-artifact — то же правило для fetched-текста. 2 из 2 источников,
  где вообще есть риск секретов в артефактах.

## Что кладут иногда

- **Метка происхождения факта (откуда взято).** Только у kit-lite: `frame` (прочитано в коде/
  документах проекта), `web` (принесено из интернета — ссылка есть, но не факт проекта),
  `assumed` (решено самим), `stale` (было верно, больше нет) — `README.md`, правило №8.
  Показательно, что сам kit-lite это разделение ввёл только на втором проходе: «В каталоге
  `frame` объединяло „прочёл в коде проекта" и „прочёл на сайте"» (`research.md:64`) — то есть
  даже внутри одного проекта это не сразу очевидное решение. У других источников такой метки
  нет: BMAD и MetaGPT не различают происхождение факта внутри артефакта вовсе.
- **State-блок для инкрементального обновления (не полная перезапись).** project-artifact:
  встроенный JSON `<script type="application/json" id="artifact-state">` с `as_of` и списком
  workstream-статусов, чтобы следующий прогон читал дельту, а не писал заново
  («Refreshing an artifact... a delta, not re-narrative»). Больше нигде в найденных источниках
  подобного встроенного диффа нет — остальные либо не поддерживают повторные прогоны (kit-lite),
  либо переиспользуют лог из append-only чекпоинтов (advanced-workflows.md: `echo
  "checkpoint:build" >> .claude/deployment-checkpoints.log`).
  1 из ~7 источников.
- **Отдельный «заметки» файл сверх основного артефакта роли.** kit-lite: `build` пишет
  и коммиты, и `build-notes.md» — «Иначе им некуда класть assumed, а check.sh не может
  проверить, что они были» (`README.md`, правило №4). У остальных ролей kit-lite — один файл.
  Нигде за пределами kit-lite такого раздвоения нет.
- **Замок/lock-файл против параллельного запуска.** Только у plugin-dev advanced-workflows:
  `.claude/deployment.lock`, создаётся при старте и удаляется по завершении
  (`advanced-workflows.md:404-448`). У остальных источников либо параллелизм разрешён через
  дизъюнктные каталоги на агента (code-modernization Phase A — «Each agent writes only to its
  own `modernized/$1-reimagined/<service-name>/` directory (disjoint, so parallel writes don't
  conflict)»), либо вопрос не поднимается вовсе.
- **Верификация машиной, а не следующим агентом.** kit-lite — `check.sh`, который читает
  git-трейлер `Kit-Role: <роль>` в коммитах, чтобы отличить коммиты `test-author` от `build»
  (правило №7), и сверяет права на запись (`writes_never`) — «Самый частый обход TDD —
  исполнитель правит тест; это запрет на запись, и его держит скрипт, а не промпт» (правило
  №10). Из остальных источников подобная скриптовая проверка (не LLM-проверка) есть только у
  ralph-loop (валидация численных полей frontmatter перед арифметикой) и отчасти у
  code-modernization (`/modernize-status` — «This is a read-only command — inspect, never
  modify»), но там это инвентаризация, а не enforcement прав на запись.

## Чего сознательно не кладут

- **Полные истории/переписки сессии в артефакт.** Anthropic-паттерн прямо формулирует это как
  решение проблемы: субагенты передают лиду только сводки или ссылки на файлы, не всю историю
  (вторично, «only passing summaries (not the whole history) to new Subagents»). kit-lite —
  то же явным запретом: `build` имеет `reads.never: [история сессии]` (`build.md`).
- **Пересказ артефакта следующей роли голосом текущей.** kit-lite, правило для `lead`: «Не
  пересказывает артефакты подагентам — даёт пути к файлам. Пересказ — испорченный телефон»
  (`README.md`, раздел «Чего тимлид не делает»). Дословно совпадает с формулировкой Anthropic —
  «avoiding the game of telephone» (по вторичной ссылке) — это два независимых источника,
  пришедших к одному и тому же запрету одними и теми же словами.
- **Правка чужого файла.** У kit-lite (`writes_never` в каждом контракте, например у `build`:
  `writes_never: [тестовые файлы, plan.md, test-plan.md]`) и у project-artifact («update the
  previous render in place… rebuild from the template only when the structure itself
  changes») — оба ограничивают, что именно можно менять при повторном заходе, а не разрешают
  трогать произвольно чужой контент.
- **Пустой обязательный артефакт «для галочки».** DEVELOPMENT-ROUTES.md формулирует это как
  наше собственное решение: «Artifact создаётся только при содержательном результате;
  обязательные пустые файлы лишь расходуют токены и создают ложное ощущение завершённости».
  Прямого аналога такому явному запрету в исследованных источниках не нашлось — ближе всего
  code-modernization, где `/modernize-status` вообще не требует наличия файла на каждой
  стадии, просто фиксирует пропуски в таблице инвентаря.
- **Секреты и credentials.** См. выше — совпадает у project-artifact и code-modernization,
  оба формулируют это как категорический запрет, а не рекомендацию.
- **Модификация артефактов инспекционным/статусным шагом.** code-modernization: `/modernize-
  status` явно maркирован «read-only command — inspect, never modify». Единственный найденный
  источник с таким явным разделением ролей на «читает и отчитывается» / «пишет».

## Формат вывода

- **kit-lite**: `brief.md` — потолок 40 строк («Длиннее — это уже спека, а не бриф»,
  `intake.md`); `plan.md` — две секции («для человека» ≤40 строк, «для исполнителя» —
  сигнатуры и файлы), `build-notes.md` — фиксированная структура (Коммиты / Сделано против §2
  / Отклонения / Допущения / Вывод тестов / На что посмотреть ревью); каждый артефакт
  завершается статусом роли (`DONE`/`DONE_WITH_CONCERNS`/`NEEDS_TEST_FIX`/`STUCK`/`BLOCKED`).
- **project-artifact**: единый self-contained HTML-файл с фиксированным каталогом секций
  (Overview обязателен всегда; остальные — «only when there's something substantive»), плюс
  скрытый JSON state-блок для дельт, плюс отдельный `config.md` (Project / Artifact / Sources /
  People / Notes).
- **code-modernization** (`/modernize-status`): не собственный формат вывода роли, а отчёт
  инспектора — таблица «Stage → Artifacts» + разделы Staleness / Secrets hygiene / Verdict
  (три строки: где мы, что устарело, следующая команда с одной причиной).
- **Cline Memory Bank**: шесть файлов с фиксированными именами и назначениями, каждый —
  свободный markdown без жёсткого шаблона внутри.
- Общий знаменатель по всем источникам: **имя файла или секции фиксировано заранее** (не
  придумывается на лету), а **длина каждого раздела ограничена явно** («40 строк», «one
  screen», «a handful of lines, not a re-narrative»).

## Условие завершения

- **kit-lite**: у каждой роли есть `done_when` в шапке контракта — проверяемое условие
  (например у `plan`: «у каждого шага — команда и что она ловит… секция 1 не длиннее 40
  строк»); плюс отдельно код-роли обязаны вернуть один из фиксированных статусов.
- **project-artifact**: шаг 4 явно требует ре-чтения собственного вывода перед публикацией
  («Review the output for cut-off text and overflow… re-read the file») — завершение это не
  просто «написал», а «написал и проверил на обрезание/переполнение».
- **Kandev (сам продукт, не сторонний источник)**: единственный жёсткий, механически
  проверяемый гейт среди всех источников — явный вызов `step_complete_kandev`; обычное
  завершение ответа, вопрос пользователю, ошибка или отмена НЕ продвигают задачу
  (`DEVELOPMENT-ROUTES.md`, «Transition safety»). Ни у одного стороннего аналога нет
  инструмента-сигнала такого уровня строгости — везде это соглашение промпта, не платформенный
  контроль.
- **code-modernization**: условие завершения стадии — не самопровозглашённое, а проверяемое
  следующим прогоном `/modernize-status`: файл существует + не старше апстрим-артефакта, из
  которого выведен.

## Расхождения и спорное

- **Файл vs. общая память (blackboard/message pool) vs. общий контекст разговора.** Три разные
  модели координации у разных источников: kit-lite/project-artifact/code-modernization/Cline —
  файлы на диске, каждый со своим владельцем; MetaGPT — общий message pool с publish/subscribe
  (все видят все сообщения, фильтрация по подписке, а не по файловым правам); AutoGen/AG2
  Swarm — вообще не файл, а `HandoffMessage` внутри одного общего контекста разговора,
  который явно передаётся следующему агенту. Это принципиально разные архитектуры: файловая
  модель предполагает границы (что нельзя прочитать/переписать), message pool — прозрачность
  по умолчанию с опциональной фильтацией, shared-context — единый непрерывный поток без
  разделения на «моё/чужое» вообще. Наш выбор (файлы с явными правами) ближе всего к kit-lite
  и Anthropic-паттерну, дальше всего — от AutoGen Swarm.
- **Кто чинит staleness.** У project-artifact следующий прогон той же роли сам замечает и
  чинит устаревание (перечитывает предыдущий рендер и делает дельту). У code-modernization
  устаревание не чинится автоматически — `/modernize-status` только обнаруживает и
  рекомендует конкретную команду для перезапуска, решение остаётся за человеком/оркестратором.
  kit-lite ближе ко второй модели: `stale` — это запись в `assumptions.md`, которую видит
  следующая роль, а не автоматический пересчёт.
- **Версионирование артефактов.** BMAD называет артефакты персон «versioned» явно, project-
  artifact хранит версии через `label` в Artifact tool и версии-пикер на самой странице.
  kit-lite и code-modernization версий не хранят вовсе — файл просто перезаписывается, история
  живёт в git commit log (для кода) или нигде (для kit-lite md-файлов, они не версионируются:
  `.kit/` в `.gitignore`). У нас — `.kandev/artifacts/` тоже вне версионируемого `.gitignore»
  (в локальном Git exclude), то есть история артефактов внутри задачи не хранится вовсе,
  только финальный commit/PR — ближе к kit-lite/code-modernization, не к BMAD/project-artifact.
- **Разрешено ли роли писать больше одного файла.** kit-lite декларирует правило «один
  артефакт на роль» (README правило №4), но тут же оговаривает практическое исключение —
  код-роли пишут ещё и notes-файл. project-artifact пишет `page.html` + `config.md` как
  штатную пару. То есть «один файл» — не универсальный принцип даже внутри одного источника,
  а скорее «один основной файл, plus по необходимости служебный».

## Выводы для нас

**Стоит взять:**
- Явную матрицу `reads.always/may/never` + `writes`/`writes_never` в описании каждой роли
  (kit-lite) — это единственный найденный способ формально ограничить, что роль имеет право
  тронуть, помимо честности промпта. У нас это тем более критично: DEVELOPMENT-ROUTES.md уже
  фиксирует «читает только перечисленные входы и не переписывает чужие результаты» как принцип,
  но не даёт механизма его проверки.
- Метки происхождения `frame`/`web`/`assumed`/`stale` (kit-lite) — прямое попадание в наш
  контекст: у нас есть `Targeted Research` (внешние источники) и `Discovery`/`Decision
  Mapping` (внутренние), различие между «прочитано в репозитории» и «принесено из интернета»
  будет нужно ровно там же, где оно понадобилось kit-lite.
- «Путь, а не пересказ» между шагами (kit-lite + независимо Anthropic-паттерн) — совпадение
  двух источников делает это одним из немногих пунктов, которые действительно стоит закрепить
  буквально в тексте протокола.
- as-of timestamp как первая проверяемая строка любого артефакта (project-artifact) и
  staleness-проверка по производности одного артефакта от другого (code-modernization) — у нас
  уже есть готовая точка: README.md-индекс может держать «зависимости» между артефактами именно
  для этой цели, DEVELOPMENT-ROUTES.md это уже упоминает («список созданных artifacts, их
  статус и зависимости»), но не описывает как ей пользоваться при staleness-проверке — стоит
  прописать явно.
- «Failed fetch = stale, never invented» (project-artifact) — прямо переносимо на наш случай,
  когда шаг стартует со сброшенным контекстом и не находит ожидаемого входного артефакта:
  правило должно требовать явную остановку/пометку, а не додумывание содержимого.
- Секреты никогда не в артефакт — уже зафиксировано в DEVELOPMENT-ROUTES.md, оба независимых
  источника (project-artifact, code-modernization) подтверждают это как универсальную практику,
  можно писать без оговорок.

**Не стоит брать:**
- Полноценное версионирование артефактов с picker'ом (project-artifact) — избыточно для
  рабочей памяти одной задачи, которая явно не является продуктом (DEVELOPMENT-ROUTES.md:
  «Это рабочая память, а не часть продукта»). Один файл, одна текущая версия — достаточно.
- Общий message pool с publish/subscribe (MetaGPT) — Kandev-архитектура уже жёстко линейна
  (шаги идут по маршруту колонка за колонкой), а не оркестрирует произвольное множество
  параллельных ролей, читающих всё подряд; явные `reads`-списки из kit-lite подходят точнее.
- Lock-файлы против конкурентного запуска (plugin-dev) — в модели Kandev параллельность внутри
  одной задачи ограничена (`Research` и `Design` — единственная явная пара, которая может идти
  параллельно, согласно DEVELOPMENT-ROUTES.md), и она уже решается дизъюнктными файлами
  (каждая роль — свой файл), а не блокировкой. Отдельный lock-механизм добавил бы сложность без
  выигрыша.

**Чего в источниках нет, а нам нужно из-за особенностей Kandev:**
- **Проверяемое завершение шага через инструмент, а не через текст/статус в файле.**
  `step_complete_kandev` — платформенный примитив, у которого нет прямого аналога ни в одном
  найденном источнике (kit-lite полагается на договорной `check.sh`, который сам ещё не
  написан; остальные источники вообще не привязаны к жёсткому execution engine). Протокол
  должен явно описать, что запись артефакта и вызов `step_complete_kandev` — разные действия,
  и файл не считается «принятым», пока сигнал не отправлен.
- **Начальная инициализация артефактного каталога без отдельного шага.** DEVELOPMENT-ROUTES.md
  уже принял решение («Discovery в Triage инициализирует manifest, а каждая последующая роль
  проверяет его наличие и создаёт минимальную структуру, если карточку внесли в маршрут
  напрямую, минуя Triage») — ни у одного стороннего источника нет аналога «прямого входа в
  маршрут» и связанной с ним обязанности произвольной роли доинициализировать структуру.
  Протокол должен явно описать этот bootstrap-путь, потому что источники его не покрывают.
- **Совмещение файлового hand-off с MCP-инструментами, у которых своя семантика владения.**
  Kandev Plan (`create_task_plan_kandev`) — не файл, полностью заменяется при каждой записи, и
  DEVELOPMENT-ROUTES.md уже фиксирует «вторая пишущая роль просто затрёт первую» как причину
  дать право записи только `Planning`. `publish_review_findings_kandev` у `Code Review` — ещё
  один канал, параллельный файлу. Ни один источник не описывает координацию файлового протокола
  с отдельным набором MCP-примитивов, имеющих собственные правила перезаписи — это специфика
  Kandev, которую придётся продумывать с нуля.
- **Multi-repository задачи.** DEVELOPMENT-ROUTES.md прямо помечает это как нерешённое
  («расположение общего каталога нужно определить отдельно… текущие маршруты предполагают один
  основной repository root»). Ни в одном исследованном источнике нет multi-repo кейса вообще —
  все они (kit-lite, project-artifact, code-modernization) явно однопроектные.
- **Три маршрута разной глубины с разным набором шагов, читающих один и тот же протокол.**
  У kit-lite один маршрут (с вариантами «лёгкая/полная полоса», но это ветвление внутри одной
  системы правил, которую пишет один автор). У Kandev маршруты (`Quick`/`Standard`/`Deep`) —
  архитектурно устойчивая часть продукта (колонки доски), и один и тот же файл артефакта может
  оказаться на разной позиции в разных маршрутах — источники, кладущие имя файла = номеру шага
  (project-artifact, code-modernization все нумеруют артефакты по стадии), для этого не
  подходят; DEVELOPMENT-ROUTES.md уже сделал верный выбор (имя = имя колонки, без номера) — этот
  выбор ни в одном источнике не был нужен, потому что ни у одного нет параллельных маршрутов
  переменной длины.

## Оговорки по методу

- Веб-поиск использован ограниченно (6 запросов), как и предписано брифом. Три источника
  (BMAD, MetaGPT, AutoGen/AG2) процитированы по агрегированным выжимкам поисковых результатов,
  не по прочтению первичного текста (arxiv/docs) — это явно помечено как «вторично» в каждом
  месте, где использовано. Первичным чтением подтверждены: весь локальный корпус (kit-lite,
  project-artifact, code-modernization, plugin-dev advanced-workflows, ralph-loop,
  session-handover.md, office-context.md, DEVELOPMENT-ROUTES.md) и один внешний источник
  (Cline Memory Bank — docs.cline.bot, содержание подтверждено search snippet, не полным
  fetch страницы).
- Superpowers `subagent-driven-development`, на который ссылается kit-lite, физически не найден
  ни в локальном корпусе плагинов, ни отдельным поиском по диску — процитирован только в объёме,
  в котором его цитирует kit-lite, как вторичная ссылка.
- Ошибок веб-поиска не было — все 6 запросов отработали штатно.
