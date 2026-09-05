# AgentKit: что не перенесено в Kandev (разбор 2026-09-05)

Отчёт агента, который прочитал `/home/dev/projects/agent-kit` целиком
(плагин v2.28.4, 386 коммитов, июль–август 2026) и сверил с
`PREDECESSORS.md`, `DECISIONS.md` (решения 55–62) и промптами Kandev.
Выводы и рекомендации — в `REVIEW-2026-09-05.md`, раздел 2. Здесь
карта с путями, чтобы не искать заново.

## 1. Карта AgentKit

Плагин `plugins/agent-kit/`. Девять команд в четырёх ролях: «знать»
(blueprint, advise), «строить» (fix, ship, sprint, epic), «проверять»
(audit, accept), «ориентироваться» (next).

### Команды (skills)

| Механизм | Путь | Суть |
|---|---|---|
| blueprint | `skills/blueprint/SKILL.md` | Одна дверь: владелец говорит свободно → чтение затронутых записей → экран сравнения new/refines/contradicts/unchanged → запись → пробелы по цене. Пишет `docs/knowledge/`, `.agent-kit/project.yml`, блок в `CLAUDE.md`. |
| blueprint --recall, блоки, жалобы | `skills/blueprint/references/doors.md`, `references/blocks.md` | Пересказ части вслух; таблица пяти видов блоков и как каждый закрывается; развилка «описание неверно / продукт неверен» по жалобам после использования. |
| ship | `skills/ship/SKILL.md` | Одна фича: Design → Build → Verify → Deliver. Таблица «что нашёл → куда пишет → кто читает», `agent-kit:unmet`, `[assumed]/[found]/[stale]`, `verified`, `mutation`, `proved_at`, handoff между сессиями. |
| fix | `skills/fix/SKILL.md` | Дефект: причина → красный тест → минимальная правка → откат для доказательства. Три стоп-условия: «это не построено», «это решение, а не дефект», «это переписывание». |
| sprint | `skills/sprint/SKILL.md`, `references/frame.md`, `references/close.md` | Бриф партии, frame-child (общие договорённости партии как `[frame]` под `stack.md` + карта `needs`), драйвер, закрывающая сессия (один PR на партию, движение долга, `docs/runs/<slug>.json`). |
| epic | `skills/epic/SKILL.md`, `references/finish.md` | Весь объём: ворота с ценой в часах, партии, аудит волнами (потолок 3), сценарии против запущенного приложения в свежем worktree. |
| audit | `skills/audit/SKILL.md`, `references/{tests,scenarios,security,performance,conventions,deps}.md` | Шесть объективов, каждый пишет `docs/audits/<lens>.md`; baseline «поверхность в коде без записи / запись без поверхности»; пять вердиктов, шестой не выдумывать. |
| advise | `skills/advise/SKILL.md`, `references/{product,code,money}.md` | Сомневается в самом описании; принятое → `[accepted]` в слот, отклонённое → `docs/advice/<lens>.md` и не поднимается снова. |
| accept | `skills/accept/SKILL.md` | Приёмка большого PR без чтения диффа: шесть блоков в порядке действий человека; запускает proof-команды `docs/manual.md`. |
| next | `skills/next/SKILL.md` | Холодный старт: лестница из 11 ступеней по цене бездействия; три переопределения. |

### Правила (rules/)

| Файл | Суть |
|---|---|
| `rules/asking.md` | Вопрос вариантами, рекомендация первой; «сначала сделай работу, спроси остаток»; «назови факт, который решил бы вопрос, и почему не можешь его достать». |
| `rules/knowledge-writing.md` | Прозу пишут только при присутствии владельца; новая запись `planned`; каскад ключей целиком или никак; коммит на слот. |
| `rules/channels.md` | Таблица всех каналов: кто пишет / кто читает / кто закрывает / где живёт. |
| `rules/preflight.md` | Реакция на находки check.py перед каждой командой; «скажи, сколько накопилось». |
| `rules/pull-requests.md` | Три ответа над сгибом; потолки 2500/4000/15 строк, считает программа. |
| `rules/closing.md` | «Скажи, где тонко, не что сделал»; последняя строка — следующая команда. |
| `rules/craft.md` | Четыре правила: продукт делать верным, а не проверку тихой (пять лазеек поимённо); заглушка доказывает заглушку; ничего сверх записи; выход обозначен. |
| `rules/audit-boxes.md`, `rules/window.md` | Тик чекбокса только с номером PR; окно управления — отчитывается, не спрашивает. |

### Скрипты, хуки, агенты

| Файл | Суть |
|---|---|
| `scripts/check.py` (3900 строк) | Механический аудит знаний перед каждой командой: поля, ссылки ключей, сироты, хэши источников, возраст стека, блоки, вердикты слотов, `unmet`, долг, manual. Флаги `--status --state --sync --record --manual --brief <key> --entries <keys> --owed --tests --epic --run <dir> --pr-body --pr-base`. |
| `scripts/orchestrate.py` | Драйвер партии: tmux, heartbeat по mtime транскрипта, 429-лимит, handoff по размеру контекста, `costly()` — говорит окну о дорогих допущениях ребёнка. |
| `hooks/guard.py`, `hooks/stop.py` | PreToolUse: запрет merge / force-push / push в default — только пока run в полёте. Stop: не дать закончить ход мид-степ. |
| `agents/reviewer.md` | Пять вопросов: та ли фича, что утверждена; код держится; та ли, что спроектирована; покрывает ли запись построчно; нет ли лишнего. Дорогое допущение без блока — major; ослабленный тест — находка. |

### Шаблоны

| Файл | Суть |
|---|---|
| `templates/knowledge/*.md` | Восемь файлов с шапкой `fields:` и «Done when» — перенесены в `custom-knowledge-shape`. |
| `templates/project.yml` | `commands`, `tests.unmet`, вердикт на слот, `verification` (ответ на каждый вид: команда или `no <дата> <причина>`), хэши манифестов. |
| `verification.yml` | 12 видов проверки: что ловит, кто гоняет, когда неприменимо. |
| `templates/run.json` | Память прогона: `assumptions[{what,why,entry,expensive}]`, `deviations`, `unmet`, `deferred`, `manual[{what,where,proof,when}]`, `proved_at`, `verified[]`. |
| `templates/technical_debt.md`, `templates/manual.md` | Ведомость долга (закрывается удалением строки в коммите работы); действия для рук владельца с `proof:` командой. |

Документы дизайна: `docs/design/the-loop.md` (шесть замкнутых циклов
с закрывающим), `docs/design/method.md` (11 уроков: «назови дешёвый
путь и потребуй артефакт, который он не даёт»),
`docs/design/2026-08-19-the-gaps-in-what-is-known.md` (73 → 14),
`docs/design/2026-08-12-frame.md`, `docs/planned.md`.

## 2. Обратная связь в чертёж: как работало

**Граница «кто пишет прозу»** (`rules/knowledge-writing.md`):

> A run with nobody in the room may move an entry's `state:` line and
> leave a block, and that is all — it may not write prose, because
> prose is a decision and there is no one there to make it.

Прозу пишут `blueprint` и `advise`. Строительные команды пишут в
знания ровно две вещи: строку `state:` и блоки.

**Пять видов блоков** (регэксп `scripts/check.py:103`):

```markdown
> **[assumed 2026-08-02 · claude/<branch>]** <what the knowledge does not say>. Took: <what you did>.
> Expensive to get wrong — <data model | permissions | money | public contract>.
```

| Блок | Кто пишет | Смысл | Кто закрывает |
|---|---|---|---|
| `[assumed …]` | ship, fix | знание молчало, прогон решил | blueprint спрашивает yes/no, пишет ответ в поле, удаляет блок |
| `[found …]` | ship | готовая библиотека, которой нет в карте | blueprint вносит в карту |
| `[stale …]` | ship, fix | фича сделала прозу ложной; блок несёт обе половины | blueprint; closing-session партии применяет в PR |
| `[accepted …]` | advise | владелец принял предложение, поля не заполнены | blueprint |
| `[frame …]` | frame-child партии | как фичи партии строят одинаково | blueprint после слияния партии |

«Deleting the block is the resolution; there is no `resolved` field
anywhere». «A recorded assumption is the decision of record until the
owner changes it. A later run hitting the same gap follows it rather
than inventing a second reading — that is what keeps features
consistent with each other.»

**Когда срабатывает** — таблица «Record as you go» в
`skills/ship/SKILL.md`: дорогое допущение (хранимые данные, права,
деньги, внешний контракт) → `[assumed]` под записью и `expensive:
true` в run.json; запись обещает, чего код не делает → тест с
`agent-kit:unmet <key>`; нужны руки владельца → `manual` с proof;
отступил от подхода → `deviations`; фича сделала прозу ложной →
`[stale]`; понял и не сделал → строка долга.

Строка состояния: `ship` Deliver ставит `state: building (pr: <n>)`;
`check.py --sync` двигает в `built` по слитому PR; `blueprint` может
вернуть в `planned`.

**Фильтр «73 → 14»** (`docs/design/2026-08-19-the-gaps-in-what-is-known.md`):
прогон на 31 ребёнка дал 73 допущения в run-файлах, 28 без ответа
`expensive`; до знаний дошли 14 — те, где `expensive: true`. Фильтр
осознанный (`blocks.md`): «Blocks are only left where being wrong is
expensive… Without that filter the documents silt up after one
sprint.» Второе заиливание — блоки под `built`-записями, куда никакой
прогон больше не придёт (`check.py unreachable()`).

**Кто закрывает** (`docs/design/the-loop.md`): «A record is closed
inside work that was happening anyway. If the only place it can be
closed is a session the owner has to start for that purpose… the
recommendation to run it stops being read by the third time.» Каждый
механизм обязан иметь четыре ответа: кто пишет, кто читает, кто может
закрыть, что становится невозможно без него.

**Жалобы после использования** (`doors.md`): каждая — развилка
«описание неверно» (переписать прозу, только blueprint) / «продукт
неверен» (строка долга с меткой `owner` или запись назад в `planned`).
«Say the count back — four went into the description, nine into the
ledger.»

## 3. Статус в Kandev

П — перенесён, Ч — частично, О — осознанно отброшен, Н — не упомянут.

### Перенесено

Восемь слотов знания с шапкой; экран сравнения с обязательной
строкой unchanged; одна дверь; концовка сценария как выбор;
`[assumed]` под записью с правилом «удаление = решение» (для
Blueprint); `walked`/`derived`; вердикт слота; один писатель прозы;
стек ссылается на `AGENTS.md`; три ответа над сгибом PR; вопрос с
рекомендацией первой; версии из lock-файлов; дробление вопросом на
Scoping; строка `Чертёж:` (аналог `--brief`); `Расхождение с
чертежом:`; `Отступление от чертежа:`; сценарии как тесты с
`kandev:scenario`; профили моделей; test-first скриптом; ревью только
новых коммитов; один автовозврат с потолком; первый блок на воротах
≤10 строк.

### Частично

| Механизм | Что взято / что нет |
|---|---|
| Блоки от строительных прогонов (`[assumed]` при `expensive`, `[stale]`, `[found]`) | Решение 62: Deep читает и не пишет. Потеряно главное: допущение как решение по умолчанию для следующих задач; `[stale]` — запись стоит как истина до ручного Blueprint; `[found]` — карта библиотек не учится. |
| Три яруса пробелов | «Кто не может никогда» AgentKit всегда спрашивал, теперь только допущение. |
| Состояния `planned / building / built` | Blueprint пишет `planned`/`built`; Draft PR лишь пишет строку в «Отложено». |
| Счёт сценариев с тестом | Метка есть, счётчика нет. |
| Ведомость долга | Файл отброшен (решение 46), карточка «Долг по PR N». Потеряны ключ записи на строке, метка `owner`, чтение долга Discovery/Scoping (PREDECESSORS п. 5 обещал — в промптах нет). |
| `manual` с proof-командой | «Нужны руки» без proof, без `stage`. |
| Reviewer «та ли фича, что утверждена» | Code Review сверяет с Планом и `scoping.md`, но не с записью `docs/knowledge/`; «ослабленный существующий тест» как отдельная находка не названа. |
| `craft.md` | Решение 16 ≈ «ничего сверх записи». Не взято: пять лазеек «проверку тихой» поимённо; «заглушка доказывает заглушку». |
| `closing.md` | «Не решено:», «где тонко» у Blueprint. Общего правила нет. |
| verification.yml / ответы проекта на виды проверки | Решение 41 решает виды на задачу; проектный датированный ответ потерян — спрашивается на каждой задаче. |
| Таблица «кто пишет / читает / закрывает» | В `HANDOFF-CONTRACT.md` нет колонки «кто закрывает». |
| Frame-child для партий | Не упомянут; решение 20 отмечает, что дочерние worktree не видят родительских файлов. |

### Осознанно отброшено

`project.yml` (решение 61), хэши источников (61), `check.py` как
программа (61), пять входов (61), файл долга (46), SHA прогона (49),
потолок числа файлов (44), таксономия «дорого ошибиться» (45 — при
этом 61 велит дорогие допущения ставить первыми, то есть для
сортировки она осталась), triage (14), «промолчать» в ревью, cron и
слои страховки от автономии, возврат по сообщению (39), документы
Kandev вместо файлов (20).

### Не упомянуто вовсе

| Механизм | Путь | Что это |
|---|---|---|
| `agent-kit:unmet` | `skills/ship/SKILL.md`, `check.py collect_unmet` | Тест на обещание записи, которого код не выполняет, помечен, чтобы suite остался зелёным; противоречие записано, не разрешено. В Kandev не решено, что делать, когда запись и код спорят: тест на сторону кода замораживает противоречие. |
| `[stale …]` | `blocks.md`, `the-loop.md` цикл 2b | Проза, которую задача сделала ложной, стоит как истина до ручного Blueprint. |
| `[found …]` | `ship/SKILL.md` | `stack.md` в Kandev статичен. |
| `[frame …]` + `needs` + `Costs:` | `skills/sprint/references/frame.md` | Общие решения партии до кода, «checkable against a diff»; технический бюджет как продуктовый вопрос. |
| audit — шесть объективов, baseline | `skills/audit/SKILL.md` | Сверка кода с описанием целиком, не по задаче. |
| advise | `skills/advise/SKILL.md` | Единственная команда, которая сомневается в описании. |
| next — лестница по цене бездействия | `skills/next/SKILL.md` | PREDECESSORS назвал к переносу — решения нет. Backlog не ранжируется. |
| Недостижимые блоки, «скажи, сколько накопилось» | `check.py:3407`, `rules/preflight.md` | Та же проблема у «Отложено»: карточки долга копятся без счёта. |
| `--brief`/`--entries` как программа | `check.py:1794` | «Инструкция выполнена 0 раз из 6443 → делать командой». |
| Сироты и перекрёстные проверки как программа | `check.py check_orphans/check_references/check_shape` | «Роль делает чтением» проверить нечем. |
| Мутации по изменённым файлам | `templates/project.yml`, ship Verify 3 | PREDECESSORS обещал вопрос в Conventions — в промпте нет. |
| `proved_at` — результат прогона привязан к дереву | `templates/run.json` | Verification пишет вывод прогона без SHA. |
| PR body потолки программой | `rules/pull-requests.md` | Решение 47 ограничило первый блок артефакта, не PR. |
| `stage: development / released` | `templates/project.yml` | «Нужны ваши руки» не фильтруется по стадии: секрет для релиза, которого нет, идёт владельцу. |
| where-things-are в `CLAUDE.md` | `templates/where-things-are.md` | Указатель на `docs/knowledge/` никто не добавляет. |
| Рецепт против дешёвого пути | `docs/design/method.md` | Применён точечно, как общее правило протокола — нет. |
| «Каждый механизм — четыре ответа» | `docs/developing.md` | Колонки «закрывает» и «что невозможно без» нет. |
| Handoff-нота «каждое утверждение называет улику или говорит, что не проверено» | `templates/run.json` `_handoff` | В протоколе артефактов нет. |

Не переносить: окно управления, `waiting_on`, handoff по контексту,
stop-hook, guard в нынешнем виде (борется с tmux, у Kandev worktree и
сигнал), `docs/runs`/`measure.py`, `--recall`.
