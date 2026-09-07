-- Уборкой стенда занимается роль в своей сессии, а движок за ней проверяет.
-- `stand_teardown` — сессия уборщика, `stand_teardown_at` — когда её позвали:
-- по этому времени движок понимает, что пора добить остатки самому.
ALTER TABLE task ADD COLUMN stand_teardown TEXT;
ALTER TABLE task ADD COLUMN stand_teardown_at TEXT;
