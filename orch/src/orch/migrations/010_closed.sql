-- Снятая задача — свой статус, а не `done` с пометкой в `wait_reason`:
-- поле причины остановки не место для судьбы задачи, и каждый читатель
-- (панель, статистика, архив) вынужден был помнить про пометку.
UPDATE task
   SET status = 'closed', wait_reason = NULL
 WHERE status = 'done' AND wait_reason = 'closed_by_owner';
