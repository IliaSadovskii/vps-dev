-- Ход побочной роли помнит, о какой задаче он был. У ролей с областью
-- «проект» запись одна на весь проект, и бюджет «ходов на задачу» считался
-- по всей записи: Менеджер замолчал бы навсегда после четвёртой задачи.
ALTER TABLE aside_run ADD COLUMN task_id TEXT;
UPDATE aside_run SET task_id = (
  SELECT a.task_id FROM aside a WHERE a.id = aside_run.aside_id
) WHERE task_id IS NULL;
