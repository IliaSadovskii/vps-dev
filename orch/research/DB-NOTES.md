# База оркестратора: что взято у Kandev и Fusion

Смотрено 2026-09-06: Kandev — живая база `/var/lib/kandev/data/kandev.db`
(SQLite, 182 таблицы), Fusion — `packages/core/src/postgres/schema/project.ts`
(PostgreSQL, drizzle) и `docs/workflow-steps.md`.

## Что берём

| Идея | Откуда | Как у нас |
|---|---|---|
| Журнал переходов отдельной таблицей: откуда, куда, кто (человек / агент / движок), чем вызван, из какой сессии | Kandev `task_step_transitions` | таблица `move` |
| Каждый вход в шаг — своя строка с порядковым номером, а не счётчик на задаче | Kandev `workflow_step_entries` | таблица `run`; `max_runs` = `COUNT(run)`, счётчиков нет |
| Замороженная копия цепочки на задачу | Fusion `workflowIrPin`, Kandev `agent_profile_snapshot` | `task.chain_yaml`, зеркало в `.orch/<task>/chain.yml` |
| Коммит на начало захода | Fusion `workflow_run_step_instances.baselineSha` | `run.start_sha`, `run.end_sha`: «что изменилось после твоего прошлого захода» считается `git diff`, а не по памяти |
| Отпечаток артефакта в момент решения | Fusion: fingerprint плана при одобрении | `move.artifact_sha`: видно, менял ли шаг файл на втором заходе; неизменённый файл на возврате — повод покраснеть |
| Решения не удаляются, а перекрываются | Kandev `workflow_step_decisions.superseded_at` | все таблицы append-only, кроме `task` |
| Ревизия задачи для интерфейса | Kandev `task_status_summaries.revision`, `route_generation` | `task.revision`, кнопки несут ревизию |
| Итоговый вердикт роли — структурированная последняя строка, одна повторная просьба «только вердикт», потом `malformed` | Fusion «Prompt-mode Structured Verdict Contract» | у нас `orch done`; тот же приём — запасной канал для режима «только чтение» и поведение «продолжай и подай сигнал» один раз |

## Чего не берём, и почему

- **Счётчики на строке задачи.** У Fusion в `tasks`: `resumeLimboCount`,
  `mergeConflictBounceCount`, `taskDoneRetryCount`, ещё десяток. Каждый
  новый сбой добавлял колонку. У нас всё считается из `run` и `move`.
- **Шина событий с потребителями, курсорами, dead-letter**
  (Fusion `task_lifecycle_*`, 5 таблиц). Потребитель у нас один и он же
  писатель; интерфейс читает состояние, не события.
- **Документы с ревизиями в базе** (Kandev `task_documents`,
  `task_document_revisions`). Артефакты — файлы; история изменений видна в
  транскрипте сессии (карточки правок). Дешёвая страховка: при каждом
  движении копия артефактов в `.orch/<task>/history/<run>/`.
- **Структурированные находки ревью** (`task_review_findings`: файл,
  строка, серьёзность). Находки — раздел артефакта; панель ревью не строим.
- **Очереди и WIP** (`queued_for_step_id`, `wip_admitted`) — не в первой
  версии.
- **Стоимость по ходам** (`task_usage_events`) — позже, из событий AoE.

## Схема

```sql
task   id, chain, chain_yaml, title, text, project_path, branch,
       worktree_path, group_path, status, human_sheet, revision,
       created_at, closed_at, archived_at
       -- status: backlog | queued | running | waiting | done | abandoned
       -- human_sheet: JSON лист автономии {step: {after, ask}}
run    id, task_id, step, n, session_id, context, started_at,
       prompt_sent_at, prompt_sha, ended_at, outcome, start_sha, end_sha,
       duration_s, cost_usd
       -- «почему ждёт» выводится: ended_at без outcome = нет сигнала
move   id, task_id, from_step, to_step, actor, trigger, comment,
       artifact_sha, revision, at
       -- actor: agent | human | engine
       -- trigger: outcome:<x> | button | auto | no_signal | max_runs | error
event  seq, task_id, kind, payload, at
```

Четыре таблицы, одна изменяемая (`task`), три только на дозапись. Единый
писатель — движок. Команда `orch` в сессиях базу не открывает; заявки на новую
задачу от ролей (`orch task new`) — файлы в `~/.local/share/orch/inbox/`,
которые движок превращает в строки `task` на следующем проходе.

## Правила

1. Нет счётчиков: всё, что можно посчитать, считается.
2. Нет производных статусов в базе: «почему ждёт» выводится на каждом
   проходе из `run`, файлов и статуса AoE.
3. Любое изменение — транзакция с инкрементом `task.revision`.
4. Схема версионируется одной строкой `PRAGMA user_version`; миграции —
   пронумерованные SQL-файлы, применяются на старте.
5. База — истина о потоке; папка задачи — истина о содержании; между
   ними только пути и отпечатки.
