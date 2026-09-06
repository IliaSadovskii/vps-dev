-- Задачи, снятые кнопкой до того, как появилась пометка «снята, а не
-- сделана». Без неё они стоят в разделе «Готово» рядом с настоящей работой
-- и читаются как достижения. Признак снятия — событие `closed` в журнале.
UPDATE task
   SET wait_reason = 'closed_by_owner'
 WHERE status = 'done'
   AND wait_reason IS NULL
   AND id IN (SELECT task_id FROM event WHERE kind = 'closed');
