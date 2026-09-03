# Draft PR

## Наш замысел

Предпоследний шаг во всех трёх маршрутах, сразу после `Final Verification`.
Собирает и открывает draft pull request по уже закоммиченным и запушенным
изменениям. Дальше — человеческий гейт `Human Review`
(`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md:17-18`).

Отдельно от самого создания PR: нативный CI/MR auto-fix в Kandev — это не шаг
цепочки, а переключатель на самой задаче. Включить его должна именно роль
`Draft PR`, через `update_task_pr_automation_kandev` (GitHub) или
`update_task_mr_automation_kandev` (GitLab), после того как PR создан и связан
с задачей:

> После `Final Verification` создаётся draft PR. Нативный PR/MR auto-fix не
> является шагом цепочки: это переключатель на самой задаче, и включить его
> должна роль `Draft PR` через `update_task_pr_automation_kandev`.
> (`DEVELOPMENT-ROUTES.md:96-98`)

> `custom-ci-fixup` не является линейным шагом workflow: это заготовка для
> будущего override встроенного PR/MR auto-fix. Роль `Draft PR` должна будет
> включить provider automation через `update_task_pr_automation_kandev` или
> `update_task_mr_automation_kandev` после создания и связывания change
> request. (`DEVELOPMENT-ROUTES.md:243-244`)

Артефакт роли — `.kandev/artifacts/<TASK_ID>/pull-request.md`
(`DEVELOPMENT-ROUTES.md:143`), имя файла совпадает с выходным файлом этого
исследования.

## Найденные аналоги

| Инструмент | Как называется роль | Где лежит |
|---|---|---|
| Kandev, встроенный prompt | `open-pr` (генерик PR-creation prompt) | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/open-pr.md` |
| Kandev, шаблон Kanban `Feature Dev` | шаг `PR` (позиция 5 из 7) | `/tmp/kandev-v0.93.0/apps/backend/config/workflows/feature-dev.yml:256-291` |
| Kandev, шаблон Kanban `PR Review` | последний штрих шага `code-review` — не создаёт PR, но включает автоматизацию тем же инструментом | `/tmp/kandev-v0.93.0/apps/backend/config/workflows/pr-review.yml:143-153` |
| Kandev, сам репозиторий (dogfooding) | Claude Code skill `pr` | `/tmp/kandev-v0.93.0/.agents/skills/pr/SKILL.md` |
| Kandev, сам репозиторий | сам PR-шаблон, на который ссылается skill `pr` | `/tmp/kandev-v0.93.0/.github/pull_request_template.md` |
| kit-lite | подагент `pr` — «сборка описания PR» | `/home/dev/projects/kit-lite/roles/pr.md` |
| Anthropic `commit-commands` | команда `/commit-push-pr` | `plugins/commit-commands/commands/commit-push-pr.md` |
| Anthropic `code-review` | не создаёт PR, но задаёт формат комментария к нему — соседняя роль | `plugins/code-review/commands/code-review.md:50-86` |
| BMAD-METHOD (веб, пересказ поисковика) | PR description template | github.com/bmad-code-org/BMAD-METHOD — текст не читан дословно, см. раздел «Расхождения» |
| Qodo/CodiumAI PR-Agent (веб, пересказ поисковика) | команда «Auto Description» | упоминается в нескольких вторичных статьях, первоисточник не читан |
| GitHub Blog (прочитано через WebFetch) | редакционная статья о ревью агентских PR | https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/ |

Отдельно: `changes-walkthrough.md` (`/tmp/kandev-v0.93.0/apps/backend/config/prompts/changes-walkthrough.md`)
оказался **не аналогом Draft PR**, а независимым действием. Это встроенный
prompt, который UI шлёт активной сессии по кнопке **Walkthrough** в панелях
Changes или Review, а не часть потока создания PR:

> Select **Walkthrough** from Changes or Review. Kandev sends the built-in
> `changes-walkthrough` prompt to the active session. […] The agent must have
> task MCP and must call `show_walkthrough_kandev` with an ordered list of
> file and line anchors.
> (`/tmp/kandev-v0.93.0/docs/public/sessions-and-review.md:227`)

Он относится к любой сессии задачи (в том числе к `Human Review`), не только к
шагу создания PR. Инструмент `show_walkthrough_kandev` и его требования к
форме вызова (`steps[]`, обязательные `file`/`line`/`text`, `ELI5:` в первом
шаге, запрет `Justification:` преамбулы) разобраны построчно, но это
инструмент соседней задачи — «объяснить диф построчно», а не «описать PR
целиком». Ближайшее место для него в наших маршрутах — не `Draft PR`, а
`Human Review` или сама панель Changes.

## Что кладут всегда

### Проверка на PR-шаблон репозитория первым делом — 4 из 4 (Kandev × 2, оба skill, kit-lite косвенно)

Everywhere the check for `.github/pull_request_template.md` /
`.github/PULL_REQUEST_TEMPLATE.md` идёт раньше генерации описания, а не после:

> **Check for PR template:**
> - Look for a PR template in .github/pull_request_template.md or
>   .github/PULL_REQUEST_TEMPLATE.md
> - If a template exists, use it as the structure for the PR description
> - If no template exists, use the default format below
> (`open-pr.md:9-12`)

`feature-dev.yml` добавляет третий путь-кандидат (`docs/pull_request_template.md`)
и явно требует прочитать шаблон целиком перед заполнением
(`feature-dev.yml:263-267`). Skill `pr` идёт дальше всех — делает наличие
шаблона обязательным условием, а не опцией:

> **PR body** must be built from `.github/pull_request_template.md`; fail fast
> if it is missing. Read the whole template before writing the body.
> (`.agents/skills/pr/SKILL.md:88-89`)

kit-lite не заглядывает в репозиторий вообще (см. «Расхождения»), но его
собственный шаблон описания — фиксированный набор секций — тот же принцип на
уровне самого инструмента: структура задана заранее, а не придумывается на
ходу (`kit-lite/roles/pr.md:39-65`).

### Заголовок — Conventional Commits, отдельно от тела — 3 из 4

`open-pr.md:16` даёт точную форму:

> **Title:** Conventional Commit summary (`type: description` or
> `type(scope): description`), 50-72 characters. Types: feat, fix, docs,
> refactor, perf, chore, ci, test

`feature-dev.yml:283-286` требует того же, но мягче — «if the repo uses it», и
не называет диапазон длины. Skill `pr` — жёстче всех: заголовок обязателен
Conventional Commits и объясняет, зачем именно это (не просто стиль):

> **PR title** must follow Conventional Commits format (see `/commit` for
> full rules). CI validates via `pr-title.yml` — the PR title becomes the
> squash-merge commit used for release notes.
> (`.agents/skills/pr/SKILL.md:86`)

Диапазон длины (50-72 символа) встречается только у `open-pr.md`; больше
нигде цифр нет.

### Draft создаётся отдельным явным флагом, не догадкой — 3 из 4

`feature-dev.yml:283` не оставляет выбора — весь шаг называется «Create a
draft pull request», и команда содержит `--draft` буквально:

> STEP 3: CREATE DRAFT PR
> ```bash
> gh pr create --draft --title "<type>: <description>" --body "<body …>"
> ```

Skill `pr` делает выбор параметром вызывающего, а не догадкой агента — см.
подробнее в «Формат вывода» и «Расхождения».

### Отчёт с URL PR в конце — 4 из 4

Каждый источник, который вообще создаёт PR, завершается тем же самым шагом —
вернуть ссылку. `open-pr.md:43-46` формулирует это как отдельный пункт
«Verify», `feature-dev.yml:290` — «STEP 4: REPORT. Return the PR URL.»,
`commit-push-pr.md` создаёт PR последним шагом в batch tool calls (сам URL
возвращает `gh pr create` в stdout), skill `pr` — «Report the PR URL after all
applicable steps are complete» (`.agents/skills/pr/SKILL.md:225-226`).

### Не выдумывать footer-атрибуцию инструмента — 2 явных запрета из тех, что вообще упоминают тему

Реальный PR-шаблон самого Kandev это формулирует как жёсткое RULE:

> - Do not add "🤖 Generated with..." or any tool attribution footer.
> (`.github/pull_request_template.md:42`)

Skill `pr` повторяет то же самое дословно как отдельный пункт при построении
тела (`.agents/skills/pr/SKILL.md:95`). Заметьте контраст с плагином
`code-review` — см. «Расхождения».

## Что кладут иногда

### Явный gate на право открывать крупный/архитектурный PR — 1 из источников, но детально

Только skill `pr` и его собственный шаблон проверяют права автора перед
созданием PR и требуют для внешних контрибьюторов сначала обсуждение в issue:

> **Architecture and scope gate:** Before running any PR creation command,
> verify the authenticated actor's repository permission. […] For an actor
> without write access, require a linked issue with maintainer discussion
> before opening a large or architectural PR. […] Do not open a PR to start
> the discussion.
> (`.agents/skills/pr/SKILL.md:74-84`, дублируется в
> `.github/pull_request_template.md:17-22`)

Для нас это не применимо буквально (Kandev-агент обычно и есть автор с write
доступом), но принцип — «крупная архитектурная правка требует
предварительного обсуждения, не PR как черновика для дискуссии» — стоит
держать в уме отдельно от формата описания.

### Многохостовость (GitHub / GitLab / Azure Repos) — только skill `pr`

Skill `pr` явно детектирует хост по `git remote get-url origin` и ветвится на
три разных потока создания PR/MR (`.agents/skills/pr/SKILL.md:14-22`,
GitLab-ветка — строки 268-353, Azure-ветка — строки 228-267). Kandev-продуктовые
prompts (`open-pr.md`) написаны только под `gh`, GitLab-путь у Kandev идёт не
через отдельный prompt-текст, а через тот же generic `open-pr.md` плюс
provider-specific MCP-инструменты выбора (`get_task_mr_automation_kandev` и
т.п.), что подтверждается таблицей provider-scoped tools
(`/tmp/kandev-v0.93.0/docs/public/automation-and-mcp.md:530-533`).

### Скриншоты для UI-изменений — 2 из 4 (open-pr.md как опциональная секция, skill `pr` как обязательный процесс)

`open-pr.md:21` просто перечисляет секцию «Screenshots/Examples: If applicable
(for UI changes)». Skill `pr` разворачивает это в отдельный многошаговый
процесс — захват, валидация на секреты/PII, сжатие `pngquant`, publish через
orphan-commit (GitHub) с SHA-pinned raw URL, потому что «GitHub has no public
API to upload images into a PR body» (`.agents/skills/pr/SKILL.md:60-172`).
Это самая длинная часть skill `pr` — явно specific к их репозиторию
(`apps/web/`), не общий паттерн.

### Сохранение уже существующего тела PR при повторном обновлении — только skill `pr`

Отдельная процедура fetch-merge-verify перед любым PATCH тела, потому что
«The PR body is a shared, mutable document. Preview automation and other bots
may add sections after the PR is created» (`.agents/skills/pr/SKILL.md:191-219`).
Актуально только для роли, которая редактирует уже созданный PR (наш
`ci-auto-fix`/`mr-auto-fix`, не `Draft PR` при первом создании), но полезная
подсказка на будущее для `custom-ci-fixup`.

### AI-сгенерированный «Auto Description» как отдельная команда — веб, вторично

По пересказу нескольких вторичных статей у Qodo/CodiumAI PR-Agent описание,
заголовок, тип и walkthrough собираются одной автоматической командой поверх
диффа PR — то есть в чужом инструменте «описание» и «построчный walkthrough»
объединены в одну функцию, тогда как у Kandev это два разных prompt-файла
(`open-pr.md` и `changes-walkthrough.md`, см. «Найденные аналоги»). Не читал
первоисточник Qodo напрямую — только summary поисковика, поэтому не
формулирую это как подтверждённый паттерн, а как повод свериться при
проектировании: возможно, `Draft PR` стоит вызывать walkthrough сама, а не
оставлять его только `Human Review`.

## Чего сознательно не кладут

- **Похвалу себе / маркетинговый тон.** Явного текста «не хвали себя» нигде не
  нашёл. Ближе всего — требование `.github/pull_request_template.md:9`:
  «Say WHY, not what. No filler phrases ("This PR...", "In order to...", "As
  part of...")» — это запрет на воду и самоочевидные фразы, а не прямой запрет
  на самопохвалу, но эффект тот же: описание не должно быть автопрезентацией
  результата.
- **Придуманное тестирование.** Прямого текста вида «не пиши про тесты,
  которых не было» ни в одном локальном источнике нет. Косвенно то же самое
  делает секция `VALIDATION (required)` реального шаблона: «How this was
  tested or verified. List commands or checks run» — требует конкретных
  команд, а не общей фразы «all tests passing», которую предлагает default
  формат самого `open-pr.md:29` («Testing checklist … all tests passing»).
  Это расхождение внутри одного источника, см. «Расхождения». Внешне то же
  подтверждает вторичный академический источник о рассинхроне текста PR и
  кода у AI-агентов (не читан целиком, только abstract-уровень через поиск):
  arxiv.org/html/2601.04886 — «AI-generated descriptions are not always
  faithful to the underlying code».
- **Плейсхолдеры и незаполненные секции в финальном тексте.** Явный запрет
  дважды: `.github/pull_request_template.md:43` («Do not leave placeholder
  text or unfilled sections») и skill `pr`: «Before creating the PR,
  self-check that the final body has no `<!--`, no empty required sections,
  and no placeholder text» (`.agents/skills/pr/SKILL.md:96`).
- **Ручной сбор чек-листа с нуля.** Реальный шаблон требует сохранять готовый
  чек-лист как есть, не переизобретать и не преотмечать: «Always keep the
  Checklist section as-is; do not remove or pre-fill its items»
  (`.github/pull_request_template.md:45`, повтор в
  `.agents/skills/pr/SKILL.md:91`).
- **Сборку/CI как часть проверки роли.** Явного текста в PR-источниках нет
  (это паттерн из соседней роли `Code Review`, не переносится буквально), но
  логика та же: `VALIDATION` требует перечислить, что запускалось, не
  запустить это внутри самой роли создания PR.

## Формат вывода

Три разных уровня строгости:

- **`open-pr.md` (generic Kandev prompt).** Восемь секций, если шаблона нет:
  Overview, Changes, Motivation, Testing (checklist), Screenshots/Examples
  (если применимо), Breaking Changes (если применимо), Related Issues.
  Заголовок отдельно нормирован (Conventional Commits, 50-72 символа).
  Финал — подтверждение создания, URL, краткое summary (`open-pr.md:14-46`).
- **`feature-dev.yml` PR-шаг.** Короче: если шаблона нет — «summary of what
  was built and why, validation steps, and a checklist»
  (`feature-dev.yml:288-289`), без деления на Motivation/Breaking
  Changes/Related Issues отдельными секциями.
- **Реальный `.github/pull_request_template.md` + skill `pr`.** Самый жёсткий:
  Summary без заголовка (1-2 предложения, WHY не WHAT), опциональные Important
  Changes / Diagram / Possible Improvements только при значимости изменения,
  обязательный Validation с конкретными командами, Related Issues только при
  реальном номере issue, чек-лист сохранён неизменным
  (`.github/pull_request_template.md:1-73`).
- **kit-lite.** Формат вообще не читает шаблон репозитория — собирает
  фиксированный набор секций из артефактов других ролей (Цель, Что одобрено,
  Допущения — дословно каждая строка `assumptions.md`, Чем проверено со
  свёрнутым выводом тестов, Ревью, Ресёрч, Roadmap), с жёстким лимитом «не
  больше 80 строк без свёрнутого блока» (`kit-lite/roles/pr.md:31-65`).

Длина явно нормирована только у двух источников: `open-pr.md` — 50-72 символа
для заголовка; kit-lite — 80 строк для тела. Никто не задаёт длину тела для
generic Kandev prompt или skill `pr` — там граница задаётся содержанием
шаблона, а не числом.

## Условие завершения

- `open-pr.md` — самый явный: «**Verify:** Confirm the PR was created
  successfully / Provide the PR URL / Summarize the PR details»
  (`open-pr.md:43-46`). Условие завершения — успешный `gh pr create` плюс
  собственная проверка результата, а не просто факт вызова команды.
- `feature-dev.yml` — STEP 4 «Return the PR URL», без отдельной верификации
  (`feature-dev.yml:290`).
- Skill `pr` — самое строгое условие: PR не считается готовым, пока не
  выполнен self-check тела на отсутствие HTML-комментариев, пустых
  обязательных секций и плейсхолдеров, и — для UI-изменений — пока не
  подтверждена публикация скриншотов отдельным шагом 7
  (`.agents/skills/pr/SKILL.md:96, 225-226`).
- kit-lite — «все строки `assumptions.md` перенесены; вывод тестов вложен;
  замечания ревью перечислены» (`kit-lite/roles/pr.md:27`), то есть условие
  завершения — не «PR создан», а «ничего не потеряно при переносе».

Для нашей роли актуальны оба слоя: платформенный (`step_complete_kandev`
обязателен, иначе задача не продвинется — `DEVELOPMENT-ROUTES.md`, бриф) и
содержательный (какой из этих чек-листов условия завершения брать за основу
перед вызовом `step_complete_kandev`).

## Расхождения и спорное

1. **Footer-атрибуция инструмента.** Реальный шаблон Kandev и его собственный
   skill `pr` явно запрещают «🤖 Generated with…» (`.github/pull_request_template.md:42`,
   `.agents/skills/pr/SKILL.md:95`). А официальный плагин `code-review` этот
   же footer требует в комментарии к ревью того же самого PR:
   `🤖 Generated with [Claude Code](https://claude.ai/code)`
   (`plugins/code-review/commands/code-review.md:70,84`). Это разные
   артефакты (тело PR vs комментарий ревью), так что прямого противоречия
   нет, но подтверждает, что «footer или нет» — решение, которое разными
   частями одного экосистемного семейства принято по-разному, и его надо
   зафиксировать явно, а не полагаться на умолчание модели.

2. **Draft или ready — кто решает.** `feature-dev.yml` решает за агента
   безусловно: шаг называется «PR», описание — «Create a draft pull request»,
   команда содержит `--draft` без альтернативы (`feature-dev.yml:256-283`).
   `open-pr.md` вообще не упоминает draft ни разу — ни как флаг, ни как
   решение. Skill `pr` делает это явным пользовательским выбором:
   «`--draft` — create the PR as draft and skip the fixup step. […] Default
   (no flag) — create as ready-for-review» (`.agents/skills/pr/SKILL.md:29-37`).
   Для нас вопрос решён на уровне маршрута («Draft PR» — само имя колонки), но
   стоит явно закрепить в промпте `--draft`, а не полагаться на то, что модель
   выберет то же, что подразумевает название шага.

3. **Testing-секция: честная или для галочки.** Default-формат самого
   `open-pr.md:29` предлагает чек-лист «unit tests, integration tests, manual
   testing, all tests passing» — по формулировке это ближе к чек-боксам,
   которые легко проставить не глядя. Реальный шаблон Kandev требует
   перечислить *команды*, которые реально запускались (`.github/pull_request_template.md:28-29`).
   Это прямое расхождение внутри самого корпуса Kandev между generic prompt
   и практикой собственного репозитория — второе строже и ближе к тому, что
   нужно нам, раз `Verification`/`Final Verification` и так оставляют лог
   команд в артефактах.

4. **Нужен ли шаблон обязательно, или можно жить без него.** `open-pr.md` и
   `feature-dev.yml` трактуют отсутствие шаблона как нормальный случай — есть
   заранее прописанный default-формат. Skill `pr`: «fail fast if it is
   missing» (`.agents/skills/pr/SKILL.md:88`) — то есть отсутствие шаблона
   репозитория для skill `pr` является блокером, а не поводом использовать
   запасной вариант. У нас в репозитории `vps-dev` `.github/pull_request_template.md`
   пока нет ни одного, так что жёсткий вариант skill `pr` немедленно
   заблокирует роль — вопрос к решению при написании промпта.

5. **Как включается automation-переключатель — где это реально описано.**
   Ни один prompt-текст, посвящённый именно `open-pr`/PR-созданию, не
   упоминает `update_task_pr_automation_kandev` вообще. Единственное место в
   корпусе, где вызов этого инструмента реально прописан текстом, — конец
   шага `code-review` в шаблоне `PR Review` (`pr-review.yml:143-153`), и там
   включаются только три lifecycle-булевых (`prompt_on_review_requested`,
   `prompt_on_merged`, `prompt_on_closed`), не `auto_fix_enabled`:

   > Enable all three task-bound lifecycle notifications on whichever
   > provider this task's linked review target is on:
   > - GitHub pull request: use update_task_pr_automation_kandev
   > - GitLab merge request: use update_task_mr_automation_kandev
   > In both cases set:
   > - prompt_on_review_requested: true
   > - prompt_on_merged: true
   > - prompt_on_closed: true
   > (`pr-review.yml:146-152`)

   Но наш замысел (`DEVELOPMENT-ROUTES.md:96-98`) говорит именно про «нативный
   CI auto-fix» — то есть `auto_fix_enabled`, отдельное поле того же
   инструмента (`server.go:1268`: `mcp.WithBoolean("auto_fix_enabled", …)`).
   Ни один локальный источник не показывает пример именно этого вызова с
   `auto_fix_enabled: true`. Это разрыв между «что мы решили делать» и «что
   где-то в корпусе реально написано текстом» — при написании промпта
   `Draft PR` придётся составлять вызов по спецификации инструмента, а не по
   готовому примеру.

## Выводы для нас

**Берём:**

- Порядок действий из `open-pr.md`/`feature-dev.yml`: сначала проверка
  `.github/pull_request_template.md` (и вариантов пути), затем заполнение по
  шаблону или по default-формату, затем `gh pr create --draft`, затем
  верификация и возврат URL.
- Conventional Commits для заголовка — самый частый и наиболее
  специфицированный паттерн (3 из 4 локальных источников), диапазон длины
  50-72 символа из `open-pr.md`, если решим его закреплять численно.
- Запрет на footer-атрибуцию инструмента и на плейсхолдеры/пустые
  обязательные секции — оба подтверждены дважды в собственном репозитории
  Kandev (шаблон + skill), это не чужая практика, а то, как сам Kandev пишет
  PR себе.
- Требование `Validation`/`Testing` как список реально выполненных команд, а
  не чек-бокс «all tests passing» — сильнее защищает от придуманного
  тестирования, и у нас для этого уже есть готовый источник данных:
  `verification.md`/`final-verification.md` в artifact protocol.
- GIT SAFETY-блок из `feature-dev.yml` (запрет `git checkout -- .`,
  `git reset --hard`, `git clean -fd`, `git stash --include-untracked`;
  восстанавливать только явные пути) — прямая защита от порчи чужой
  незакоммиченной работы, применимо к любому шагу, который трогает git, не
  только к PR.
- Явную формулировку вызова automation-инструмента по окончании — в духе
  примера из `pr-review.yml`, но с `auto_fix_enabled: true` вместо трёх
  lifecycle-булевых (или вместе с ними, если решим, что `Draft PR` тоже
  должна подписаться на уведомления, а не только на auto-fix).

**Не берём:**

- Многочасовой процесс скриншотов (захват, `pngquant`, orphan-commit,
  SHA-pinned raw URL) — специфичен для конкретного репозитория Kandev
  (`apps/web/`) и его E2E-инфраструктуры, не общий паттерн ни у одного
  другого источника.
- Fetch-merge-verify процедуру сохранения тела PR при обновлении — она про
  редактирование уже существующего PR ботами/CI-превью, это ближе к будущему
  `custom-ci-fixup`, чем к первому созданию PR в `Draft PR`.
- Multi-host ветвление (GitHub/GitLab/Azure) как единый большой промпт — у
  Kandev это уже решено на уровне платформы через provider-scoped MCP tools
  (`get_task_pr_automation_kandev` vs `get_task_mr_automation_kandev`), роли
  не нужно самой детектировать хост по `git remote`.
- Жёсткий `fail fast`, если шаблона репозитория нет — у нас `.github/pull_request_template.md`
  в `vps-dev` пока не существует, и блокировать весь маршрут по этой причине
  преждевременно; лучше поведение `open-pr.md`/`feature-dev.yml` — использовать
  запасной формат.

**Чего в источниках нет, а нам нужно:**

1. Явного примера вызова `update_task_pr_automation_kandev` с
   `auto_fix_enabled: true` именно из роли, создающей PR, а не ревьюящей его —
   такого текста не существует нигде в прочитанном корпусе (см. «Расхождения»,
   п.5). Придётся написать по спецификации инструмента
   (`server.go:1264-1280`), а не по образцу.
2. Чтения `pull-request.md` как выходного артефакта в общем artifact protocol
   и связи с `README.md`-манифестом задачи — ни один внешний источник не
   работает в модели «шаг с холодным контекстом читает файлы
   предшественников»: все они пишут PR в рамках одной непрерывной сессии,
   которая помнит собственную работу. Наш `Draft PR` получает свежий
   контекст и должен реконструировать «что делали» из
   `final-verification.md`, `code-review.md`, `security-review.md` и
   остальных файлов каталога, а не из истории диалога — этот шаг ближе к
   методу kit-lite («собери из артефактов, не смотри код»), чем к
   Kandev-нативному `open-pr.md`, который явно читает git-историю коммитов
   (`open-pr.md:4-7`) в предположении, что она полностью самодостаточна.
3. Явного решения — переносить ли допущения/риски из `review-fixes.md` и
   `security-review.md` в тело PR дословно, как это жёстко требует kit-lite
   для `assumptions.md` (kit-lite/roles/pr.md:9), или суммировать. Ни один
   источник, кроме kit-lite, вообще не формулирует такое правило, потому что
   ни у кого больше нет отдельного файла допущений как part of artifact
   protocol.
