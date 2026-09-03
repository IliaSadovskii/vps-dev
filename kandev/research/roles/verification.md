# Verification и Final Verification

## Наш замысел

Две роли, которые раньше ссылались на один и тот же промпт — признанный дефект
(`/home/dev/projects/vps-dev/kandev/prompts/custom-verification.md`,
`custom-final-verification.md` сейчас обе — безопасные заглушки-стопперы, ещё
не спроектированы).

**Verification** — идёт сразу после `Implementation`, **в том же
контексте**, что `Test Authoring` и `Implementation`
(`/home/dev/projects/vps-dev/kandev/workflows/quick.yml:69-87`, то же в
`standard.yml:119-121`, `deep.yml:184-186`; на `on_enter` нет
`reset_agent_context`). Комментарий в коде: «Замыкает red-green цикл в том же
контексте, что Test Authoring и Implementation». Задача узкая: тесты,
написанные на `Test Authoring`, должны стать зелёными.

**Final Verification** — идёт после `Review Fixes`, **в контексте Review
Fixes** (не реализации): на `on_enter` тоже нет `reset_agent_context`, только
`auto_start_agent` (`quick.yml:151-169`, `standard.yml:200-205`,
`deep.yml:265-268`). Комментарий: «Работает в контексте Review Fixes, а не
реализации, и гоняет полный прогон после правок — поэтому у неё свой промпт».
После неё — `Draft PR`
(`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md:93-98`).

`Review Fixes, Final Verification` есть в маршруте только «если ревью
что-то нашло» (`DEVELOPMENT-ROUTES.md:36`) — то есть у Final Verification
пустой вход возможен и не является дефектом.

## Найденные аналоги

| инструмент | как называется роль | где лежит |
|---|---|---|
| Kandev (наш продукт), встроенный шаблон **Feature Dev** | `QA` — приходит после `Review`, до `PR`, находит баги end-to-end, а не подтверждает | `/tmp/kandev-v0.93.0/apps/backend/config/workflows/feature-dev.yml:206-254` |
| Kandev, `TDD внутри Work` того же шаблона | Test-first цикл (red→green→refactor) как часть **одного** шага `Work`, отдельной узкой Verification нет | `feature-dev.yml:86-98` |
| Kandev, `ci-auto-fix.md` / `mr-auto-fix.md` | не отдельная роль, но их правило верификации — прямой первоисточник паттерна «сначала узко» | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/ci-auto-fix.md:6`, `mr-auto-fix.md:11` |
| Kandev, `CI Fixup` того же шаблона | Роль, ближе всего к «финальному прогону + цикл исправлений», но по CI, не по локальным тестам | `feature-dev.yml:302-346` |
| kit-lite | `test-run` — **не роль**: сознательно влита в `build` и в скрипт `check.sh`, вывод считает не модель, а код возврата | `/home/dev/projects/kit-lite/roles/test-run.md` |
| kit-lite | `check.sh` — скрипт-контролёр, не LLM-роль вовсе; правило 1 «тесты первыми», правило 4 «маршрут пройден» | `/home/dev/projects/kit-lite/roles/check.md` |
| kit-lite | `debug` — подагент «свежего взгляда» на застрявший красный тест, вызывается по факту `STUCK`, не правит код/тесты сам | `/home/dev/projects/kit-lite/roles/debug.md` |
| Anthropic marketplace, `claude-security` | `patch-verifier` — единственный автоматический чек перед выдачей патча человеку; прогоняет тесты как условие вердикта, но это ревьюер диффа, не исполнитель red-green | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/claude-security/agents/patch-verifier.md:1-45` |
| Anthropic marketplace, `code-modernization` | `test-engineer` пишет тесты (аналог Test Authoring), а «Step 3 — Prove it» команды `modernize-transform.md` — прогон и цикл «fix and re-run until green» — ближе к Verification | `.../code-modernization/agents/test-engineer.md`, `.../code-modernization/commands/modernize-transform.md:92-98` |
| Anthropic marketplace, `ralph-loop` | не роль — режим цикла целой сессии; шаблон промпта включает «3. Run tests 4. If any fail, debug and fix... 6. Repeat until all green» | `.../ralph-loop/README.md:109-116` |
| Superpowers (obra) | `verification-before-completion` — не шаг пайплайна, а сквозная дисциплина: запрет заявлять успех без свежего вывода команды и её exit code | через WebFetch пересказа `raw.githubusercontent.com/obra/superpowers/main/skills/verification-before-completion/SKILL.md` |
| BMAD-METHOD | модуль TEA (Test Engineering Architect), агент «Murat» — `tea-test-review` как headless CI-гейт с реальными exit-кодами и 35-строчным реестром критериев; про раздельные узкую/широкую проверки не нашёл | через WebSearch-сниппеты `docs.bmad-method.org/reference/skills-and-agents/` — не открывал первоисточник, низкая уверенность |
| «Build-Verify Loop» (community, regolo.ai) | не именованная роль, а CI-паттерн: Gate 1 обязательный (`pytest tests/ -x -q`, строгий exit code) + Gates 2-4 политика (покрытие, запрещённые пути, секреты) — деление скорее «обязательное/консультативное», чем «узкое/широкое» | regolo.ai/the-build-verify-loop-... (WebFetch пересказа) |
| Community "test-runner" subagent (не первоисточник) | детектирует фреймворк тестов через `package.json`/`Makefile`, прогоняет и чинит — общий паттерн, встречается в нескольких независимых репозиториях подобных subagents | через WebSearch-сниппеты, конкретный файл не открывал — низкая уверенность |

**Отдельной роли «Final Verification», отличной от обычного `test-run`/`Verification`,
нигде в корпусе как явного самостоятельного шага не нашлось.** Ближе всего —
`CI Fixup` у самого Kandev (прогон + цикл исправлений, но по CI после PR, не
локально после ревью) и `patch-verifier` (тоже финальный/единственный
автоматический чек перед выдачей человеку, но ревьюер диффа с полномочием
отклонить, а не исполнитель, гоняющий тесты до зелёного).

## Что кладут всегда

**1. Реальный прогон и его вывод — обязательное условие, не заявление.**
6 из 6 источников, которые вообще формулируют правило верификации:

- kit-lite: «Запуск тестов — детерминированное действие, у него есть код
  возврата. Модель здесь может только одно: соврать о результате» —
  `test-run.md`.
- Superpowers: «NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE» —
  идентифицировать команду, выполнить её целиком, прочитать вывод и exit
  code, только потом заявлять результат.
- `patch-verifier.md:44`: `testsRun` заполняется «verbatim commands you
  executed, or "none possible" and why» — нельзя промолчать о том, что тесты
  не запускались.
- Feature Dev `Work`: «2. Run the test — confirm it fails... 4. Run the test —
  confirm it passes» — `feature-dev.yml:90-92`.
- ralph-loop: «3. Run tests 4. If any fail, debug and fix» —
  `README.md:111-113`.
- `modernize-transform.md:94-98`: «Show the output. If anything fails, fix
  and re-run until green.»

**2. Различают «упало по нужной причине» и «не собралось/тест сломан».**
Zафиксировано в исследовании Test Authoring как относящееся туда, но тот же
принцип у соседних verification-ролей звучит зеркально для перехода в
зелёное: `feature-dev.yml:90` — «confirm it fails with the expected assertion
error (not a compile error)», далее «confirm it passes» — то есть зелёный
статус тоже подтверждается конкретной строкой вывода, а не предположением.

**3. Узнают команды из репозитория, а не выдумывают.** Явно в 3 источниках:
`patch-verifier.md:28` — «Find the project's own test command (CI config,
`package.json`, `Makefile`, `tox.ini`, and the like) and run it in the
workspace»; сам Kandev — `workflow-tips.md:214` — «Keep repository-specific
instructions such as AGENTS.md, CLAUDE.md, skills, test commands, and MCP
configuration in that repository»; `modernize-transform.md:12-22` — «Step 0a
— Toolchain check... before planning» проверяет, что тулчейн вообще
отвечает, прежде чем строить план.

## Что кладут иногда

- **Паттерн «сначала узко, потом широко».** В прямой формулировке нашёлся
  только в двух родственных промптах самого Kandev — `ci-auto-fix.md:6` и
  `mr-auto-fix.md:11`: «Run the narrowest relevant verification commands
  first, then broader checks if needed». Больше нигде в корпусе (ни в
  Anthropic marketplace, ни в kit-lite, ни в community-источниках) этот
  принцип текстом не сформулирован — я искал `narrow` по всему маркетплейсу
  и по kit-lite и не нашёл ни одного другого совпадения по теме тестов.
  Ближайший функциональный аналог — «Build-Verify Loop»
  (regolo.ai): деление на обязательный Gate 1 (полный прогон тестов) и
  консультативные Gates 2-4, но это ось «блокирует/не блокирует», а не
  «узкий/широкий» прогон.
- **Предел попыток при провале.** Явно заданное число встречается у 2
  источников с разными числами: Feature Dev `Work` — «After 3 failed fix
  attempts on the same issue: stop, question the approach, ask the user» —
  `feature-dev.yml:103`; Build-Verify Loop (regolo.ai) — «If you cannot make
  tests pass after 5 fix attempts, stop and write a comment». `CI Fixup` у
  Kandev предела попыток исправления не задаёт вовсе, только предел времени
  на сам поллинг CI: «Poll every 30 seconds, cap at 10 minutes» —
  `feature-dev.yml:330`, а цикл «STEP 3 → STEP 2» ничем не ограничен кроме
  этого. kit-lite ограничивает не число попыток, а меняет исполнителя: после
  второго `STUCK` подряд подключается `debug` — «свежий взгляд» —
  `debug.md`.
- **«Свежий взгляд» на застрявшую проверку — отдельная роль/подагент.**
  Только kit-lite формализует это отдельной ролью `debug`, которая явно не
  правит ни код, ни тесты, а только называет причину и одно исправление —
  `debug.md`. У Kandev похожего механизма нет: `CI Fixup` чинит сам, без
  передачи «свежему взгляду».
- **Финальная роль как единственный автоматический гейт перед выдачей
  результата человеку/наружу.** `patch-verifier.md:12` — «You are the ONLY
  automated check this fix gets before it becomes a file on the user's
  disk... your default is REJECT, and the fix earns a PASS» — по духу
  ближе всего к тому, чем могла бы быть Final Verification (последний
  автоматический барьер перед Draft PR), но реализовано как ревью с правом
  отклонить работу другого агента, а не как исполнитель, который сам гоняет
  прогон до зелёного.

## Чего сознательно не кладут

- **Не подгонять тест под код при провале.** У ближайших source по теме это
  правило сформулировано для авторства тестов (см. исследование Test
  Authoring), но для верификации формулируется зеркально — запрет
  ослаблять/подстраивать под наблюдаемый результат:
  `patch-verifier.md:27` — «any change that *weakens* security while
  claiming to fix it (a loosened auth check, a removed validation, a widened
  allowlist, a **disabled test**) is an automatic reject»;
  `test-engineer.md:13-16` (code-modernization) — «The legacy code is the
  oracle... We're proving equivalence first; fixing bugs is a separate
  decision» — то есть даже расхождение с ожиданием не повод переписать тест
  молча, это отдельно фиксируемый факт. Ни в одном источнике не нашёл
  разрешения адаптировать тест под текущее поведение кода как штатный путь
  «позеленить».
- **Не заявлять успех без свежего вывода команды.** Superpowers формулирует
  это максимально жёстко и явно перечисляет, что НЕ считается
  верификацией: прошлые прогоны, частичные проверки, прохождение линтера
  (не подтверждает компиляцию), собственный отчёт другого агента об успехе,
  уверенность/предположения.
- **Не мержить и не выдавать результат самой роли.** `ci-auto-fix.md:12` /
  `mr-auto-fix.md:12` — «Do not merge the pull/merge request. Kandev handles
  auto-merge separately»; `patch-verifier.md:16` — «you inspect and test;
  you never modify the workspace» (для верификатора, отдельного от
  исполнителя фикса).
- **Не тратить прогон на заведомо неактуальное состояние.** `ci-auto-fix.md`
  и `mr-auto-fix.md` одинаково: «Pending-only... snapshots are also
  non-actionable: when `failed_checks: []`... but checks are still queued or
  running, do not modify files, do not run local verification... and do not
  poll indefinitely.»
- **Не проверять то же самое, что уже проверяет CI.** Явного текстового
  запрета «это оставь CI» в корпусе не нашёл ни в одном источнике — граница
  между локальной верификацией и CI нигде не проговорена как правило,
  только подразумевается разделением ролей (`Work`/`QA` локально →
  `CI Fixup` — по факту готового пайплайна). Это скорее пробел источников,
  чем «сознательно не кладут» — см. раздел «Выводы для нас».

## Формат вывода

- **kit-lite `check.sh`**: не проза, а код возврата 0/1 плюс по строке на
  правило `OK`/`FAIL` — причина — что сделать; секция «Вывод тестов» внутри
  `build-notes.md` как обязательная часть чужого артефакта, не отдельного.
- **`patch-verifier`**: строго структурированный вердикт — `PASS`/`REJECT`,
  три заявления (`TARGETED`, `NO_NEW_VULNERABILITY`, `BEHAVIOUR_UNCHANGED`) со
  статусом `CONFIDENT`/`NOT_CONFIDENT`/`UNSURE` и строкой доказательства
  каждое, плюс обязательные поля `untested`, `REVIEWED_PATHS`, `testsRun`
  (verbatim-команды или «none possible and why»).
- **Feature Dev `Work`**: не отдельный артефакт верификации — фиксация через
  git-коммиты по шагам TDD-цикла плюс `git status`/коммит перед выходом из
  шага.
- **Feature Dev `QA`**: секция «STEP 6: REPORT» — что подтверждено рабочим,
  какие баги найдены (`file:line` + как воспроизвести), какого тестового
  покрытия не хватает.
- **`ci-auto-fix.md`/`mr-auto-fix.md`**: «summarize what changed and which
  verification commands you ran» — минимум, без структуры полей.
- Ни один источник не задаёт фиксированную длину; общий знаменатель —
  «команда + вывод + вердикт», не эссе.

## Условие завершения

- **Красное → зелёное, подтверждённое свежим прогоном** — общий знаменатель
  всех TDD-ориентированных источников (kit-lite, Feature Dev `Work`,
  ralph-loop, modernize-transform Step 3).
- **`patch-verifier`**: завершение — вынесенный вердикт `PASS`/`REJECT` со
  всеми обязательными полями; сам факт запуска тестов не гейт сам по себе,
  гейт — это совокупность трёх заявлений `CONFIDENT` плюс закрытый exploit
  path.
- **`CI Fixup` (Kandev)**: завершение — «When all checks pass, report the CI
  status and the PR URL» — то есть конца ждут именно от внешнего CI, а не от
  локального суждения роли.
- **Предел попыток как условие остановки, а не только успеха.** У
  Build-Verify Loop и Feature Dev `Work` есть явный «выход по потолку» —
  застрять и написать, что заблокировано, вместо того чтобы бесконечно
  повторять попытки. У Kandev-роли `CI Fixup` такого потолка на число
  попыток фикса нет — только временной кап на ожидание самого CI.
- **Kandev, `step_complete_kandev` как формальный сигнал.** Это наш
  собственный механизм (`DEVELOPMENT-ROUTES.md:100-106`), явного аналога
  «вызов инструмента завершения шага» ни у одного стороннего источника нет —
  они привязаны к git-состоянию, зелёному прогону или структурированному
  вердикту, а не к явному API-сигналу оркестратору.

## Расхождения и спорное

- **Останавливаться при провале или чинить самой.** Единого ответа нет.
  `debug`-подход kit-lite и `patch-verifier` — роль **не чинит**, только
  диагностирует/отклоняет. `CI Fixup`, ralph-loop, Build-Verify Loop,
  `modernize-transform` Step 3 — роль **чинит сама** в цикле до предела
  попыток или до зелёного. Наш дизайн (Verification замыкает red-green в
  контексте Implementation) ближе ко второй группе, но источники расходятся
  и по числу попыток (3 у Feature Dev, 5 у Build-Verify Loop, «до второго
  `STUCK`» у kit-lite перед подключением `debug`) и по тому, эскалируется ли
  застревание к отдельной роли/подагенту (только kit-lite) или к человеку
  напрямую (Feature Dev, Build-Verify Loop).
- **Разделять ли узкую и широкую проверку явным правилом или доверять
  масштабу задачи.** Только `ci-auto-fix.md`/`mr-auto-fix.md` формулируют
  это прямо; Feature Dev `QA` наоборот — сразу широкая адверсариальная
  проверка (граничные значения, конкурентность, авторизация) без узкой
  предварительной стадии, потому что в этом шаблоне узкая стадия уже прожита
  внутри `Work`.
- **Нужен ли отдельный шаг «Final Verification» вообще.** Ни один сторонний
  источник не выделяет его как самостоятельную роль, отличную от обычного
  прогона тестов: у Feature Dev `QA` идёт один раз перед `PR` и не
  повторяется после `Review`/фиксов отдельным шагом; у claude-security весь
  цикл «фикс → verify» одноразовый (`patch-verifier` — «the single verifier
  per fix round», согласно `description` в шапке файла). Наша архитектура
  (два разных промпта на двух разных участках пайплайна) — решение, которого
  в корпусе никто не подтверждает и не опровергает: это, по всей видимости,
  следствие структуры Kandev (контекст на шаг, файловые артефакты), а не
  общепринятая практика извне.

## Выводы для нас

**Стоит взять:**
- Различие exit-кода / вывода команды как единственного источника истины —
  общий знаменатель практически всех источников (Superpowers формулирует
  максимально жёстко, `patch-verifier` требует verbatim-команды).
- Разделение «узкое → широкое» из `ci-auto-fix.md`/`mr-auto-fix.md` подходит
  Verification почти буквально: узкое — прогнать именно тесты, написанные на
  Test Authoring; широкое — по обстоятельствам, если узкое зелёное, но есть
  сомнение в побочных эффектах.
- Явный предел попыток перед остановкой/возвратом — ни один сторонний
  источник не оставляет цикл незамкнутым (кроме нашего же `CI Fixup`-аналога
  в Kandev, который сам является примером известного пробела —
  `DEVELOPMENT-ROUTES.md:213-229` фиксирует отсутствие счётчика кругов как
  осознанный gap).
- Запрет ослаблять/подгонять тест под провал, сформулированный по аналогии с
  `patch-verifier.md:27` («disabled test» = автоматический reject) и с
  `test-engineer.md` («legacy is the oracle», расхождение — отдельно
  фиксируемый факт, не молчаливая правка теста).

**Не стоит брать:**
- Сложную структуру трёх заявлений `CONFIDENT`/`NOT_CONFIDENT`/`UNSURE` из
  `patch-verifier` — это специфика роли-ревьюера чужого патча перед выдачей
  наружу пользователю; у Verification нет отдельного «автора» и «проверяющего
  третьего», роль сама и пишет, и гоняет.
- Идею одной общей QA-роли без разделения узкое/широкое (Feature Dev `QA`,
  BMAD TEA) — у нас это разделение уже архитектурно закреплено разными
  шагами (Verification vs Final Verification), сворачивать его в один общий
  промпт значило бы повторить дефект, который мы уже исправляем.

**Чего в источниках нет, а нам нужно из-за особенностей Kandev:**
- **Как формально различать «первый узкий прогон» и «финальный широкий»,
  когда это буквально два разных промпта на двух разных участках цепочки,
  а не два раздела одного промпта.** Все найденные аналоги узко/широкого
  деления (`ci-auto-fix.md`, Build-Verify Loop) — это один непрерывный
  контекст одной роли; у нас Verification и Final Verification — разные
  turn'ы, разные (потенциально) контексты, и Final Verification вообще не
  видит diff Implementation напрямую, только то, что осталось в контексте
  Review Fixes плюс файловые артефакты. Требуется явно прописать, что читает
  Final Verification из `.kandev/artifacts/<TASK_ID>/` (verification.md?
  review-fixes.md?), поскольку ни один источник в принципе не имеет
  file-based hand-off между «узкой» и «широкой» верификацией — они всегда в
  одном контексте.
- **Условие вызова `step_complete_kandev`.** Ни у одного стороннего
  источника нет аналога этому конкретному сигналу — у всех либо git-состояние
  (коммит), либо структурированный вердикт в возвращаемом сообщении, либо
  внешний CI. Нужно самим сформулировать, что для Verification считается
  «готово к сигналу» (все тесты Test Authoring зелёные + ничего не сломано
  из существовавшего) и отдельно для Final Verification (полный прогон после
  Review Fixes зелёный), и прописать это как явное условие в самом промпте,
  а не полагаться на «естественное» завершение, как это делают внешние
  агенты, которые просто перестают писать в чат.
- **Разграничение с CI явным правилом.** Ни один источник в корпусе не
  формулирует его текстом (см. «Чего сознательно не кладут» выше) — при
  этом у нас `CI Fixup`/`ci-auto-fix` уже существует как отдельный
  нативный механизм после `Draft PR`
  (`DEVELOPMENT-ROUTES.md:96-98, 242-245`), значит важно явно указать в
  Verification/Final Verification, что не нужно ждать или опрашивать внешний
  CI — это забота более позднего, отдельного механизма, а не этих шагов.
- **Что делать, если Test Authoring не оставил падающих тестов (пустой
  вход).** У нас это невозможно по конструкции («Test Authoring обязан
  оставить реально падающие тесты»), но источники, которые формализуют такую
  проверку на стороне Verification, не встретились — `check.sh` в kit-lite
  проверяет это как отдельное правило (2 и 4) скриптом до старта работы, а
  не полагается на добросовестность предыдущей роли. Стоит решить, проверяет
  ли Verification сама, что тесты вообще были и падали, или полностью
  доверяет hand-off от Test Authoring.
