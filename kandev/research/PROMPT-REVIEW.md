# Сквозное ревью промптов Kandev

Проверены все 15 реальных ролевых промптов (`custom-discovery.md` … `custom-pull-request.md`),
оба общих блока (`custom-artifact-protocol.md`, `custom-git-safety.md`) и все четыре
`kandev/workflows/*.yml`, против `HANDOFF-CONTRACT.md` и раздела 7
`PROMPT-WRITING-GUIDE.md`. `custom-ci-fixup.md` не проверялся, как и было сказано.

На диске 18 файлов в `kandev/prompts/`: 15 ролей + 2 общих блока + `custom-ci-fixup.md`
(намеренная заглушка) = 17 неисключённых файлов. «Шестнадцать» из брифа, видимо, считает
15 ролей плюс сам `custom-ci-fixup.md` как «промпт, который лежит на диске» (сама заглушка
отдельно исключена из проверки в тексте брифа) — файлов не меньше шестнадцати, отсутствующих
нет.

**Итог: 11 находок, блокирующих нет.** Самое важное — в `standard.yml` и `deep.yml` для шага
Test Authoring физически отсутствует `reset_agent_context`, хотя контракт и комментарии в
самих YAML утверждают, что контекст там сбрасывается. Дальше по значимости — у `custom-planning.md`
шапка `Reads` не называет нативный План, который роль тем не менее обязана прочитать первым
действием; `custom-review-fixes.md` сам себе противоречит в описании «Номера круга»; у
`custom-final-verification.md` вызов `move_task_kandev` описан заметно менее точно, чем у
`custom-plan-review.md`, хотя это парная функциональность. Остальное — точечные повторы общих
правил внутри ролей и мелкие шероховатости в шапках.

Три места, которые вы просили проверить первыми: счётчик кругов у трёх ролей расходится в
точности формулировки (находки 1 и 2 ниже); сравнение `final-verification.md` с
`verification.md` определено настолько чётко, насколько это вообще возможно при том, что
`verification.md` не обязан выдавать разбивку по тестам — это не баг, но и не железная гарантия
(находка 8); передача «Отклонений от плана» между `custom-implementation.md` и
`custom-verification.md` — единственная из трёх пар, где расхождений не нашлось, обе стороны
описывают её одинаково.

---

## Стоит поправить

### Test Authoring не сбрасывает контекст ни в Standard, ни в Deep
**Где:** `kandev/workflows/standard.yml:84-100` (шаг Test Authoring), `kandev/workflows/deep.yml:149-165`; для сравнения — сброс присутствует у Plan Review (`standard.yml:61`, `deep.yml:126`), Code Review (`standard.yml:149`, `deep.yml:214`), Security Review (`standard.yml:171`, `deep.yml:236`), Review Fixes (`standard.yml:192`, `deep.yml:257`)
**Что:** `HANDOFF-CONTRACT.md:51` заявляет: «Test Authoring | сброшен в Standard и Deep, продолжает в Quick». Комментарий в самом `standard.yml:7-8` говорит то же: «Test Authoring сбрасывает контекст: к этому моменту в нём лежат Planning и Plan Review, и тащить их в реализацию дороже, чем перечитать план.» Но в блоке `events.on_enter` шага Test Authoring в обоих файлах стоит только `auto_start_agent` — события `reset_agent_context` там нет, хотя у всех остальных «сброшенных» шагов в тех же файлах оно присутствует явно.
**Почему важно:** Если событие правда отсутствует в переносимом YAML, Test Authoring в Standard и Deep реально продолжает контекст Plan Review (или Planning, если Plan Review не резало), а не начинает с чистого листа. `custom-test-authoring.md` от этого не ломается — он всё равно читает План и `scoping.md` явными вызовами инструментов, — но контекст Implementation (который «тот же, что у Test Authoring») тоже потащит на себе весь разговор Planning + Plan Review, что прямо противоречит причине, ради которой сброс вообще был задуман (стоимость контекста).
**Серьёзность:** стоит поправить
**Предлагаемая правка:** добавить `- type: reset_agent_context` в `on_enter` шага Test Authoring в `standard.yml` и `deep.yml`, перед `auto_start_agent`, по образцу соседних шагов.

### `custom-planning.md`: шапка `Reads` не называет нативный План
**Где:** `kandev/prompts/custom-planning.md:10-11` (шапка) против `custom-planning.md:22-23` (тело) и `HANDOFF-CONTRACT.md:49`
**Что:** Шапка гласит: «Reads: `scoping.md`; `solution-synthesis.md` when the Deep route produced one.» — нативный План не упомянут вовсе. Но первая же секция тела требует: «Call `get_task_plan_kandev` before anything else and read what comes back.» Контракт называет это чтение обязательным: «нативный Plan (обязательно до записи)». Скелет из `PROMPT-WRITING-GUIDE.md:148` прямо говорит, что в `Reads` идут «нативные объекты Kandev», а не только файлы.
**Почему важно:** Шапка — это то место, по которому сверяют контракт и куда смотрят в первую очередь; сейчас она расходится и с телом того же файла, и с таблицей. Функционально роль всё равно прочитает План (тело инструкции работает), но документирующая часть промпта врёт о своих входах.
**Серьёзность:** стоит поправить
**Предлагаемая правка:** добавить в `Reads` шапки пункт про нативный План, например: «Reads: the native Kandev Plan through `get_task_plan_kandev` (read first, before anything else); `scoping.md`; `solution-synthesis.md` when the Deep route produced one.»

### `custom-review-fixes.md` сам себе противоречит в определении «Номера круга»
**Где:** `kandev/prompts/custom-review-fixes.md:99-104` («Which round this is») против `custom-review-fixes.md:118-119` (Artifact shape)
**Что:** Тело говорит: «`Review Fixes` runs once by default and can come back only if a human returns the card... There's no cap enforced here; the number itself is what lets the human judge how many times this has gone around.» — то есть кругов может быть сколько угодно. Но `Artifact shape` определяет поле только для двух значений, слово в слово скопировав формулу `custom-plan-review.md` (у которой круги реально ограничены двумя): «Номер круга — this step's ordinal count on this task: 1 the first time, 2 if your own prior `review-fixes.md` already shows a 1.»
**Почему важно:** Формула не описывает, что писать на третьем и последующих ручных возвратах — а тело явно допускает такие возвраты. Роль на третьем круге останется без инструкции, что писать в это поле.
**Серьёзность:** стоит поправить
**Предлагаемая правка:** заменить формулу на «this step's ordinal count on this task: 1 the first time, otherwise one more than your own prior `review-fixes.md` already shows» — без искусственного потолка в «2».

### `move_task_kandev` описан подробно у Plan Review и вскользь у Final Verification
**Где:** `custom-plan-review.md:93-96` против `custom-final-verification.md:70-71`
**Что:** Plan Review перечисляет обязательные поля вызова: «Call `move_task_kandev` with this task's ID, the current workflow's ID, and the `Planning` step's `workflow_step_id`, and use its `prompt` field for a short hand-off.» Final Verification для той же по сути операции (возврат карточки назад) пишет только: «sends the card back to `Review Fixes` through `move_task_kandev` — but only on the first round» — ни одного поля вызова не названо.
**Почему важно:** Это ровно та пара ролей, которую сам контракт называет «ровно двумя», выполняющими одно и то же действие с разными целями. `PROMPT-WRITING-GUIDE.md` (раздел 3.3) требует точной формы вызова именно там, где роль обязана вызвать инструмент с определёнными полями — здесь одна роль это делает, другая нет, хотя вызывают один и тот же MCP-инструмент.
**Серьёзность:** стоит поправить
**Предлагаемая правка:** добавить в `custom-final-verification.md` аналогичное перечисление полей: task ID, ID текущего воркфлоу, `workflow_step_id` шага `Review Fixes`, `prompt` с коротким письмом.

### `custom-security-review.md` дословно повторяет общее правило о секретах
**Где:** `custom-security-review.md:78-79` против `custom-artifact-protocol.md:64-68`
**Что:** Общий блок уже говорит: «If evidence for something you are recording includes a credential, token, connection string or private key, never reproduce the value. Cite the file and line and mask it.» `custom-security-review.md` пишет почти то же самое своими словами: «Where a finding's evidence is a credential, token, connection string or key, cite `файл:строка` and mask the value, per the general rule on secrets — never reproduce the value itself.» Контракт (`HANDOFF-CONTRACT.md:147-149, 162-163`) прямо относит это правило к списку, который «идёт в `custom-artifact-protocol`, не повторяется в ролях».
**Почему важно:** Дублирование конкретного правила, а не общего стиля — именно то, о чём предупреждает `PROMPT-WRITING-GUIDE.md` (3.2): повтор одного требования в двух местах ослабляет оба, а не усиливает.
**Серьёзность:** стоит поправить
**Предлагаемая правка:** убрать повтор, оставить лишь то, что специфично для роли (что именно в её находках может оказаться секретом), без переформулировки самого правила маскирования.

### Контракт не называет для Review Fixes чтение своего прошлого файла
**Где:** `HANDOFF-CONTRACT.md:56` против `custom-review-fixes.md:8-10`
**Что:** Строка таблицы: «Review Fixes | сброшен | code-review.md, security-review.md, находки в Kandev | review-fixes.md». Колонка «Читает» не включает «свой прошлый review-fixes.md». Но обязательный раздел «Номер круга» (сам контракт, строка про `review-fixes.md` в «Обязательные разделы артефактов») невозможно заполнить корректно, не прочитав прошлый файл — и промпт его читает: «and your own previous `review-fixes.md`, if this task has already been through this step once, so you know which round you're in.»
**Почему важно:** Раздел «Возврат назад при блокирующем исходе» контракта формулирует правило чтения своего прошлого файла только для двух «возвратных» ролей (Plan Review, Final Verification), но по факту оно нужно и Review Fixes, которая не возвращает карточку, но тоже ведёт счётчик. Промпт поступил разумнее таблицы, но по инструкции брифа это всё равно расхождение, о котором надо знать.
**Серьёзность:** стоит поправить
**Предлагаемая правка:** дописать в строку Review Fixes колонки «Читает» контракта: «…, свой прошлый `review-fixes.md`».

### `custom-scoping.md` и `custom-pull-request.md` повторяют общее правило «путь, а не пересказ»
**Где:** `custom-scoping.md:125-127`, `custom-pull-request.md:44-45` против `custom-artifact-protocol.md:36-39`
**Что:** Общий блок: «When you refer to something a previous step established, give the path to its file rather than restating its contents. A path stays true when the file changes; a retelling drifts from it silently…» `custom-scoping.md`: «cite what you're relying on rather than restating Discovery's findings in your own words, since a paraphrase can quietly drift from what was actually found.» `custom-pull-request.md`: «`final-verification.md` for what actually ran, carried over the way it's recorded there rather than restated in your own words». Оба почти дословно воспроизводят логику «пересказ дрейфует» из общего блока.
**Почему важно:** То же ослабление общего правила повтором, что и в находке про секреты — конкретно эта формулировка («путь, а не пересказ, потому что пересказ дрейфует») уже есть в промпте уровня цепочки и подмешивается ко всем шагам без исключения.
**Серьёзность:** стоит поправить
**Предлагаемая правка:** в обоих файлах оставить только собственно ролевую часть требования («на что именно ссылаться» — на `discovery.md`, на `final-verification.md`), убрав переобъяснение того, почему путь лучше пересказа.

---

## Мелочи

### «Номер круга» у Final Verification определён менее буквально, чем у двух других ролей
**Где:** `custom-final-verification.md:67-69, 88` против `custom-plan-review.md:123-124` и `custom-review-fixes.md:118-119`
**Что:** Plan Review и Review Fixes формулируют поле дословно одинаково: «this step's ordinal count on this task: 1 the first time, 2 if your own prior `<file>.md` already shows a 1.» Final Verification вместо этого пишет расплывчато: «Read your own previous `final-verification.md`, if one exists, for the round number it recorded, and record the next one in yours» и в форме артефакта — «Номер круга — the round number described above», без явного стартового значения на первый прогон.
**Почему важно:** Это ровно то, о чём предупреждал бриф — если формат записи разойдётся, роль на повторном прогоне может не опознать собственный прошлый номер, если на первом прогоне что-то, кроме «1», было записано (например, «первый круг» вместо «1»).
**Серьёзность:** мелочь
**Предлагаемая правка:** привести формулировку к тому же виду: «Номер круга — this step's ordinal count on this task: 1 the first time, 2 if your own prior `final-verification.md` already shows a 1.»

### `custom-pull-request.md` ставит `review-fixes.md` в зависимость от маршрута, которого не бывает
**Где:** `custom-pull-request.md:10` против `HANDOFF-CONTRACT.md:58` и всех трёх `kandev/workflows/{quick,standard,deep}.yml`
**Что:** Шапка: «Reads: … and `review-fixes.md`, if the route passed through review, for what changed as a result.» Но во всех трёх маршрутах Review Fixes — обязательный шаг перед Draft PR (комментарий в `quick.yml:131-132`: «Выполняется один раз и может быть пустым, если замечаний нет»), и контракт указывает `review-fixes.md` для Draft PR без всякого «если».
**Почему важно:** Условие звучит так, будто существует маршрут без ревью вовсе — такого маршрута нет ни в одном YAML. Не ломает работу (файл действительно всегда будет на месте), но вводит в заблуждение при чтении промпта отдельно от YAML.
**Серьёзность:** мелочь
**Предлагаемая правка:** убрать «if the route passed through review», читать `review-fixes.md` безусловно.

### Сравнение `final-verification.md` с `verification.md` зависит от необязательной детализации
**Где:** `custom-verification.md` (Artifact shape, «Что запущено, дословный вывод») против `custom-final-verification.md` («Naming a regression»)
**Что:** `custom-final-verification.md` обещает сравнивать «test by test where its output lets you, by overall outcome where it doesn't» — то есть предвидит, что `verification.md` может не дать разбивки по тестам, и деградирует до сравнения по общему исходу либо явно говорит «нет базы для сравнения». Но `custom-verification.md` нигде не требует от себя verbose/поимённого вывода тестов — только «literal terminal output» команды целиком. Регрессия называется регрессией только тогда, когда вывод `verification.md` действительно позволяет узнать конкретный тест по имени.
**Почему важно:** Это не баг стыковки — обе стороны честно предусмотрели неполноту — но надёжность самого важного вывода Final Verification («это регрессия, а не всегда падавший тест») целиком зависит от того, дал ли раннер тестов поимённый вывод, а этого никто не требует явно.
**Серьёзность:** мелочь
**Предлагаемая правка:** можно добавить в `custom-verification.md` фразу вроде «where the test runner supports naming individual tests, prefer the flag that does — a later step compares this output test by test», не вводя числовой критерий или обязательный флаг.

### (низкая уверенность) Заголовок раздела «Вывод прогона» у Test Authoring короче, чем в контракте
**Где:** `custom-test-authoring.md` (Artifact shape) против `HANDOFF-CONTRACT.md:127`
**Что:** Контракт для `test-authoring.md` называет третий раздел «Вывод прогона, показывающий, что тесты падают по нужной причине», промпт даёт заголовок короче: `Вывод прогона`. В части случаев (`targeted-research.md`, `solution-synthesis.md`) контракт даёт полную фразу, и там она дословно совпадает с заголовком раздела в промпте; в других случаях (`code-review.md`, `security-review.md`) похожая по строению приписка в контракте явно не заголовок, а описание. Формат самого контракта непоследователен, поэтому не могу сказать однозначно, ожидался ли здесь заголовок длиннее.
**Почему важно:** Если контракт всё же задаёт заголовки дословно (как в случае `targeted-research.md`), это несовпадение; если нет — находка ложная.
**Серьёзность:** мелочь
**Предлагаемая правка:** либо привести формат контракта к единому виду (заголовок отдельно от описания через тире/скобки везде), либо явно подтвердить, что «Вывод прогона» — весь ожидаемый заголовок.

---

## Проверено и расхождений не найдено

Отмечаю отдельно, раз бриф просил проверить именно эти стыки в первую очередь:

- **Отклонения от плана (Implementation → Verification).** `custom-implementation.md` явно говорит, что передаёт расхождения в текущем контексте, называя точный адрес: «`Verification` follows in the same context and is the one who carries it into `verification.md` under «Отклонения от плана»»; `custom-verification.md` содержит отдельный раздел «Carrying forward «Отклонения от плана»» с тем же названием кириллицей и тем же пониманием механизма («`Implementation` has no artifact of its own, so whatever it flagged... lives only in this session until you write it down»). Совпадает дословно.
- **Предел кругов и поведение на последнем круге (Plan Review / Final Verification).** Обе роли называют одно и то же ограничение — «только один автоматический возврат», обе явно ссылаются друг на друга («This is one of exactly two steps in the whole chain allowed to send a card backward — `Plan Review` is the other»), и обе одинаково описывают действие на втором круге: писать вердикт, называть нерешённое, отдавать карточку дальше человеку. Разошлись только в детализации самого вызова `move_task_kandev` — см. находку выше.
- **`publish_review_findings_kandev` и поведение при нуле находок (Code Review / Security Review).** Пятипунктовый security-чеклист `custom-review-code.md` и список того, что «Code Review уже покрыл», в `custom-security-review.md` совпадают почти слово в слово по всем пяти пунктам (секреты, валидация на границе, инъекции, авторизация, слабая криптография) — явный признак, что файлы сверяли друг с другом. Обе роли одинаково пропускают вызов `publish_review_findings_kandev` при нуле находок и одинаково требуют вместо этого честной записи в собственном вердикте, различающей «чисто» от «не дошли». Единственная асимметрия — `custom-review-code.md` явно упоминает возможность указать диапазон строк для находки, `custom-security-review.md` нет; это слишком мелко, чтобы заводить отдельную находку, но стоит знать.
