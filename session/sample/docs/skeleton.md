# Каркас

Таблица забот к оглавлению «Каркас» в `../AGENTS.md`: образец — путь в коде, правило — одна строка (подробности — `rules/<область>.md` и ADR), проверка — тест или скрипт. Пути, проверки и совпадение с оглавлением держит `scripts/check-agents.sh`.

Новая забота — строка здесь и её имя в оглавлении тем же PR. Каркас — подсказка, правда — код.

## Каркас

| Забота | Образец | Правило | Проверка |
|---|---|---|---|
| Границы модулей | `app/Domain/Bookings/` | домен не знает про HTTP и консоль | `tests/Arch/ArchitectureTest.php` «домен не знает про HTTP» |
| Лайаут и навигация | `resources/js/layouts/AppLayout.vue` | страница не рисует шапку и меню сама | ревью |
| Состояния экрана | `resources/js/pages/Rooms/Index.vue` | loading, empty, error, «нет прав» у каждой страницы | `tests/Browser/RoomsIndexTest.php` |
| Формы и ошибки полей | `resources/js/components/ui/AppField.vue` | ошибка стоит у поля, форма не сбрасывается | ревью |
| Уведомления | — | один способ на весь UI, живёт в лайауте; страница свой не заводит | — |
| Права | `app/Domain/Bookings/Policies/BookingPolicy.php` | решает политика; кнопка скрыта по той же политике | `tests/Feature/Bookings/BookingPolicyTest.php` |
| Пересечения и транзакции | `app/Domain/Bookings/Actions/SaveBooking.php` | пересечение слотов запрещает база, код переводит ошибку в текст | `tests/Feature/Bookings/OverlapTest.php` |
| Время и пояс | `app/Domain/Shared/Values/Slot.php` | хранение в UTC, показ в поясе компании | `tests/Unit/SlotTest.php` |
| Экспорт | — | решить при первой задаче, которая потребует выгрузки | — |
| Письма | `app/Domain/Bookings/Listeners/SendBookingCreated.php` | письмо — из события домена, не из контроллера | `tests/Feature/Bookings/NotificationTest.php` |
