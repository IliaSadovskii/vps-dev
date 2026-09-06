# Промпты

Префикс имени файла говорит, что это:

| Префикс | Что | Кто читает |
|---|---|---|
| `role-` | роль шага цепочки; по умолчанию шаг `id` читает `role-<id>.md` | движок вклеивает в промпт шага |
| `sub-` | роль подагента внутри шага | шаг-родитель передаёт подагенту путь |
| `common-` | общие правила, приклеиваются ко всем ролям цепочки через `includes` | все роли цепочки |
| `skill-` | навык, подключается строкой `Навыки:` в `scoping.md` | роли, перечисленные в шапке навыка |
| `test-` | заглушки для тестовой цепочки `smoke` | только разработка оркестратора |
| `role-stand` | не шаг: поднимает окружение задачи на её блоке портов и сообщает адрес | движок по кнопке «Поднять стенд» или к первым воротам |
| `role-wizard` | не шаг: мастер задачи — формулирует ТЗ, спрашивает цепочку, ветку и автономию, заводит задачу | движок по кнопке «Новая задача» |

Движок добавляет к каждому промпту блок задачи: текст задачи, путь по шагам,
заход, файлы для чтения, комментарии владельца, можно ли спрашивать, исходы. Роли
на него ссылаются как на «блок задачи»; ничего из него в промпт роли не
дублируется.

## Роли Deep (8)

| Шаг | Файл | Из Kandev |
|---|---|---|
| Разведка | `role-scoping.md` | Discovery + Scoping |
| Решение | `role-solution.md` | Research + Solution Synthesis |
| План | `role-plan.md` | Planning (файл вместо нативного Плана) |
| Ревью плана | `role-plan-review.md` | Plan Review |
| Реализация | `role-implementation.md` | Test Authoring + Implementation + Verification |
| Ревью кода | `role-code-review.md` + `sub-review-defects.md` + `sub-review-security.md` | Code Review + Security Review + Fix Review + Final Verification |
| Правки | `role-review-fixes.md` | Review Fixes |
| PR | `role-pr.md` | Draft PR |

Ворота Kandev (Backlog, Solution Approval, Plan Approval, Human Review, Done) и
промпт `custom-gate` не переносились: остановки задаёт `human.after` в
цепочке, доклад владельцу — последнее сообщение роли.

## Служебные цепочки

`conventions.yml`: `role-conventions` → `role-conventions-check`.
`blueprint.yml`: `role-blueprint` → `role-blueprint-check`, оба с
`common-knowledge-shape`.

## Что заменено в текстах

`step_complete_kandev`, `move_task_kandev` → `orch done <исход>`;
`ask_user_question_kandev` → интерактивный вопрос агента;
`kd-state` → нет (движок ведёт состояние); файлы `notes-*.md` → комментарии в
блоке задачи; `README.md` индекс → нет; `publish_review_findings_kandev` →
раздел находок в файле; `get_task_plan_kandev` → `plan.md`;
`get_shared_prompt_kandev` → чтение файла навыка по пути; трейлер
`Kandev-Step:` → `Orch-Step: <шаг>`, тесты — `Orch-Step: tests`;
`.kandev/artifacts/$KANDEV_TASK_ID/` → `.orch/<task>/artifacts/`.

Навыки и `common-knowledge-shape` перенесены как были (английский, длинные) —
сократить после первого прогона Deep и Blueprint.
