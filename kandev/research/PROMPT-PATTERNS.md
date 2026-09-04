# Анализ ролевых промптов: что кладут другие

## Кратко

Разобрано 16 наших ролей против встроенных промптов и цепочек Kandev, семи
плагинов Anthropic, KitLight и полутора десятков сторонних инструментов.

**Модель жизнеспособна.** Состав ролей выдержал сверку: у каждой нашей роли
есть работающий аналог, а порядок шагов нигде не противоречит чужой практике.
Три места, где мы устроены лучше типичного: гейт по явному сигналу завершения,
свежий контекст у ревью-ролей, и артефакты как файлы вместо пересказа.

**Что чинить до написания промптов — три вещи:**

1. ~~Проверить, доезжает ли workflow-level prompt после
   `reset_agent_context`.~~ **Проверено: доезжает.** `buildWorkflowPrompt`
   собирает промпт заново при каждом запуске агента и всегда подставляет блок
   уровня цепочки. Общий контракт можно держать в одном месте.
2. Добавить блок про безопасное обращение с git. У Kandev он повторён дословно
   в каждом рабочем шаге и запрещает команды, стирающие незакоммиченную работу.
   У нас агент запускает команды на шести шагах из семнадцати, блока нет.
3. Добавить в `Verification` проверку «подключено ли». Код, который написан,
   покрыт тестами и никуда не подключён, проходит все наши проверки насквозь.

**Что решать вам — четыре развилки:** число вариантов у `Solution Synthesis`
перед человеческим гейтом; объективы `Code Review`; граница между `Code Review`
и `Security Review`; замыкание ревью-цикла и предел числа кругов.

**Два наших решения не подтвердились чужой практикой** и остаются нашими:
дешёвый гейт применимости у `Security Review` (есть только у KitLight) и
гарантия test-first при общем контексте трёх шагов (все остальные разделяют
контексты или держат запрет скриптом).

Подробности — ниже и в `roles/`. Отдельно про то, как устроены цепочки самих
авторов Kandev — в [KANDEV-BUILTIN-WORKFLOWS.md](KANDEV-BUILTIN-WORKFLOWS.md).

---

Документ собран, чтобы не писать наши 16 ролей с чистого листа. Это не готовые
промпты, а разбор того, как те же самые роли описаны в уже работающих
инструментах: что в них попадает всегда, что иногда, и чего сознательно не пишут.

Разбор по каждой роли — в `roles/<роль>.md`. Здесь сведено общее.

## Инвентарь источников

### Встроенные промпты самого Kandev

Самый релевантный источник: та же платформа, те же MCP-инструменты, те же
ограничения. `/tmp/kandev-v0.93.0/apps/backend/config/prompts/`.

| Файл | Размер | Наш аналог |
|---|---:|---|
| `code-review.md` | 6.0 КБ | Code Review, отчасти Security Review |
| `config-context.md` | 5.5 КБ | — (контекст настройки) |
| `kandev-context.md` | 3.5 КБ | общий контекст всех ролей |
| `office-context.md` | 3.0 КБ | — |
| `merge-base.md` | 2.6 КБ | Code Review (определение базы дифа) |
| `open-pr.md` | 2.3 КБ | Draft PR |
| `mr-auto-fix.md` | 1.9 КБ | Review Fixes (для GitLab) |
| `ci-auto-fix.md` | 1.8 КБ | Review Fixes |
| `changes-walkthrough.md` | 1.6 КБ | Draft PR (разбор изменений) |
| `plan-mode.md` | 1.4 КБ | Planning |
| `default-plan-prefix.md` | 1.3 КБ | Planning |
| `session-handover.md` | 0.4 КБ | artifact protocol |
| `spawned-session.md` | 0.5 КБ | — (подсессии) |
| `*-issue-watch-default.md` | 0.4–0.8 КБ | — (интеграции) |

### Официальный маркетплейс плагинов Anthropic

`~/.claude/plugins/marketplaces/claude-plugins-official/plugins/`.
Роли лежат как `agents/*.md` с YAML-шапкой, скиллы — как `skills/**/SKILL.md`.

| Плагин | Роли | Наш аналог |
|---|---|---|
| `feature-dev` | `code-explorer`, `code-architect`, `code-reviewer` | Discovery, Planning, Code Review |
| `pr-review-toolkit` | `code-reviewer`, `code-simplifier`, `comment-analyzer`, `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer` | Code Review, Review Fixes |
| `claude-security` | `explore`, `scan-inventory`, `scan-loader`, `scan-researcher`, `scan-verifier`, `patch-generator`, `patch-verifier` | Security Review, Targeted Research |
| `code-modernization` | `legacy-analyst`, `architecture-critic`, `business-rules-extractor`, `version-delta-analyst`, `scaffolder`, `test-engineer`, `security-auditor`, `uplift-migrator` | Discovery, Decision Mapping, Test Authoring |
| `code-simplifier` | `code-simplifier` | Review Fixes |
| `project-artifact` | скиллы | artifact protocol |
| `ralph-loop` | команды | циклы и возвраты |

### Прочее

Разбирается агентами по каждой роли: Superpowers, плагины и скиллы Codex,
BMAD-METHOD, CrewAI, AutoGen/AG2, MetaGPT, ChatDev, OpenHands, Aider,
roo-code/SPARC, cline. Источники и ссылки — в файлах по ролям.

## Формат шапки роли

В плагинах Anthropic роль — файл с YAML-шапкой:

```yaml
---
name: code-architect
description: Designs feature architectures by analyzing existing codebase
  patterns and conventions, then providing comprehensive implementation
  blueprints with specific files to create/modify, component designs,
  data flows, and build sequences
tools: Glob, Grep, LS, Read, NotebookRead, WebFetch, TodoWrite, WebSearch
model: sonnet
color: green
---
```

Что здесь важно для нас:

- **`description` — не одна фраза, а перечисление того, что роль выдаёт.**
  Это описание для маршрутизатора, который решает, вызывать роль или нет.
- **`tools` — белый список.** У архитектора нет `Edit` и `Write`: роль,
  которая проектирует, физически не может править код. Это тот самый
  `writes_never` из KitLight, но реализованный конфигурацией, а не текстом.
  В Kandev прямого аналога нет — ближайшее `set_session_mode`.
- **`model`** — есть и в Kandev как `agent_profile` на шаге.

## Общие паттерны, которые повторяются

Ниже то, что видно уже по встроенным промптам Kandev и плагинам Anthropic.
Счёт по источникам уточняется по мере готовности файлов в `roles/`.

### 1. Дешёвая проверка применимости перед работой

Роль сначала решает, есть ли для неё работа, и только потом работает. Явно
описано, что считается «нет работы», и что в этом случае делать.

`ci-auto-fix.md`:

> First classify the new PR feedback as actionable or non-actionable.
> If the new feedback is not actionable, do not modify files, do not commit,
> and do not push. Non-actionable feedback includes summaries, status updates,
> no-finding reports, duplicated or previously addressed comments…

**Важная оговорка, выяснившаяся при разборе `Security Review`.** Я сначала
записал это как подтверждение нашего решения держать `Security Review` во всех
трёх маршрутах: мол, роль дёшева, потому что сначала делает копеечную проверку
применимости. Разбор источников этого не подтверждает.

Гейт применимости у `ci-auto-fix.md` — про обратную связь на PR, а не про
безопасность. Среди самих security-ролей такой гейт есть ровно у одного
источника (KitLight). `claude-security`, `security-auditor.md` и
`awesome-copilot/security-review` всегда сканируют весь заданный им объём;
решение «сканировать или нет» либо принимает пользователь, либо его нет вовсе.

То есть дешёвый гейт применимости — не устоявшаяся практика, а наше проектное
решение. Оно может быть верным, но опереться на чужой опыт здесь не выйдет, и
формулировать гейт придётся самим.

### 2. Запрет на общие советы

Требование ссылаться на конкретные пути и имена из этого проекта, а не выдавать
универсальные рекомендации. Встречается в обоих планировочных промптах Kandev.

`default-plan-prefix.md`:

> Your plan must reference actual file paths, function names, types, and
> patterns from this project — not generic advice.

### 3. Явное отрицательное пространство

Значительная доля текста уходит на то, чего делать НЕ надо. У `code-review.md`
это отдельный раздел `NOT A FINDING (skip these)` из семи пунктов, у
`ci-auto-fix.md` — перечисление неактивных видов обратной связи.

Наблюдение: в этих промптах запреты занимают сопоставимый объём с указаниями.

### 4. Порог уверенности

`code-review.md`:

> Only report findings you're >=80% confident about.

Численный порог, а не «будь осторожен».

### 5. Структурированный вывод с правилом «пустое опускать»

`code-review.md` задаёт разделы `## BLOCKER` и `## SUGGESTION`, формат строки
находки (`file:line - Description. Why it matters. How to fix.`) и требует
опускать пустые разделы. Заканчивается однострочным вердиктом из закрытого
списка:

> End with a verdict: Ready to merge / Ready with suggestions / Blocked — fix blockers first

### 6. Точная форма вызова инструмента

Там, где роль обязана вызвать MCP-инструмент, промпт перечисляет обязательные и
необязательные поля. `changes-walkthrough.md`:

> Required tool shape: `steps` is an ordered array. Every step requires `file`
> (repository-relative path), `line` (positive 1-based integer), and `text`
> (markdown explanation). Optional step fields are `repo`, `title`, `line_end`.

### 7. Явное условие остановки

`plan-mode.md` и `default-plan-prefix.md`: «After saving, STOP and wait for the
user to review». Не «закончи работу», а конкретное действие и конкретное
ожидание. Для нас это место, куда встаёт `step_complete_kandev`.

### 8. Сначала узкая проверка, потом широкая

`ci-auto-fix.md`:

> Run the narrowest relevant verification commands first, then broader checks
> if needed.

Прямо относится к нашим двум `Verification`.

### 9. Сохранение чужой работы

`ci-auto-fix.md`: «Preserve unrelated work and avoid broad refactors».
`plan-mode.md`: «Build on what already exists. Only replace or discard the user
content if it is clearly irrelevant or incorrect».

### 10. Ограничение области действия инструкции

`plan-mode.md` заканчивается строкой:

> This instruction applies to THIS PROMPT ONLY.

Нужно, потому что промпт подмешивается в живую сессию, и без такой оговорки
режим «не реализовывать» протёк бы на следующие шаги. У нас та же архитектура:
промпт шага живёт в сессии, которая продолжается на следующем шаге, если
контекст не сброшен.

## Разбор по ролям

| Роль | Файл | Строк |
|---|---|---:|
| Discovery | [roles/discovery.md](roles/discovery.md) | 237 |
| Scoping | [roles/scoping.md](roles/scoping.md) | 354 |
| Decision Mapping | [roles/decision-mapping.md](roles/decision-mapping.md) | 265 |
| Targeted Research | [roles/targeted-research.md](roles/targeted-research.md) | 343 |
| Solution Synthesis | [roles/solution-synthesis.md](roles/solution-synthesis.md) | 292 |
| Planning | [roles/planning.md](roles/planning.md) | 331 |
| Plan Review | [roles/plan-review.md](roles/plan-review.md) | 285 |
| Test Authoring | [roles/test-authoring.md](roles/test-authoring.md) | 256 |
| Implementation | [roles/implementation.md](roles/implementation.md) | 234 |
| Verification + Final Verification | [roles/verification.md](roles/verification.md) | 307 |
| Code Review | [roles/review-code.md](roles/review-code.md) | 306 |
| Security Review | [roles/security-review.md](roles/security-review.md) | 282 |
| Review Fixes | [roles/review-fixes.md](roles/review-fixes.md) | 281 |
| Draft PR | [roles/pull-request.md](roles/pull-request.md) | 435 |
| Artifact protocol | [roles/artifact-protocol.md](roles/artifact-protocol.md) | 292 |

## Отдельно: встроенные цепочки самого Kandev

Найдены позже разбора ролей и оказались самым весомым источником —
`/tmp/kandev-v0.93.0/apps/backend/config/workflows/`, девять готовых цепочек с
полными промптами шагов. Главное: во флагманской `Feature Dev` из восьми
колонок **нет ни одного автоматического перехода**. Разбор —
[KANDEV-BUILTIN-WORKFLOWS.md](KANDEV-BUILTIN-WORKFLOWS.md).
