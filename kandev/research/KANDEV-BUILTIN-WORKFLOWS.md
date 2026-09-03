# Встроенные цепочки Kandev: как авторы платформы делают то же самое

Источник найден поздно, уже после разбора ролей, и оказался самым весомым:
`/tmp/kandev-v0.93.0/apps/backend/config/workflows/` — девять готовых цепочек,
которые Kandev ставит из коробки, с полными промптами шагов.

Это не сторонний инструмент со своими правилами. Это те же колонки, те же
события, те же MCP-инструменты — написанные людьми, которые платформу и
сделали.

## Что там лежит

| Файл | Цепочка | Колонки |
|---|---|---|
| `feature-dev.yml` (18 КБ) | Feature Dev | Todo → Spec → Work → Review → QA → PR → CI Fixup → Done |
| `plan-and-build.yml` | Plan & Build | Todo → Plan → Implementation → Done |
| `architecture.yml` | Architecture | Ideas → Planning → Review → Approved |
| `improve-kandev.yml` | Improve Kandev | Improve → Test → PR |
| `pr-review.yml` | PR Review | Waiting → Review → Done |
| `office-default.yml` | Office Default | Backlog → Work → Review → Approval → Done |
| `kanban.yml` | Kanban | Backlog → In Progress → Review → Done |
| `routine.yml` | Routine | In Progress → Done |
| `report-kandev-issue.yml` | Report Kandev Issue | Open issue |

`Feature Dev` — прямой аналог наших маршрутов и самая проработанная из всех.

## Главное расхождение: они не автоматизируют переходы

Посчитано по всем девяти файлам:

| Цепочка | Автопереходов | Гейт по сигналу |
|---|---:|---:|
| `feature-dev` | **0** | 0 |
| `plan-and-build` | **0** | 0 |
| `architecture` | **0** | 0 |
| `improve-kandev` | **0** | 0 |
| `report-kandev-issue` | 0 | 0 |
| `pr-review` | 1 | 0 |
| `routine` | 1 | 0 |
| `kanban` | 4 | 0 |
| `office-default` | 5 | 1 |

Во флагманской восьмиколоночной `Feature Dev` **нет ни одного**
`on_turn_complete`, ни одного `move_to_next`, ни одного
`auto_advance_requires_signal` и ни одного упоминания `step_complete_kandev`.
Каждый переход между фазами делает человек, перетаскивая карточку.

Автопереходы есть только там, где фаз мало и они дешёвые: простая `Kanban`,
`Routine`, `PR Review`. Единственная цепочка с гейтом по сигналу —
`office-default`, и она не про разработку.

Закономерность читается так: **чем больше в цепочке содержательных фаз, тем
меньше её авторы доверяют автоматическому переходу.**

У нас ровно наоборот. Все четыре маршрута — сплошной `move_to_next` с
`auto_advance_requires_signal: true` на каждом шаге. Это не обязательно
ошибка: мы сознательно строили «запустил и ушёл», а гейт по сигналу как раз и
есть страховка, которой у них нет. Но стоит понимать, что мы отклонились от
того, как платформу используют её авторы, и отклонились в сторону большей
автоматизации.

## Паттерны из их промптов, которых нет в нашей сводке

### Блок GIT SAFETY, повторённый дословно в каждом рабочем шаге

Встречается в `feature-dev.yml` восемь раз — во всех шагах, где агент вообще
может выполнить команду:

> - NEVER run `git checkout -- .`, `git checkout .`, `git reset --hard`,
>   `git clean -fd`, or `git stash --include-untracked`. These wipe
>   uncommitted work.
> - When reverting files touched by formatters/linters, ALWAYS pass explicit
>   paths (e.g. `git checkout -- path/to/file path/to/dir/`). Never use `.`
>   or unscoped globs.
> - Treat any uncommitted changes you did not make as intentional user work —
>   leave them in place. Do not revert, stash, or overwrite them.

Обратите внимание: блок не вынесен в общий workflow-level prompt, а
продублирован в каждом шаге. У `Feature Dev` поле `prompt` на уровне цепочки
пустое. Это осознанный выбор в пользу надёжности против экономии токенов: при
сбросе контекста общий промпт мог бы не доехать.

У нас общий контракт вынесен в `@custom-artifact-protocol` на уровне цепочки —
противоположное решение. Стоит проверить, доезжает ли workflow-level prompt до
шага со сброшенным контекстом.

### STEP 0: сначала составь список подзадач

Одинаково во всех шагах:

> STEP 0: CREATE A TASK LIST
> Before anything else, create a task list tracking the substeps below (use
> your todo/task tracking tool if available). Mark each task in_progress when
> you begin it and completed when you finish. Do not skip ahead — each step
> feeds the next.

Роль обязана начать с планирования собственной работы внутри шага. «Do not
skip ahead» — прямой запрет перепрыгивать подшаги.

### Нумерованные фазы и заголовок в скобках

Все промпты построены одинаково: `[SPEC PHASE]`, `[WORK PHASE]`,
`[QA PHASE]`, `[CI FIXUP PHASE]`, затем `STEP 0`, `STEP 1`, … Никакого
свободного повествования. Заголовки капсом.

### Числовой предел попыток

В шаге `Work`:

> - After 3 failed fix attempts on the same issue: stop, question the
>   approach, ask the user.

Это ответ на вопрос, который при разборе `Plan Review` остался открытым:
счётчик кругов существует — но не как механизм платформы, а как число в тексте
промпта. В `CI Fixup` тот же приём иначе: «Poll every 30 seconds, cap at 10
minutes» — предел на ожидание, но не на число исправлений.

### Условия остановки перечислены отдельным шагом

`Work`, STEP 3:

> - If you hit a blocker (missing dependency, unclear requirement, test fails
>   repeatedly): stop and ask the user.
> - If a fix requires an architectural change (new DB table, new service
>   layer, switching libraries): stop and ask.

Не «действуй разумно», а список конкретных ситуаций.

### Дисциплина коммитов с уважением к чужой работе

`Work`, STEP 4:

> Stage and commit every file YOU created or modified for this task, using
> explicit paths. Any uncommitted or untracked changes you did not make are
> intentional user work — leave them as-is. **Do not aim for an absolutely
> clean tree**; aim for none of YOUR task-related edits to be uncommitted.

Явный отказ от соблазна «привести дерево в порядок».

### QA сформулирован враждебно

> Verify the feature works end-to-end. **Your goal is to find bugs, not
> confirm it works.**

И перед проверкой поведения — проверка того, что фича вообще подключена:

> STEP 2: TRACE THE WIRING
> - Exports are imported and used (not just defined)
> - API routes have consumers
> - Data flows end-to-end: input -> handler -> storage -> response -> display

Этого объектива у нас нет ни в `Verification`, ни в `Code Review`: код,
который написан и протестирован, но никуда не подключён, пройдёт обе наши
проверки.

### TDD расписан шестью действиями с проверкой причины падения

`Work`, STEP 2:

> 1. Write a failing test that asserts the expected behavior
> 2. Run the test — confirm it fails **with the expected assertion error
>    (not a compile error)**
> 3. Write the minimum code to make it pass
> 4. Run the test — confirm it passes
> 5. Refactor while keeting tests green
> 6. Commit the change

Различение «падает по нужной причине» и «падает потому что не собирается» —
ровно то, что при разборе `Test Authoring` нашлось как сквозной паттерн.

Существенно и другое: у них TDD целиком внутри **одного** шага `Work`. У нас
он растянут на три колонки — `Test Authoring`, `Implementation`,
`Verification`, — хотя и в одном контексте.

### Spec требует варианты, а не один

> STEP 3: DESIGN THE SOLUTION
> - Propose 2-3 approaches with trade-offs and your recommendation.

Прямо противоположно `code-architect` из плагина `feature-dev`, который
требует «pick one approach and commit». Наш `Solution Synthesis` спроектирован
по второму образцу. Расхождение между самим Kandev и плагином Anthropic —
не в нашу пользу, потому что после нашего `Solution Synthesis` идёт
человеческий гейт `Solution Approval`, а человеку на гейте сравнивать нечего.

### Чтение журнала решений проекта

`Spec`, STEP 2:

> Check if the repo has a decision log (e.g. `docs/decisions/`) and read
> relevant decisions.

Ни у нас, ни в плагинах Anthropic этого нет.

## Что с этим делать

1. **Проверить, доезжает ли workflow-level prompt до шага после
   `reset_agent_context`.** Если нет — весь наш `@custom-artifact-protocol`
   не доедет ровно до тех ролей, которым он нужнее всего, и придётся
   дублировать его по шагам, как это делают авторы.

2. **Взять блок GIT SAFETY почти дословно.** Он про необратимую потерю чужой
   работы, и в наших цепочках агент запускает команды на шести шагах из
   семнадцати.

3. **Добавить объектив «подключено ли» в `Verification`.** Дёшево и ловит
   класс ошибок, который наши проверки пропускают целиком.

4. **Решить про `Solution Synthesis`:** один вариант или два-три с
   рекомендацией. Сам Kandev перед человеческим гейтом даёт варианты.

5. **Осознать отклонение по автоматизации переходов** и решить, оставляем ли
   мы `move_to_next` на всех шагах. Наш гейт по сигналу — та страховка,
   которой у них нет, но у них и переходов нет.
