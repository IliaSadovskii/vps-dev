# Code Review

> Состояние: локальный корпус разобран, включая четыре независимых источника.
> Интернет-источники не добирались: локального материала по этой роли
> больше, чем по любой другой, и он самодостаточен.

## Наш замысел

Идёт после `Verification` во всех трёх маршрутах. Работает в свежем контексте
(`reset_agent_context`), чтобы не полагаться на самооценку автора кода. Читает
диф и артефакты предшественников, публикует замечания через
`publish_review_findings_kandev`. Дальше `Security Review`, затем
`Review Fixes`.

## Найденные аналоги

| Инструмент | Роль | Где | Размер |
|---|---|---|---|
| Kandev, встроенный | `code-review` | `apps/backend/config/prompts/code-review.md` | 6.0 КБ |
| Anthropic `code-review` | команда-оркестратор | `plugins/code-review/commands/code-review.md` | ~7 КБ |
| Anthropic `feature-dev` | `code-reviewer` | `plugins/feature-dev/agents/code-reviewer.md` | ~3 КБ |
| Anthropic `pr-review-toolkit` | `code-reviewer` + 5 специалистов | `plugins/pr-review-toolkit/agents/` | 4–6 КБ каждый |

Это самая проработанная роль во всём корпусе. Четыре независимых реализации,
и все четыре сходятся в главном, расходясь в устройстве.

## Что кладут всегда

### Порог уверенности числом — 4 из 4

Ни один источник не пишет «будь осторожен». Все дают число и все выбрали 80.

Kandev, плоско:

> Only report findings you're >=80% confident about.

`feature-dev` — шкала 0–100 с якорями на каждом делении:

> - **0**: Not confident at all. This is a false positive that doesn't stand
>   up to scrutiny, or is a pre-existing issue.
> - **50**: Moderately confident. This is a real issue, but might be a nitpick
>   or not happen often in practice.
> - **75**: Highly confident. Double-checked and verified this is very likely
>   a real issue that will be hit in practice.
> - **100**: Absolutely certain. The evidence directly confirms this.
>
> **Only report issues with confidence ≥ 80.**

`pr-review-toolkit` — тот же диапазон, но полосами: `0-25` ложное или
предсуществующее, `26-50` мелочь вне CLAUDE.md, `51-75` верное но
малозначимое, `76-90` важное, `91-100` критичное.

Наблюдение: якоря важнее самого числа. «80» без описания того, что значит 50 и
что значит 100, не калибрует ничего.

### Явный список того, что находкой не считается — 4 из 4

Самый развёрнутый — у команды `code-review`, восемь пунктов. Совпадающие у
всех четырёх:

- предсуществующие проблемы на строках, которые изменение не трогало;
- то, что поймает линтер, типизатор или компилятор;
- педантичные придирки, которые не сделал бы senior;
- намеренные изменения поведения, относящиеся к сути задачи;
- то, что в коде явно заглушено (`lint-ignore`, `nolint`).

Формулировка Kandev по первому пункту жёсткая:

> Issues on lines or files the change didn't modify — even if they are real bugs

То есть настоящий баг рядом — не находка. Роль ограничена дифом намеренно.

### Разделение труда с CI — 4 из 4

Команда `code-review`:

> Do not check build signal or attempt to build or typecheck the app. These
> will run separately, and are not relevant to your code review.

Ревьюер не запускает сборку. Это не экономия, а разграничение: то, что ловится
машиной, машина и ловит.

### Определение базы дифа как отдельный шаг — 3 из 4

Kandev расписывает подробно и предупреждает о типичной ошибке:

> Run: `git remote show origin | grep 'HEAD branch'` to find the default branch
> Set BASE_REF to origin/<default-branch>
> Use: `git diff $(git merge-base "$BASE_REF" HEAD)`
> Do NOT diff directly against BASE_REF or origin/main/master — that would
> include unrelated changes if the branch is outdated

Плюс развилка: если есть незакоммиченные правки — ревьюить их, если дерево
чистое — коммиты ветки.

### Читать файл целиком, а не диф — 2 из 4

Kandev:

> Read each changed file in full — understand surrounding code, not just the
> diff. Navigate callers, interfaces, and tests to understand changes
> end-to-end. Check git blame on modified sections to understand why code was
> written a certain way. Only REPORT issues on code modified in this
> changeset, but USE the full codebase for context.

Разделение «где искать» и «о чём докладывать» проведено явно.

### Проверка на соответствие правилам проекта — 4 из 4

У всех первым или вторым пунктом идёт сверка с `CLAUDE.md`. У команды
`code-review` для этого выделен отдельный агент, и есть тонкая оговорка:

> Note that CLAUDE.md is guidance for Claude as it writes code, so not all
> instructions will be applicable during code review.

### Структурированный вывод с закрытым списком градаций — 4 из 4

Kandev: разделы `## BLOCKER` и `## SUGGESTION`, формат строки
`file:line - Description. Why it matters. How to fix.`, пустые разделы
опускать, в конце вердикт из трёх вариантов:

> Ready to merge / Ready with suggestions / Blocked — fix blockers first

`feature-dev`: группировка `Critical` / `Important`, и отдельно оговорено, что
делать при отсутствии находок — «confirm the code meets standards with a brief
summary», а не молчать.

## Что кладут иногда

### Ревью разбито на узких специалистов — 2 из 4

Это главное структурное расхождение с нашим замыслом.

`pr-review-toolkit` содержит шесть агентов вместо одного: `code-reviewer`,
`silent-failure-hunter` (6.3 КБ), `type-design-analyzer` (4.4 КБ),
`comment-analyzer` (4.4 КБ), `pr-test-analyzer` (4.0 КБ), `code-simplifier`
(2.9 КБ). У всех, кроме двух, `model: inherit`.

Команда `code-review` делает то же, но во время выполнения — пять
параллельных ревьюеров с разными объективами:

> a. Agent #1: Audit the changes to make sure they comply with the CLAUDE.md
> b. Agent #2: Read the file changes, then do a shallow scan for obvious bugs.
>    Avoid reading extra context beyond the changes
> c. Agent #3: Read the git blame and history of the code modified, to
>    identify any bugs in light of that historical context
> d. Agent #4: Read previous pull requests that touched these files, and check
>    for any comments on those pull requests that may also apply
> e. Agent #5: Read code comments in the modified files, and make sure the
>    changes comply with any guidance in the comments

Объективы #3, #4 и #5 у нас не покрыты ничем: история строки, замечания на
прошлых PR по тем же файлам, и указания в комментариях самого кода.

Отдельно стоит объектив #2: ему **запрещено** читать контекст за пределами
изменений. Ограничение осознанное — так ловятся грубые ошибки без утопания в
контексте.

### Оценку уверенности ставит не тот, кто нашёл — 1 из 4

Только команда `code-review`. Находки собирают пять агентов, а оценивает
каждую отдельный дешёвый агент, которому дают рубрику дословно:

> For each issue found in #4, launch a parallel Haiku agent that takes the PR,
> issue description, and list of CLAUDE.md files, and returns a score…
> For issues that were flagged due to CLAUDE.md instructions, the agent should
> double check that the CLAUDE.md actually calls out that issue specifically.

Независимость оценки от автора находки. У остальных трёх ревьюер оценивает
сам себя.

### Расслоение по цене модели — 1 из 4

Команда `code-review` расписывает, кто чем работает: Haiku — проверка
применимости, сбор путей `CLAUDE.md`, пересказ PR, оценка находок; Sonnet —
собственно ревью. Дешёвая модель делает всё, кроме самого ревью.

### Проверка применимости до работы и повторно после — 1 из 4

Команда `code-review`, шаг 1:

> Use a Haiku agent to check if the pull request (a) is closed, (b) is a draft,
> (c) does not need a code review (eg. because it is an automated pull request,
> or is very simple and obviously ok), or (d) already has a code review from
> you from earlier. If so, do not proceed.

И шаг 7 — та же проверка ещё раз, потому что за время ревью состояние могло
измениться. Двойной барьер: до и после.

### Указание, когда роль вызывать — 1 из 4

У `pr-review-toolkit/code-reviewer` поле `description` в шапке огромное и
адресовано не роли, а тому, кто её вызывает, плюс в теле есть раздел
`## When to invoke` с тремя разобранными сценариями. Это описание для
маршрутизатора, а не инструкция исполнителю.

### Точный формат ссылки на код — 1 из 4

Команда `code-review` посвящает этому семь строк: полный sha, знак `#` после
имени файла, диапазон `L[start]-L[end]`, минимум одна строка контекста сверху
и снизу, и предупреждение, что `$(git rev-parse HEAD)` в ссылке не сработает,
потому что комментарий рендерится как Markdown.

### Обратная связь на само ревью — 1 из 4

Команда `code-review` завершает комментарий строкой с просьбой поставить 👍
или 👎. Механизм сбора качества самой роли.

## Чего сознательно не кладут

- **Сборку и типизацию.** Явный запрет у одного, умолчание у остальных.
- **Общих претензий к покрытию тестами.** Kandev: «General "add more tests"
  without specifying what logic is untested».
- **Эмодзи** — команда `code-review`: «Avoid emojis» (при этом сама ставит
  один в подпись).
- **Находок на нетронутых строках** — у всех четырёх.

## Формат вывода

Сходятся на трёх вещах: `file:line`, почему это важно, как исправить. Различия:

- Kandev — разделы по серьёзности, вердикт строкой из закрытого списка.
- `feature-dev` — группировка Critical/Important, оценка уверенности
  указывается в самой находке.
- команда `code-review` — нумерованный список с ссылками на GitHub с полным
  sha, отдельный шаблон для «ничего не найдено».

## Условие завершения

- Kandev — выдал разделы и вердикт.
- `feature-dev`, `pr-review-toolkit` — вернул список находок вызывающему.
- команда `code-review` — оставил комментарий на PR через `gh`, но только если
  после фильтра по 80 что-то осталось; иначе не публикует ничего.

Последнее для нас существенно: «нет находок» и «не публиковать» — разные
состояния, и они разведены.

## Расхождения и спорное

1. **Один ревьюер или шесть.** Два источника из четырёх дробят ревью на узкие
   объективы. У нас одна колонка. Дробление даёт покрытие, которого одним
   промптом не добиться (история строки, прошлые PR, комментарии в коде), но в
   Kandev каждый объектив — это отдельный шаг цепочки, то есть отдельная
   колонка и отдельный сброс контекста. Шесть колонок ревью в маршруте Quick
   выглядят абсурдно.

   Возможный выход, которого в источниках нет: один шаг, но внутри него
   `spawn_session_kandev` или родной механизм подагентов хоста. Тогда объективы
   остаются, а колонка одна. Это надо проверять: `kandev-context.md` прямо
   ограничивает делегирование — «use your host agent's native subagent
   mechanism only when the user has explicitly authorized delegation».

2. **Кто ставит оценку уверенности.** Три источника — сам ревьюер, один —
   отдельный агент. Самооценка дешевле и явно работает достаточно хорошо,
   раз так сделано у большинства. Но независимая оценка — единственный
   способ поймать ревьюера, который убедил сам себя.

3. **Читать контекст или только диф.** Kandev требует читать изменённые файлы
   целиком и ходить по вызывающим. Объектив #2 у команды `code-review`
   запрещает выходить за диф. Это не противоречие, а разные объективы, но при
   одной колонке выбрать придётся.

4. **Кто определяет базу дифа.** Kandev расписывает `merge-base` внутри
   промпта ревью. У нас есть отдельная встроенная роль `merge-base.md` для
   слияния базовой ветки — но это про слияние, не про базу для дифа. Для
   ревью базу придётся определять внутри роли.

## Выводы для нас

**Берём:**

- Шкалу уверенности 0–100 с якорями и порогом 80. Именно с якорями:
  формулировки `feature-dev` можно переносить почти дословно.
- Список «не находка» — сводный из всех четырёх, они почти совпадают.
- Разграничение с CI: не запускать сборку и типизацию, это не работа ревью.
- Разведение «где искать» и «о чём докладывать»: контекст брать из всего
  проекта, находки — только на изменённых строках.
- Определение базы дифа через `merge-base`, с предупреждением не диффить
  против `origin/main` напрямую.
- Разные состояния «ничего не найдено» и «нечего публиковать».
- Оговорку про `CLAUDE.md`: это инструкции для пишущего, не все применимы при
  ревью.

**Не берём:**

- Формат ссылок на GitHub с полным sha — у нас находки идут в
  `publish_review_findings_kandev`, а не в комментарий PR.
- Просьбу поставить 👍 — у нас нет такого канала.

**Открытый вопрос, который надо решить:**

Три объектива из пяти у команды `code-review` — история строки, замечания на
прошлых PR по тем же файлам, указания в комментариях кода — у нас не покрыты.
Либо они входят в единый промпт `Code Review` и делают его большим, либо роль
внутри шага делегирует их подагентам, что упирается в ограничение
`kandev-context.md` на делегирование. Решать надо до написания промпта, потому
что от этого зависит его размер и структура.

**Чего в источниках нет, а нам нужно:**

1. Вызов `publish_review_findings_kandev` вместо возврата списка вызывающему.
   Ни один источник не пишет находки в платформу — все возвращают их агенту
   или постят в PR.
2. Условие вызова `step_complete_kandev` при нулевых находках. Это же место,
   где потом появится прыжок через пустые `Review Fixes` и
   `Final Verification`.
