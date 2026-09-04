# Возможности Kandev, которые касаются оркестрации

Разобрано по исходникам `kandev v0.93.0` (`/tmp/kandev-v0.93.0`) и родной
документации. Цель — перестать выдумывать своё там, где у платформы есть
готовое, и понять, что из нашей схемы лишнее.

Ссылки на файлы даны от корня репозитория Kandev.

## Одиннадцать триггеров шага

`internal/workflow/models/models.go:136-160`. Мы используем три из
одиннадцати.

| Триггер | Когда срабатывает | Используем |
|---|---|---|
| `on_enter` | вход в колонку | да |
| `on_turn_start` | **пользователь отправил сообщение** | нет |
| `on_turn_complete` | ход агента завершён | да |
| `on_exit` | выход из колонки | да (снятие plan mode) |
| `on_comment` | комментарий к задаче | нет |
| `on_blocker_resolved` | снят блокер | нет |
| `on_children_completed` | завершены все дочерние задачи | нет |
| `on_approval_resolved` | решено одобрение | нет |
| `on_heartbeat` | периодический тик | нет |
| `on_budget_alert` | пересечён порог бюджета | нет |
| `on_agent_error` | агент упал с ошибкой | нет |

Все одиннадцать переносимы через YAML-импорт
(`docs/workflow-import-export.md`, исправлено в issue #1109).

## Действия

`on_enter`: `enable_plan_mode`, `auto_start_agent`, `reset_agent_context`,
`set_session_mode` (config `mode`), `clear_decisions`, `queue_run`,
`queue_run_for_each_participant`, `ensure_participant_seat`,
`run_code_review`.

`on_turn_start` и `on_turn_complete`: `move_to_next`, `move_to_previous`,
`move_to_step` (config `step_position` — **не** `step_id`, позиция
переписывается на импорте), плюс `disable_plan_mode` у второго.

Семь событийных триггеров: `move_to_next`, `move_to_previous`,
`move_to_step`, `auto_start_agent`, `queue_run`, `clear_decisions`,
`queue_run_for_each_participant`.

`move_to_step` даёт прыжок на произвольную колонку статикой — то, что мы
считали доступным только агентским переходом. Условий по содержанию по-прежнему
нет: прыжок безусловен.

`run_code_review` — нативный проход ревью по изменённым файлам, с
`agent_profile_id` в конфиге: **ревьюить может другая модель, чем та, что
писала код**. Профиль переносится по значению
(`internal/workflow/models/export.go:332-391`), то есть в YAML это тоже можно
записать.

## Поля шага

Переносимы: `name`, `position`, `color`, `prompt`, `events`, `is_start_step`,
`show_in_command_panel`, `allow_manual_move`, `auto_archive_after_hours`,
`agent_profile`, `auto_advance_requires_signal`,
`cancel_triggers_turn_complete`, `wip_limit`, `pull_from_step_position`.

**`agent_profile` переносим по значению** — `agent_name` (отображаемое имя),
`model`, `mode`, на уровне цепочки и на уровне шага
(`docs/workflow-import-export.md`, раздел «Agent profiles»). Профиль ищется в
целевом рабочем пространстве по точному совпадению трёх полей; не нашёлся —
шаг создаётся без профиля, молча. Это снимает довод решения 12: модель по
шагам можно задать прямо в YAML, не ломая самодостаточность каталога.

Не переносимы: `stage_type` (подсказка интерфейсу — work/review/approval),
участники шага, записанные решения, данные задачи, история шага.

## Вопрос человеку — механизм платформы

`ask_user_question_kandev` создаёт bundle структурированных вопросов, каждый
с вариантами ответа. Вопросы сохраняются как сообщения `clarification_request`
с общим `pending_id` (`internal/task/models/interactions.go`).

Пока bundle не отвечен, платформа **блокирует переход по `on_turn_complete`**
(`internal/orchestrator/clarification_guard.go`): «A pending clarification is
a platform pause, not a step-completion signal». Карточка физически не уедет.

Пользователь отвечает, пропускает (`User skipped`) или отклоняет. В интерфейсе
состояние — `Awaiting user response`; можно очередить инструкции, пока вопрос
висит. Есть `list_pending_questions_kandev`, чтобы перечислить висящие вопросы
по доске.

Родственные инструменты: `answer_question_kandev`, `ask_parent_question_kandev`
(вопрос родительской задаче).

## Сессия переживает перенос карточки

Сессия привязана к задаче, а не к шагу. При перемещении оркестратор
обрабатывает `on_exit` старого шага и `on_enter` нового **в той же сессии**
(`internal/orchestrator/event_handlers_workflow_moved_test.go`,
`TestHandleTaskMovedWithSession`). Новая сессия создаётся только когда сессии
нет вовсе.

Следствия: ручное перетаскивание запускает `on_enter` целевого шага; перенос
туда-обратно память не рвёт; единственное, что рвёт — явный
`reset_agent_context`.

## Документы задачи

`write_task_document_kandev`, `get_task_document_kandev`,
`list_task_documents_kandev`. Документ — `document_key`, `title`, `type`,
`content`, автор.

Внимание: эти три инструмента регистрируются только в режиме office (`server.go`, таблица регистрации, «office-documents»); на канбан-доске их у агента нет. Ключевое: список доступных документов **автоматически подставляется в промпт
агента** («Documents available (fetch with get_task_document_kandev)»,
`internal/office/service/prompt_handoff_test.go`), а тела не отдаются — агент
забирает нужный явным вызовом. Видимость шире одной задачи: документы
родителя, соседей и блокирующих задач тоже попадают в список
(`internal/task/service/handoff_context.go`).

Это прямая альтернатива нашему `.kandev/artifacts/$KANDEV_TASK_ID/`.

## Разговор задачи

`get_task_conversation_kandev` возвращает сообщения основной сессии задачи,
включая сообщения пользователя (`internal/mcp/handlers/get_task_conversation_test.go`).

Это канал, по которому замечание человека доезжает до роли **со сброшенным
контекстом**. Мы считали, что такого канала нет.

## Задачи, подзадачи, зависимости

- `create_task_kandev` — создать задачу, в том числе дочернюю.
- `delegate_task_kandev` — делегировать.
- `add_task_dependency_kandev` / `remove_task_dependency_kandev` — блокеры.
- `list_related_tasks_kandev` — родитель, дети, соседи, блокеры.
- `message_task_kandev` — сообщение другой задаче.
- `on_children_completed` и `on_blocker_resolved` — реакции на их события.

Это готовый механизм для нерешённого пробела «дробление крупной задачи на
дочерние», который в шпаргалке роли `Scoping` записан как отсутствующий у всех
источников.

## Несколько агентов на одной задаче

`spawn_session_kandev` запускает **дополнительную** сессию на существующей
задаче со своим профилем агента, тем же путём, что кнопка «New Session»
(`internal/mcp/handlers/spawn_session.go`). Новая задача не создаётся.

## Ревью и решения

- `publish_review_findings_kandev` — находки в панель ревью (используем).
- `record_step_decision_kandev` — решение на шаге-одобрении; роль и место
  определяются сервером, не агентом.
- `clear_decisions` в `on_enter` — сбросить решения при новом круге.
- `queue_run_for_each_participant`, `ensure_participant_seat` — веерный запуск
  по участникам-ревьюерам.

## План, PR, CI

- `create_task_plan_kandev` / `update_task_plan_kandev` / `get_task_plan_kandev`
  / `delete_task_plan_kandev` — нативный План (используем).
- `update_task_pr_automation_kandev`, `update_task_mr_automation_kandev` и их
  `get_`-пары — нативная авто-починка CI (используем через `Draft PR`).
- `add_branch_to_task_kandev`, `update_repository_base_branch_kandev`.

## Прочее, что существует

`stop_task_kandev`, `update_task_state_kandev`, `set_task_title_kandev`,
`archive_task_kandev` / `restore_task_kandev`, `show_rich_output_kandev`,
`show_walkthrough_kandev`, `get_diagnostic_bundle_kandev`,
`list_shared_prompts_kandev` / `get_shared_prompt_kandev`,
`list_agent_profiles_kandev`, `list_task_sessions_kandev`, полный набор
инструментов управления цепочками и шагами (`create_workflow_step_kandev`,
`reorder_workflow_steps_kandev`, `import_workflow_kandev`,
`export_workflow_kandev` и другие).

## Что делают встроенные цепочки, а мы нет

Из `docs/workflow-tips.md`: во **всех пяти** встроенных шаблонах возврат на
доработку сделан одинаково — «Sending a message moves the task back to X», то
есть `on_turn_start: move_to_previous` или `move_to_step`. В Kanban `Review`
возвращает в `In Progress`, `Done` переоткрывает задачу. Это родной способ
сказать «переделай, вот почему»: человек пишет сообщение, карточка едет назад,
и сообщение уже лежит в той же сессии как инструкция.

Родная документация также прямо рекомендует держать конвенции в `CLAUDE.md` /
`AGENTS.md` самого репозитория, а не в платформе.

## Чего я не разбирал

Бюджеты и `on_budget_alert`, `on_heartbeat`, режим office целиком, плагины,
worktree и снимки git, `pull_from_step` и `wip_limit` в деталях,
`set_session_mode` — какие значения принимает помимо `default` и
`acceptEdits`.
