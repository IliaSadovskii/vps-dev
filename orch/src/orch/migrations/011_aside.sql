-- Побочные роли (`ASIDE-PLAN.md`): агент вне графа цепочки. Стенд был
-- первым таким и жил в полях самой задачи; под четыре роли полей не
-- напасёшься, поэтому одна таблица на всех, а Стенд переезжает в неё.
--
-- `aside` — роль, приставленная к области: заход цепочки, задача, проект,
-- машина. `scope_key` — id задачи, путь проекта или 'machine'.
CREATE TABLE aside (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  scope      TEXT NOT NULL,          -- run | task | project | machine
  scope_key  TEXT NOT NULL,
  task_id    TEXT REFERENCES task(id),
  status     TEXT NOT NULL,          -- live | done | failed
  created_at TEXT NOT NULL,
  ended_at   TEXT
);
-- Живая роль на область ровно одна: два наблюдателя за одним прогоном
-- писали бы друг поверх друга.
CREATE UNIQUE INDEX aside_one_live ON aside (name, scope_key) WHERE status = 'live';

-- Ход побочной роли. `wake` — повод, `cause_seq` — событие, которое его
-- подняло: по нему заход идемпотентен, повтор прохода не заводит второй.
CREATE TABLE aside_run (
  id             INTEGER PRIMARY KEY,
  aside_id       INTEGER NOT NULL REFERENCES aside(id),
  wake           TEXT NOT NULL,
  cause_seq      INTEGER,
  session_id     TEXT,
  started_at     TEXT NOT NULL,
  prompt_sent_at TEXT,
  ended_at       TEXT,
  outcome        TEXT,
  cost_usd       REAL
);
CREATE UNIQUE INDEX aside_run_cause ON aside_run (aside_id, wake, cause_seq)
  WHERE cause_seq IS NOT NULL;

-- Находка: единственный выход побочной роли наружу. `options` — варианты
-- ответа владельцу, каждый со своим глаголом из словаря движка.
CREATE TABLE aside_note (
  id          INTEGER PRIMARY KEY,
  aside_id    INTEGER NOT NULL REFERENCES aside(id),
  run_id      INTEGER REFERENCES aside_run(id),
  task_id     TEXT REFERENCES task(id),
  severity    TEXT NOT NULL,         -- hold | fyi
  title       TEXT NOT NULL,
  body        TEXT,
  options     TEXT,                  -- JSON [{verb, target, label}]
  state       TEXT NOT NULL,         -- open | sent | answered | applied | dropped
  channel_msg TEXT,
  decision    TEXT,
  created_at  TEXT NOT NULL,
  decided_at  TEXT
);

-- Курсор подписки на журнал: докуда роль уже разобрала события.
CREATE TABLE aside_cursor (
  name      TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  seq       INTEGER NOT NULL,
  PRIMARY KEY (name, scope_key)
);

-- Стенд переезжает: сессии живут в `aside_run`, а на задаче остаётся то,
-- что и правда про задачу — нужен ли стенд, чей блок портов, какой порт.
INSERT INTO aside (name, scope, scope_key, task_id, status, created_at)
SELECT 'stand', 'task', id, id, 'live', COALESCE(created_at, datetime('now'))
  FROM task WHERE stand_session IS NOT NULL;
INSERT INTO aside_run (aside_id, wake, session_id, started_at)
SELECT a.id, 'raise', t.stand_session, a.created_at
  FROM task t JOIN aside a ON a.scope_key = t.id AND a.name = 'stand'
 WHERE t.stand_session IS NOT NULL;

INSERT INTO aside (name, scope, scope_key, task_id, status, created_at)
SELECT 'stand-down', 'task', id, id, 'live', COALESCE(stand_teardown_at, datetime('now'))
  FROM task WHERE stand_teardown IS NOT NULL;
INSERT INTO aside_run (aside_id, wake, session_id, started_at)
SELECT a.id, 'teardown', t.stand_teardown, a.created_at
  FROM task t JOIN aside a ON a.scope_key = t.id AND a.name = 'stand-down'
 WHERE t.stand_teardown IS NOT NULL;

ALTER TABLE task DROP COLUMN stand_session;
ALTER TABLE task DROP COLUMN stand_teardown;
ALTER TABLE task DROP COLUMN stand_teardown_at;
