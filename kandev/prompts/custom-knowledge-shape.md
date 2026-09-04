The shape of a project's product description — `docs/knowledge/` — as the
`Blueprint` role writes it and the development chain reads it.

Eight files, one per kind of thing the product is made of. Each file opens
with a comment that says what belongs there, the `fields:` every record
answers, the key convention and the bar for the file being done. That
header is the definition: a record is complete when every field its file
declares has content, and every key it names exists in its own file.

The files are written in the language of the project's own documentation
— Russian unless the project's README and docs are in English — and the
headings and field labels below are translated together with the prose.
What never gets translated: `key:`, `state:`, `walked:`, `derived`,
`entry_point`, `[assumed …]`, and the state names `planned`, `building`,
`built`. A later role finds records by these marks, and a mark in two
languages is two marks.

## Marks every file uses

- **Slot verdict** — the first line under the title, one of
  `Состояние: заполнен`, `Состояние: не применимо — <причина>`,
  `Состояние: открытый вопрос — <что неизвестно>`. A slot the product
  does not need is closed with a reason, not filled with invention: a
  reader is careful around a gap and confident around a wrong answer.
- **Key** — the line right under a record's heading, in backticks:
  `` `key: developer.create_offer` ``. Keys are lowercase English slugs
  whatever the prose language. Every key a record names — actor, entity,
  status, screen, action — must exist in its own file.
- **State** — on the same line for actions, screens and integrations:
  `` `key: …` · `state: planned` ``. `planned` — nothing built;
  `building (pr: N)` — a pull request is open for it; `built` — the code
  exists (not that it works: scenarios answer that). `Blueprint` writes
  `planned`, or `built` only for what it read in the code in this very
  turn. Moving `planned` to `building` and `built` is not this role's
  job and is not done yet by anyone.
- **`[assumed <date>] …`** — a line under a record, for what the
  description did not say and the writer decided instead of asking. It
  is the decision of record until the owner changes it; deleting the
  line is the resolution, and only `Blueprint` may delete it. Left where
  being wrong costs something — stored data, who may and may not, money,
  a contract outside this codebase — or where confidence was low. Not
  for mechanics: how something is stored or layered is never a block.
- **Fields with a list** — a field's answer may be a list on the lines
  below the label; the field is filled when that list has content.

## The eight files

### `product.md`

```markdown
# Продукт

<!--
Что это и чего оно намеренно не делает. Первый раздел — рассказ владельца,
близко к его словам, не причёсанный пересказ: по нему проверяется всё
остальное («вы упомянули агентства — актора такого нет»). Части — то, о
чём владелец может рассказать за несколько минут и у чего свой словарь;
обычно пять–десять. Метка части: `walked: <дата>` — владелец рассказал,
`derived` — выведено из кода и документов и не подтверждено.
Границы MVP — два явных списка; «и так далее» границей не считается.
Готово, когда: исполнитель, прочитав файл, знает, что строить, для кого и
чего не строить, не спрашивая.
-->

Состояние: заполнен

## Как владелец описывает продукт

## Части
<!-- по строке: название — что покрывает — метка -->
- вход и аккаунт — регистрация, вход, выход — `walked: 2026-09-04`
- карта тем — прогресс по узлам — `derived`

## Для чего
<!-- одно-два предложения; каждое позднее решение сверяется с ними -->

## Чего намеренно не делает
<!-- по строке -->

## Тип приложения
<!-- веб-приложение и API, монолит, мобильное, CLI, библиотека, только
     API, конвейер данных. Какие файлы описания к нему применимы -->

## Окружение и ограничения
<!-- где работает; что задаёт форму: офлайн, права, задержки, объёмы -->

## Границы MVP
**Входит:**
**Не входит:**
```

### `actors.md`

```markdown
# Акторы

<!--
Все, кто и что запускает действие: роль пользователя, оператор CLI,
внешняя система, расписание, сам продукт. Так описание работает и для
библиотеки, и для конвейера.
fields: Появляется, Может, Никогда не может
Ключ: короткий слаг — developer, buyer, scheduler, payment_gateway.
Готово, когда: у каждого актора из рассказа есть запись, и у каждого
актора есть хотя бы одно действие в actions.md.
-->

Состояние: заполнен

### Застройщик
`key: developer`

**Появляется:** регистрируется, модератор проверяет
**Может:** публиковать лоты, отвечать на запросы покупателей
**Никогда не может:** видеть чужие предложения по тому же запросу
```

### `entities.md`

```markdown
# Сущности

<!--
Что живёт дольше одного вызова и в каких состояниях бывает. Состояния и
переходы — главное: действие, ставящее статус, которого сущность не
называет, — дефект, и это видно только если состояния записаны.
fields: Что это, Состояния, Переходы, Связи, Инварианты
Ключ: существительное в единственном числе — offer, request, lot.
Готово, когда: у каждой сущности перечислены состояния, кто её между
ними переводит, и инварианты, которые держатся при любом исходе.
-->

Состояние: заполнен

### Предложение
`key: offer`

**Что это:** ответ застройщика на запрос покупателя, привязан к лоту
**Состояния:** pending, accepted, rejected, withdrawn, expired
**Переходы:** pending → accepted покупателем; pending → withdrawn
застройщиком; pending → expired расписанием через 14 дней
**Связи:** принадлежит одному запросу и одному лоту; у застройщика не
больше одного живого предложения на запрос
**Инварианты:** принятое предложение закрывает запрос; истёкшее не
оживает
```

### `actions.md`

```markdown
# Действия

<!--
Что делают акторы — единица работы. Фича — небольшая связная группа
действий и экраны, с которых они достижимы. У каждой записи состояние:
planned — не построено; building (pr: N) — открыт пул-реквест; built —
код есть (работает ли — отвечают сценарии).
fields: Кто, Триггер, Предусловия, Что происходит, Что меняется, Видит
инициатор, Видят другие, Что может пойти не так, Откуда достижимо
Ключ: actor.verb_object — developer.create_offer, scheduler.expire_offers.
Готово, когда: перечислено каждое действие каждого актора, все поля
отвечены, и каждый названный ключ — актор, сущность, статус, экран —
существует в своём файле.
-->

Состояние: заполнен

### Застройщик создаёт предложение
`key: developer.create_offer` · `state: planned`

**Кто:** developer
**Триггер:** видит запрос покупателя, подходящий под его лот
**Предусловия:** запрос активен; у застройщика нет живого предложения
**Что происходит:** выбирает лот, называет цену и срок, отправляет
**Что меняется:** создаётся offer в `pending`; счётчик у запроса растёт
**Видит инициатор:** предложение в своём списке с пометкой «ждёт ответа»
**Видят другие:** покупатель получает уведомление и видит предложение
**Что может пойти не так:** запрос отменили, пока форма была открыта
**Откуда достижимо:** `screen.request_detail`
[assumed 2026-09-04] срок предложения — 14 дней, владелец не называл
```

### `screens.md`

```markdown
# Экраны

<!--
Поверхность, через которую человек доходит до действия. Переходы
называют ключи действий. У экрана своё состояние, как у действия: экран
может быть построен без нового действия за ним. Экран, с которого
продукт открывается, приходит ниоткуда: в «Откуда пришли» пишется
`entry_point`. Если у продукта нет интерфейса — «не применимо» с
причиной, а не выдуманные записи.
fields: Для кого, Зачем, На экране, Откуда пришли, Куда ведёт
Ключ: screen.<slug>.
Готово, когда: перечислен каждый экран, у каждого названо, откуда на
него приходят и куда уходят, и каждый ключ действия в переходе есть в
actions.md.
-->

Состояние: заполнен

### Список предложений
`key: screen.offers_list` · `state: planned`

**Для кого:** developer, buyer
**Зачем:** увидеть предложения по запросу
**На экране:** карточки предложений, фильтр по статусу, пустое состояние
**Откуда пришли:** `screen.requests`, открыв запрос
**Куда ведёт:** `screen.offer_detail` через `developer.open_offer`;
назад в `screen.requests`
```

### `integrations.md`

```markdown
# Интеграции

<!--
Внешние системы, от которых продукт зависит. Значения секретов не
записываются никогда — только имена переменных окружения.
fields: Что это, Отправляем, Получаем, Когда недоступно, Секреты
Ключ: integration.<slug>.
Готово, когда: у каждой внешней системы есть запись, и в каждой сказано,
что происходит, когда она недоступна.
-->

Состояние: заполнен

### Платёжный провайдер
`key: integration.payments` · `state: planned`

**Что это:** размещённая касса — покупатель платит там и возвращается
**Отправляем:** сумму, номер заказа, адрес возврата
**Получаем:** вебхук с результатом платежа
**Когда недоступно:** сделка остаётся в `awaiting_payment`; покупатель
видит «повторить», ничего не теряется; вебхук идемпотентен по заказу
**Секреты:** `PAYMENTS_KEY`, `PAYMENTS_WEBHOOK_SECRET`
```

### `scenarios.md`

```markdown
# Сценарии

<!--
Восемь–десять сквозных проходов на настоящих именах и числах, нарочно
через несколько частей продукта. Так проверяется полнота: там, где
честный ответ на шаге — «ну, добавим ещё поле», описание неверно, и
это видно за пять минут, а не за пять недель. Шаги называют ключи
действий: сценарий, упоминающий действие, которого никто не записал, —
находка. Концовка — всегда ответ владельца, не догадка. Сквозной тест,
проходящий сценарий целиком, помечается комментарием
`kandev:scenario <заголовок сценария>`.
fields: Кто, Исходная точка, Шаги, Чем заканчивается
Готово, когда: пройдены основные пути через продукт, включая хотя бы
один, где что-то идёт не так.
-->

Состояние: заполнен

### Анна получает предложение и принимает его

**Кто:** Анна, покупатель
**Исходная точка:** опубликовала запрос на двушку до 12 млн
**Шаги:**
1. `developer.create_offer` — «Север» предлагает квартиру за 11,4 млн
2. `buyer.open_offer` — Анна открывает его с экрана запроса
3. `buyer.accept_offer` — принимает; предложение уходит в `accepted`
4. запрос закрывается, два других `pending` уходят в `rejected`
**Чем заканчивается:** сделка в `draft`, обе стороны уведомлены
```

### `stack.md`

```markdown
# Стек

<!--
На чём это построено и по каким правилам строится. Выводится из кода и
манифестов, владелец правит и добавляет то, что знает только он. Каждое
правило — одна строка с причиной: правило без причины игнорируют или
применяют не там. Команды запуска, тестов и линтера, версии и раскладка
живут в AGENTS.md проекта — здесь на них ссылка, а не копия. Тип
приложения — в product.md.
Готово, когда: исполнитель может строить внутри этого, не спрашивая:
знает, какие версии, какие паттерны, где искать готовое, чего проект не
делает, и чем прогоняются сценарии от начала до конца.
-->

Состояние: заполнен

## Версии
<!-- языки, фреймворк, пакетный менеджер — из lock-файлов; если это уже
     в AGENTS.md, одна строка со ссылкой на раздел -->

## Принципы
<!-- правила владельца, по строке с причиной -->

## Решения по областям
<!-- слои, валидация, ошибки, фоновая работа, доступ к данным — по
     строке, с «почему»; выведено из кода, поправлено владельцем -->

## Карта библиотек
<!-- готовый ответ экосистемы на каждую задачу: пакет и что закрывает,
     чтобы исполнитель брал его, а не писал своё -->

## Чем гоняются сценарии
<!-- инструмент и где он запускается, или прямо: «инструмента нет,
     сценарии проверяются руками». Это единственная строка здесь, которую
     нельзя вывести из кода: несуществующий прогон невидим, и молчание
     позже читается как «решили не проверять» -->

## Чего не делаем
<!-- антипаттерны именно этого проекта -->
```

## Cross-checks a reader can do without a program

Every key named anywhere resolves to a record. An actor with no action, an
entity nothing creates, a screen nothing leads to that is not an
`entry_point` — each is an orphan and is a finding, not a style issue. A
scenario step naming an action nobody wrote is a finding. A status an
action sets that its entity does not list is a finding. Empty fields are
counted, not hidden. These are what `Blueprint` checks by reading before
it commits, and what a later role may name in its own artifact without
fixing — only `Blueprint` writes prose into these files.
