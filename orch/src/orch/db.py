"""База задач: SQLite в WAL, единственный писатель — движок.

Схема версионируется `PRAGMA user_version`; миграции — пронумерованные файлы
`migrations/NNN_*.sql`, применяются на старте. Любое изменение задачи —
транзакция с инкрементом `task.revision` (`research/DB-NOTES.md`).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

STATE_DIR = Path.home() / ".local" / "share" / "orch"
DB_PATH = STATE_DIR / "orch.db"
MIGRATIONS = Path(__file__).resolve().parent / "migrations"

# Статусы задачи (`PLAN.md` §3).
BACKLOG, QUEUED, RUNNING, WAITING, DONE, ABANDONED = (
    "backlog", "queued", "running", "waiting", "done", "abandoned"
)
LIVE = (QUEUED, RUNNING, WAITING)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def epoch(value: str | None) -> float | None:
    """Наше время в секунды эпохи. `time.mktime` тут неверен: он считает
    строку местным временем, а мы пишем UTC."""
    if not value:
        return None
    import datetime

    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class EngineLock:
    """Один движок на машину.

    Воркер плагина и запущенный руками `orch-plugin --no-rpc` пишут в одну
    базу; два писателя нарушают главное правило (`PLAN.md` §2, правило 1) и
    ведут одну задачу дважды. Замок — flock на файле рядом с базой: он
    снимается сам, когда процесс умирает, поэтому «забытый замок» невозможен.
    """

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(str(path) + ".lock")
        self.fh = None

    def acquire(self) -> bool:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("w")
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        import os

        self.fh.write(f"{os.getpid()}\n")
        self.fh.flush()
        return True

    def release(self) -> None:
        if self.fh:
            self.fh.close()
            self.fh = None


class Db:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.migrate()

    # ── миграции ─────────────────────────────────────────────────────────
    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        files = sorted(MIGRATIONS.glob("*.sql"))
        for path in files:
            number = int(path.name.split("_", 1)[0])
            if number <= version:
                continue
            # `executescript` ведёт транзакцию сам, поэтому номер версии
            # дописывается в тот же скрипт: применилось всё или ничего.
            script = path.read_text(encoding="utf-8")
            self.conn.executescript(
                f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;"
            )

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Одна транзакция. Всё, что меняет задачу, идёт через неё."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    # ── задачи ───────────────────────────────────────────────────────────
    def next_task_id(self) -> str:
        row = self.conn.execute(
            "SELECT id FROM task WHERE id GLOB 'T[0-9]*' ORDER BY CAST(SUBSTR(id,2) AS INTEGER) DESC LIMIT 1"
        ).fetchone()
        n = int(row["id"][1:]) + 1 if row else 1
        return f"T{n}"

    def task(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()

    def tasks(self, statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            sql = f"SELECT * FROM task WHERE status IN ({marks}) ORDER BY created_at"
            return list(self.conn.execute(sql, statuses))
        return list(self.conn.execute("SELECT * FROM task ORDER BY created_at"))

    def bump(self, task_id: str, **fields) -> int:
        """Изменить задачу и поднять ревизию. Только внутри `tx`."""
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values())
        sql = f"UPDATE task SET {sets + ', ' if sets else ''}revision = revision + 1 WHERE id = ?"
        self.conn.execute(sql, [*values, task_id])
        return self.conn.execute(
            "SELECT revision FROM task WHERE id = ?", (task_id,)
        ).fetchone()["revision"]

    # ── заходы ───────────────────────────────────────────────────────────
    def open_run(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM run WHERE task_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()

    def runs_of_step(self, task_id: str, step: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM run WHERE task_id = ? AND step = ? ORDER BY n",
                (task_id, step),
            )
        )

    def last_run_of_step(self, task_id: str, step: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM run WHERE task_id = ? AND step = ? ORDER BY n DESC LIMIT 1",
            (task_id, step),
        ).fetchone()

    def last_run_of_agent(self, task_id: str, agent_steps: list[str]) -> sqlite3.Row | None:
        """Последняя сессия этого агента в этой задаче (для `context: continue`)."""
        if not agent_steps:
            return None
        marks = ",".join("?" * len(agent_steps))
        return self.conn.execute(
            f"SELECT * FROM run WHERE task_id = ? AND step IN ({marks}) "
            "AND session_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (task_id, *agent_steps),
        ).fetchone()

    def start_run(
        self, task_id: str, step: str, context: str, start_sha: str | None
    ) -> int:
        n = 1 + len(self.runs_of_step(task_id, step))
        cur = self.conn.execute(
            "INSERT INTO run (task_id, step, n, context, started_at, start_sha) "
            "VALUES (?,?,?,?,?,?)",
            (task_id, step, n, context, now(), start_sha),
        )
        return cur.lastrowid

    def end_run(
        self, run_id: int, outcome: str | None, end_sha: str | None, signalled: bool = False
    ) -> None:
        row = self.conn.execute("SELECT started_at FROM run WHERE id = ?", (run_id,)).fetchone()
        started = epoch(row["started_at"]) if row else None
        duration = max(0.0, time.time() - started) if started else None
        self.conn.execute(
            "UPDATE run SET ended_at = ?, outcome = ?, end_sha = ?, duration_s = ?, "
            "signalled = ? WHERE id = ?",
            (now(), outcome, end_sha, duration, int(signalled), run_id),
        )

    def sessions_of_task(self, task_id: str) -> list[str]:
        return [
            r["session_id"]
            for r in self.conn.execute(
                "SELECT DISTINCT session_id FROM run WHERE task_id = ? AND session_id IS NOT NULL",
                (task_id,),
            )
        ]

    # ── движения и журнал ────────────────────────────────────────────────
    def move(
        self,
        task_id: str,
        from_step: str | None,
        to_step: str | None,
        actor: str,
        trigger: str,
        revision: int,
        comment: str | None = None,
        artifact_sha: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO move (task_id, from_step, to_step, actor, trigger, comment, "
            "artifact_sha, revision, at) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, from_step, to_step, actor, trigger, comment, artifact_sha, revision, now()),
        )
        return cur.lastrowid

    def undelivered_comments(self, task_id: str, step: str) -> list[sqlite3.Row]:
        """Комментарии владельца, адресованные этому шагу и ещё не доставленные."""
        return list(
            self.conn.execute(
                "SELECT * FROM move WHERE task_id = ? AND to_step = ? AND comment IS NOT NULL "
                "AND comment != '' AND delivered_at IS NULL ORDER BY id",
                (task_id, step),
            )
        )

    def mark_delivered(self, move_ids: list[int]) -> None:
        for mid in move_ids:
            self.conn.execute("UPDATE move SET delivered_at = ? WHERE id = ?", (now(), mid))

    def moves(self, task_id: str, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM move WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            )
        )

    def event(self, task_id: str | None, kind: str, payload: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO event (task_id, kind, payload, at) VALUES (?,?,?,?)",
            (task_id, kind, json.dumps(payload or {}, ensure_ascii=False), now()),
        )

    def events(self, task_id: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        if task_id:
            return list(
                self.conn.execute(
                    "SELECT * FROM event WHERE task_id = ? ORDER BY seq DESC LIMIT ?",
                    (task_id, limit),
                )
            )
        return list(
            self.conn.execute("SELECT * FROM event ORDER BY seq DESC LIMIT ?", (limit,))
        )
