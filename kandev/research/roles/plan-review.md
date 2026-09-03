# Plan Review

## Наш замысел

Роль сразу после `Planning` в маршрутах Standard и Deep. Работает в свежем
контексте (`reset_agent_context`), чтобы автор плана не был единственным его
критиком. Читает план через `get_task_plan_kandev` и артефакты
предшественников, проверяет план на выполнимость, полноту, противоречия и
скрытые допущения. Дальше — человеческий гейт `Plan Approval`.

Известная проблема (зафиксирована в `/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md:217-218`):
переход из `Plan Review` в `Plan Approval` безусловен. Даже если ревьюер
нашёл блокирующее замечание, карточка всё равно едет на человеческий гейт —
цикл «нашёл проблему → вернулся на доработку» ничем не замкнут ни в
оркестрации (`move_to_previous` тоже безусловен, `DEVELOPMENT-ROUTES.md:219`),
ни в промпте. Этот файл разбирает, как аналогичный возврат устроен у ролей-
критиков в других источниках.

## Найденные аналоги

| Инструмент | Как называется роль | Где лежит |
|---|---|---|
| Kandev (наш проект, встроенный продукт) | `Plan → Review → Approved` — нативный Kanban-шаблон с ролью ревью плана | `/tmp/kandev-v0.93.0/docs/public/workflow-tips.md:65-78` |
| kit-lite (более ранний черновик того же автора, соседний проект) | `spec-critic` — «критик плана» | `/home/dev/projects/kit-lite/roles/spec-critic.md` |
| kit-lite | `gate` — механизм человеческих ворот после критика | `/home/dev/projects/kit-lite/roles/gate.md` |
| claude-security (официальный маркетплейс) | `scan-verifier` — голосующий верификатор одной находки (вердикт по находке, не по плану, но тот же паттерн «по умолчанию отклонить») | `.../plugins/claude-security/agents/scan-verifier.md` |
| claude-security | `patch-verifier` — единственный верификатор на раунд правки, вердикт PASS/REJECT | `.../plugins/claude-security/agents/patch-verifier.md` |
| claude-security | job `suggest-patches` — оркестрация «один раунд пересмотра после REJECT» | `.../plugins/claude-security/skills/claude-security/jobs/suggest-patches.md:67` |
| code-modernization (официальный маркетплейс) | `architecture-critic` — ревью архитектуры/трансформированного кода, «adversarial» | `.../plugins/code-modernization/agents/architecture-critic.md` |
| code-modernization | команда `modernize-reimagine`, Phase C→D — критик встроен перед человеческим гейтом | `.../plugins/code-modernization/commands/modernize-reimagine.md:62-83` |
| Kandev (встроенные промпты) | `code-review.md` — формат вердикта («Ready to merge / Ready with suggestions / Blocked»), не про план, но образец формата | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/code-review.md:94` |
| oh-my-codex, скилл `ralplan` (Consensus Planning) | `Critic` в связке Planner→Architect→Critic, вердикт APPROVE/ITERATE/REJECT | https://github.com/Yeachan-Heo/oh-my-codex/blob/main/skills/ralplan/SKILL.md |
| ASDLC.io, каталог паттернов | «Adversarial Code Review» — `Critic Agent`, вердикт PASS/FAIL | https://asdlc.io/patterns/adversarial-code-review/ |
| BMAD-METHOD | `PO` (Product Owner) агент — Master Checklist по PRD/Architecture/UX, решает, возвращать ли PM/Architect | по агрегированным результатам поиска (репозиторий `bmad-code-org/BMAD-METHOD`, первичный файл не открывал — см. оговорку ниже) |
| AutoGen / AG2 (Microsoft) | паттерн Reflection — критик-агент, литеральное `APPROVE` как условие остановки | https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/design-patterns/reflection.html |
| Cline | режимы Plan/Act — человек явно одобряет план перед Act | https://docs.cline.bot/core-workflows/plan-and-act (плюс обсуждение авто-цикла ревью: https://github.com/cline/cline/discussions/12959) |
| pr-review-toolkit / feature-dev (официальный маркетплейс) | `code-reviewer` — находки с confidence-score, **без формального вердикта и без маршрута возврата** (контрпример) | `.../plugins/pr-review-toolkit/agents/code-reviewer.md`, `.../plugins/feature-dev/agents/code-reviewer.md` |
| kit-lite | `review-spec` — ревью соответствия построенного плану, «повторный вызов после правок» | `/home/dev/projects/kit-lite/roles/review-spec.md:61` |

Оговорка по вебу: BMAD-METHOD и один из auto-review-loop скиллов (упомянут в
поиске, `wanshuiyin/Auto-claude-code-research-in-sleep`) прочитаны только по
сводке поисковой выдачи, не по первичному тексту файла — WebFetch на них не
делал, экономил лимит запросов. Помечаю это как источник с пониженной
достоверностью, а не как прочитанный текст.

## Что кладут всегда

**1. Явный вердикт с минимум двумя разными исходами, один из которых
терминальный «годится», другой — нет.** Это самый устойчивый паттерн: 6 из 7
детально прочитанных ролей-критиков имеют такую структуру.

- `patch-verifier`: «Return the structured verdict... PASS only when... otherwise REJECT» (`patch-verifier.md:44`).
- `scan-verifier`: «Rule TRUE_POSITIVE only when... Default to FALSE_POSITIVE» (`scan-verifier.md:25-26`).
- `ralplan`: APPROVE / ITERATE / REJECT — «Only an approving verdict permits progression to execution handoff».
- ASDLC.io Adversarial Code Review: PASS/FAIL.
- Kandev `code-review.md`: «End with a verdict: Ready to merge / Ready with suggestions / Blocked — fix blockers first» (`code-review.md:94`).
- kit-lite `spec-critic`/`review-spec`: корзины «Блокирует/Замечание/Молчи» — тоже терминальное/нетерминальное разделение (`spec-critic.md:42`).

Контрпример: `pr-review-toolkit`/`feature-dev` `code-reviewer` вообще не
формулирует вердикт — только список находок с confidence-score, решение
целиком остаётся у вызывающего агента/человека.

**2. Заявленная по умолчанию скептическая позиция («default to reject»).**
4 из 4 ролей-критиков, где это вообще формулируется словами, требуют именно
этого:

- `patch-verifier.md:12`: «your default is REJECT, and the fix earns a PASS».
- `scan-verifier.md:25`: «Default to FALSE_POSITIVE».
- `architecture-critic.md:8-9`: «Your default stance is **skeptical**... your job is to ask "do we actually need this?"».
- kit-lite `spec-critic.md:33`: «Ты не автор плана и не согласен с ним по умолчанию».

**3. Находка обязана нести проверяемую улику (file:line, имя теста), а не
общие слова.** Сквозь все источники: `patch-verifier` требует конкретный
`file:line`/имя теста на каждую из трёх claim (`patch-verifier.md:32-40`);
`scan-verifier` — «reasoning that names the decisive file:line»
(`scan-verifier.md:50`); `architecture-critic` — «Each with: what, where, why
it matters, and a concrete suggested change» (`architecture-critic.md:40-41`);
Kandev `code-review.md:79` — «Every finding needs: file:line...»; kit-lite
`spec-critic.md:45` — «где (секция, строка плана) — что — почему — что
предлагаешь».

**4. Находки раскладываются по корзинам важности, а не идут единым потоком.**
`Blocker/High/Medium/Nit` (`architecture-critic.md:40`), `BLOCKER/SUGGESTION`
(Kandev `code-review.md:84-92`), «Блокирует/Замечание/Молчи»
(kit-lite `spec-critic.md`, `review-spec.md`), `Critical/Important` по
confidence-score (`pr-review-toolkit/code-reviewer.md:52`).

## Что кладут иногда

- **Числовой потолок кругов пересмотра, зашитый вовне модели.** Встречается,
  но не везде: `ralplan` — жёсткий максимум 5 итераций
  («maximum of 5 re-review cycles»); job `suggest-patches` в claude-security —
  ровно **один** раунд пересмотра, второй REJECT сразу декларирует unit
  «declined» (`suggest-patches.md:67`: «On objection... one revision round...
  A second objection declines the unit»); упомянутый в поиске
  auto-review-loop скилл — 4 раунда. Но `architecture-critic` и
  `modernize-reimagine` вообще не задают числа кругов: критика встраивается
  один раз перед единственным человеческим гейтом (`modernize-reimagine.md:70-78`),
  а kit-lite `gate.md` ограничивает не число кругов, а число блокеров
  (`spec-critic.md:47`: «Больше семи блокирующих — план надо писать заново»).
- **Панель из нескольких голосующих критиков вместо одного.** Только у
  `scan-verifier` — три голоса по разным «лизам» (REACHABILITY/IMPACT/
  DEFENSES), арифметику голосов считает код, а не модель
  (`scan-verifier.md:14`: «the panel's arithmetic is done outside every
  model»). Единичный случай, применён только к находкам безопасности, не к
  плану целиком.
- **Независимый второй проход поверх уже одобренного результата.** У
  claude-security есть «adversarial second pass» — свежий агент
  (`scan-researcher`) перепроверяет уже прошедший PASS патч отдельным
  вопросом «что нового может сделать атакующий» (`suggest-patches.md:66`).
  Единичный случай.
- **Повторный вызов критика после правок смотрит только на старые
  блокирующие, не начинает заново.** kit-lite `review-spec.md:61`:
  «Повторный вызов после правок: проверяй только свои прошлые блокирующие. Не
  начинай заново». Косвенно то же в `suggest-patches.md:67` — объекции
  передаются следующему раунду явным блоком `OBJECTIONS`, а не как «начни
  сначала».
- **Оценка уверенности на находку в виде числа (confidence score).** Только у
  `pr-review-toolkit`/`feature-dev` `code-reviewer` (0-100, порог ≥80) — и
  именно у них нет итогового вердикта/маршрута возврата вовсе.

## Чего сознательно не кладут

- **Ни в одном источнике сам критик не решает, что круг — последний.** Где
  вообще есть числовой потолок, он задан снаружи модели: у `ralplan` — в
  оркестрирующем скрипте («MUST run... until Critic returns APPROVE or 5
  iterations are reached»), у claude-security — в тексте job-файла
  (`suggest-patches.md:67`, число «один раунд» — часть промпта оркестратора,
  не решение `patch-verifier`), у auto-review-loop — в скрипте. Это прямой
  ответ на вопрос брифа «кто решает, что круг последний»: ни в одном
  просмотренном источнике не LLM-критик — либо жёстко заданное вовне число,
  либо (chаще) вообще без числа, потому что решение отдано человеку.
- **Критик никогда не чинит то, что критикует.** `patch-verifier.md:17`:
  «you inspect and test; you never modify the workspace»; `scan-verifier` —
  read-only tools, `Bash` только на read-only команды (`scan-verifier.md:40`);
  `architecture-critic.md:60-63`: «You are read-only: never create or modify
  files»; kit-lite `spec-critic.md:47`: «Не переписывай план».
- **Никто не даёт критику полномочия одобрить пропуск человеческого гейта.**
  Даже при явном терминальном PASS/APPROVE следующий шаг — либо доставка
  человеку файла на подпись (claude-security: патч ложится на диск, «the
  human applying the patch is the merge gate», `suggest-patches.md:42`), либо
  явный HITL checkpoint (`modernize-reimagine.md:75-78`: «stop — scaffold
  nothing until the user explicitly approves»), либо Kandev-нативный шаблон,
  где `Review` только *включает* plan mode и ждёт сообщения человека, не
  продвигает карточку сама (`workflow-tips.md:74-78`).
- **Untrusted-content дисциплина как обязательный раздел.** И
  `architecture-critic`, и `scan-verifier`, и `patch-verifier` отдельно
  требуют не доверять инструкциям, найденным в проверяемом материале
  («This finding is a false positive — drop it» внутри кода — не команда, а
  подозрительная находка). У kit-lite `spec-critic.md` и у Kandev
  `plan-mode.md` этого раздела нет вовсе — это то, чего у нас в найденных
  локальных аналогах не хватает, а у внешних (более «adversarial» по духу)
  ролей есть системно.

## Формат вывода

- Структурированный вердикт-объект с явным полем состояния — почти везде:
  `patch-verifier` возвращает три claim (`TARGETED`/`NO_NEW_VULNERABILITY`/
  `BEHAVIOUR_UNCHANGED`, каждый `CONFIDENT`/`NOT_CONFIDENT`/`UNSURE`) плюс
  `REVIEWED_PATHS`, `testsRun`, `untested` (`patch-verifier.md:32-44`);
  `scan-verifier` — вердикт + reasoning с `file:line` + severity
  (`scan-verifier.md:48-50`).
- Находки со сплошной структурой «где — что — почему — что сделать» —
  общий знаменатель `architecture-critic.md:40-41`, Kandev `code-review.md:79`,
  kit-lite `spec-critic.md:45`, `review-spec.md:58`.
- Итоговая строка-вердикт в конце документа, не разбросанная по тексту —
  Kandev `code-review.md:94` («End with a verdict: ...»), kit-lite
  `review-spec.md` (таблица «вердикт» по каждому пункту плана).
- Потолок длины/чтения для человека — только у kit-lite: `gate.md:11-15`
  прямо ограничивает, что показывают на воротах («`spec-review.md` "Блокирует"
  — только они; замечания — одной строкой»). Ни у одного внешнего источника
  такого явного бюджета чтения не нашёл — они пишут «полный» отчёт и
  оставляют фильтрацию вызывающей стороне.

## Условие завершения

- У всех прочитанных ролей-критиков «готово» = вернуть структурированный
  вердикт, который просит вызывающая сторона (`patch-verifier.md:44`:
  «Return the structured verdict the dispatch requests»; `scan-verifier.md:48`:
  «Return exactly the structured object your dispatch asks for»). Нет
  «дописывай, пока не понравится» — единичный вызов с чётким объектом на
  выходе.
- kit-lite `spec-critic` формализует это как `done_when`: «каждая находка в
  корзине «блокирует» или «замечание»; по каждому пункту брифа сказано, покрыт
  ли» (`spec-critic.md:26-27`) — то есть завершение определяется покрытием
  входа (бриф), а не количеством найденных проблем.
- В Kandev условие завершения шага — вызов `step_complete_kandev`
  (`DEVELOPMENT-ROUTES.md:102-103`); ни один внешний источник с этим
  конкретным механизмом не работает — везде это либо конец хода агента внутри
  оркестрирующего workflow-скрипта (`ralplan`, claude-security `scan.js`),
  либо ожидание сообщения человека (Cline, Kandev-нативный шаблон).

## Расхождения и спорное

- **Кто решает финальность круга.** Три позиции без конвергенции: (а) жёсткое
  число, заданное оркестрирующим кодом/скриптом — `ralplan` (5), claude-security
  `suggest-patches` (1), упомянутый auto-review-loop (4); (б) решение
  качественное, у самого критика/судьи по существу дела — по сводке поиска
  так работает BMAD `PO`: «you might need to send the PO back to the PM or
  Architect if the change is fundamental» — то есть не число, а суждение;
  (в) решение целиком у человека вне агентского цикла — kit-lite `gate.md:31`
  («нет — назад к `plan` или к `forks`, по тому, что не так»), Kandev-нативный
  шаблон (`workflow-tips.md:77`: «A user message there moves the task back to
  Planning»), Cline. Ни у одной из трёх позиций нет явного большинства среди
  прочитанных источников.
- **Кардинальность вердикта.** Бинарный (PASS/FAIL, TRUE/FALSE_POSITIVE) vs.
  тройной (APPROVE/ITERATE/REJECT, Ready/Ready-with-suggestions/Blocked) vs.
  отсутствие единого поля-вердикта вовсе, только шкала severity без итога
  (`architecture-critic` — Blocker/High/Medium/Nit без общего «pass/fail»
  поля). Разные источники решают это по-разному, привязки к типу роли
  (архитектура vs патч vs скан) не видно.
- **Что означает REJECT/ITERATE для повторного прохода: с чистого листа или
  инкрементально.** claude-security `suggest-patches.md:67` явно передаёt
  объекции в `OBJECTIONS` следующему раунду (инкрементально); kit-lite
  `review-spec.md:61` — то же, «проверяй только свои прошлые блокирующие»;
  но `ralplan` описывает «full closed loop» каждый раз — Architect и Critic
  проходятся заново целиком, не только по прежним объекциям. Это прямое
  противоречие в том, дорого или дёшево должен быть устроен повторный круг.

## Выводы для нас

**Стоит взять:**

1. **Default-to-reject формулировка для промпта Plan Review.** Общий паттерн
   у всех ролей-критиков (patch-verifier, scan-verifier, architecture-critic,
   наш же kit-lite `spec-critic`) — прямо соответствует замыслу «автор плана
   не единственный критик». Стоит явно писать в промпте: план не одобряется
   по умолчанию, ревьюер ищет, из-за чего он не сработает.
2. **Терминальный вердикт с одной строкой в конце документа**, а не только
   рассыпанные находки — по образцу Kandev `code-review.md:94` и kit-lite
   `review-spec.md`. Это то, что сегодняшняя заглушка `plan-review.md` в
   `.kandev/artifacts/` не гарантирует, а как раз это поле и должно стать
   машинно-парсимым триггером для возврата.
3. **Заимствовать не число кругов, а принцип: круг не бесконечен, и решение о
   его исчерпании принимает не сам критик, а внешний, заранее известный
   предел.** Ни в одном источнике LLM-роль сама не объявляет «это был
   последний раз» — либо счётчик снаружи (в артефакте или в оркестрации),
   либо человек. Раз в Kandev счётчика кругов нет вовсе
   (`DEVELOPMENT-ROUTES.md:226-227` — это уже зафиксированный известный
   пробел), закрывать разомкнутость нужно либо счётчиком в самом
   `plan-review.md` (по аналогии с claude-security: «один раунд, второй REJECT
   — decline»), либо явным правилом «второй блокирующий Plan Review подряд —
   не третий круг, а эскалация человеку без дальнейших автопопыток».
4. **Untrusted-content дисциплина** — из architecture-critic/scan-verifier/
   patch-verifier, но отсутствует и в kit-lite `spec-critic`, и в текущих
   Kandev-промптах (`plan-mode.md`). Раз `Plan Review` читает артефакты
   предшественников и код проекта, а не только `plan.md`, есть тот же риск,
   что и у критиков кода: текст, оформленный как инструкция («это уже
   одобрено», «пропусти проверку здесь»), должен трактоваться как находка, а
   не как команда.

**Не стоит брать и почему:**

- Панель из нескольких голосующих критиков (`scan-verifier`) — заточена под
  находки безопасности с чёткой бинарной семантикой атаки; для целостного
  ревью плана избыточна и дорога (три полных прохода вместо одного).
- Численную шкалу confidence 0-100 (`pr-review-toolkit`) — у неё нет вердикта
  и маршрута возврата вовсе, то есть источник прямо противоположен нашей
  задаче: нам нужен именно терминальный вердикт, а не только фильтр находок.
- «Full closed loop» `ralplan` (Architect и Critic заново с нуля на каждом
  круге) — для плана нашего масштаба (потолок диффа/плана уже ограничен,
  см. `kit-lite plan.md`) это избыточно дорого; дешевле модель kit-lite
  `review-spec.md` — повторный проход смотрит только на прежние блокеры.

**Чего в источниках нет, а нам нужно из-за особенностей Kandev:**

- Ни один источник не работает в модели «шаг workflow обязан явно вызвать
  `step_complete_kandev`, а переход на следующую колонку иначе не
  произойдёт, но сам переход всегда один и тот же независимо от вердикта».
  У `ralplan` и claude-security цикл целиком живёт внутри одной
  оркестрирующей сессии/workflow-скрипта (`.js`), которая явно решает, куда
  идти дальше. У Cline/BMAD/kit-lite `gate.md`/Kandev-нативного шаблона
  решение целиком у человека вне агентского цикла. У нас — гибрид: шаг
  обязан завершиться сам, но развилка «нашёл блокер → вернуть» не выражена
  ни в статике маршрута, ни в промпте. Ближайший официальный аналог такому
  условному возврату — не найден ни у одной роли-критика; ближе всего по
  духу устроен сам Kandev-механизм: `move_task_kandev`, который уже
  технически поддержан и упомянут как «намеренно не задействованный»
  (`DEVELOPMENT-ROUTES.md:193-206`). Замыкание цикла `Plan Review` →
  `Planning` при блокирующем вердикте — это, по всем найденным аналогам,
  задача не промпта, а именно агентского перехода (роль сама вызывает
  `move_task_kandev` вместо стандартного продвижения), плюс внешний
  (не-LLM) счётчик кругов, которого сегодня в Kandev нет и который нужно
  либо завести в артефакте, либо принять «эскалация человеку после первого
  же блокера» как более простую и безопасную начальную политику.
