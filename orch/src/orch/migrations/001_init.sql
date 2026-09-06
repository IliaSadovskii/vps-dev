-- Схема оркестратора. Четыре таблицы, одна изменяемая (`task`), три только
-- на дозапись. Нет счётчиков (всё, что можно посчитать, считается) и нет
-- производных статусов: «почему ждёт» выводится на проходе движка
-- (research/DB-NOTES.md).

CREATE TABLE task (
    id            TEXT PRIMARY KEY,     -- T12
    chain         TEXT NOT NULL,
    chain_yaml    TEXT NOT NULL,        -- замороженная копия цепочки
    title         TEXT NOT NULL,
    text          TEXT NOT NULL,
    project_path  TEXT NOT NULL,
    branch        TEXT,
    worktree_path TEXT,
    group_path    TEXT,
    step          TEXT,                 -- текущий шаг; NULL до старта и после конца
    status        TEXT NOT NULL,        -- backlog|queued|running|waiting|done|abandoned
    wait_reason   TEXT,                 -- почему стоит: короткий код причины
    human_sheet   TEXT NOT NULL,        -- JSON {шаг: {after, ask}}
    revision      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    closed_at     TEXT,
    archived_at   TEXT
);

CREATE TABLE run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT NOT NULL REFERENCES task(id),
    step          TEXT NOT NULL,
    n             INTEGER NOT NULL,     -- номер захода в этот шаг
    session_id    TEXT,
    context       TEXT NOT NULL,        -- fresh|continue
    started_at    TEXT NOT NULL,
    prompt_sent_at TEXT,
    prompt_sha    TEXT,
    ended_at      TEXT,
    outcome       TEXT,                 -- NULL при ended_at = «нет сигнала»
    start_sha     TEXT,
    end_sha       TEXT,
    duration_s    REAL,
    cost_usd      REAL
);

CREATE UNIQUE INDEX run_task_step_n ON run(task_id, step, n);
CREATE INDEX run_open ON run(task_id) WHERE ended_at IS NULL;

CREATE TABLE move (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL REFERENCES task(id),
    from_step    TEXT,
    to_step      TEXT,
    actor        TEXT NOT NULL,         -- agent|human|engine
    trigger      TEXT NOT NULL,         -- outcome:<x>|button|auto|no_signal|max_runs|error|start
    comment      TEXT,
    artifact_sha TEXT,
    revision     INTEGER NOT NULL,
    delivered_at TEXT,                  -- когда комментарий доехал до роли
    at           TEXT NOT NULL
);

CREATE INDEX move_task ON move(task_id, id);

CREATE TABLE event (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    kind    TEXT NOT NULL,
    payload TEXT,
    at      TEXT NOT NULL
);

CREATE INDEX event_task ON event(task_id, seq);
