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

from .clock import epoch, now, now_precise  # noqa: F401 — реэкспорт для соседей

STATE_DIR = Path.home() / ".local" / "share" / "orch"
DB_PATH = STATE_DIR / "orch.db"
# Заявки от `orch` из сессий и терминала: движок читает их на каждом проходе.
INBOX = STATE_DIR / "inbox"
MIGRATIONS = Path(__file__).resolve().parent / "migrations"

# Статусы задачи (`PLAN.md` §3). `closed` — снята владельцем, работа не
# делалась; `done` — доведена до конца.
BACKLOG, QUEUED, RUNNING, WAITING, DONE, CLOSED, ABANDONED = (
    "backlog", "queued", "running", "waiting", "done", "closed", "abandoned"
)
LIVE = (QUEUED, RUNNING, WAITING)
FINISHED = (DONE, CLOSED)

# Причины остановки. Код лежит в `task.wait_reason`, текст рисует панель.
WAIT_REASONS = {
    "gate": "ворота: ждёт вашего решения",
    "no_signal": "роль закончила ход, не подав сигнал",
    "max_runs": "предел заходов на шаг",
    "loops": "роли гоняют задачу по кругу",
    "error": "сессия в ошибке",
    "ask": "роль спрашивает вас",
    "bad_outcome": "роль назвала исход не из списка",
    "chain_broken": "замороженная цепочка не читается",
    "path_mismatch": "рабочая копия сессии не совпала с задачей",
    "no_worker": "у сессии не поднялся воркер агента",
    "no_worktree": "не удалось создать рабочую копию задачи",
    "branch_busy": "ветку задачи держит другая рабочая копия",
    "artifact": "роль сдала ход, но её файла нет или он не той формы",
    "abandoned": "сессия задачи исчезла",
    "aside_hold": "побочная роль просит вас посмотреть",
}


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
            "AND session_id IS NOT NULL AND void_at IS NULL ORDER BY id DESC LIMIT 1",
            (task_id, *agent_steps),
        ).fetchone()

    def runs_after(self, task_id: str, at: str) -> list[sqlite3.Row]:
        """Заходы задачи, начатые строго позже момента `at`."""
        return list(
            self.conn.execute(
                "SELECT * FROM run WHERE task_id = ? AND started_at > ? ORDER BY id",
                (task_id, at),
            )
        )

    def void_run(self, run_id: int) -> None:
        """Забыть заход: его сессию не подхватит шаг с памятью, а его заходы
        не считаются пределом. Строка остаётся — путь задачи по шагам
        переписывать задним числом нельзя."""
        self.conn.execute(
            "UPDATE run SET void_at = ? WHERE id = ? AND void_at IS NULL", (now(), run_id)
        )

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
        # Событие пишется здесь, а не в пяти местах движка: конец захода —
        # повод проснуться для побочных ролей (`ASIDE-PLAN.md` §2), и
        # забыть его в новом месте закрытия было бы нечем поймать.
        row = self.conn.execute(
            "SELECT task_id, step, n FROM run WHERE id = ?", (run_id,)
        ).fetchone()
        if row is not None:
            self.event(
                row["task_id"],
                "run_ended",
                {
                    "run": run_id,
                    "step": row["step"],
                    "n": row["n"],
                    "outcome": outcome,
                    "signalled": bool(signalled),
                    "duration_s": round(duration) if duration else None,
                },
            )

    def prompt_sent(self, run_id: int, session_id: str | None = None, prompt_sha: str | None = None) -> None:
        """Промпт ушёл в сессию — сейчас.

        Зовётся и при первом промпте захода, и при каждом повторном
        («заверши ход», «продолжай», побудка воркера): конец хода считается
        от последней отправки, иначе старый `Idle` сойдёт за новый
        (`aoe.Session.turn_ended`).
        """
        sets = ["prompt_sent_at = ?"]
        values: list = [now_precise()]
        if session_id is not None:
            sets.append("session_id = ?")
            values.append(session_id)
        if prompt_sha is not None:
            sets.append("prompt_sha = ?")
            values.append(prompt_sha)
        self.conn.execute(f"UPDATE run SET {', '.join(sets)} WHERE id = ?", [*values, run_id])

    def run_events(self, task_id: str, kind: str, run_id: int) -> list[sqlite3.Row]:
        """События захода: у повторяемых действий (побудка, «продолжай»)
        счётчик — это число событий, а не поле."""
        return list(
            self.conn.execute(
                "SELECT * FROM event WHERE task_id = ? AND kind = ? AND payload LIKE ? ORDER BY seq",
                (task_id, kind, f'%"run": {run_id}%'),
            )
        )

    def sessions_of_task(self, task_id: str) -> list[str]:
        return [
            r["session_id"]
            for r in self.conn.execute(
                "SELECT DISTINCT session_id FROM run WHERE task_id = ? AND session_id IS NOT NULL",
                (task_id,),
            )
        ]

    # ── побочные роли ────────────────────────────────────────────────────
    def aside_open(self, name: str, scope: str, scope_key: str, task_id: str | None) -> int:
        """Найти живую роль на этой области или завести её."""
        row = self.conn.execute(
            "SELECT id FROM aside WHERE name = ? AND scope_key = ? AND status = 'live'",
            (name, scope_key),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        cur = self.conn.execute(
            "INSERT INTO aside (name, scope, scope_key, task_id, status, created_at) "
            "VALUES (?,?,?,?,'live',?)",
            (name, scope, scope_key, task_id, now()),
        )
        return int(cur.lastrowid)

    def aside(self, aside_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM aside WHERE id = ?", (aside_id,)).fetchone()

    def aside_live(self, name: str, scope_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM aside WHERE name = ? AND scope_key = ? AND status = 'live'",
            (name, scope_key),
        ).fetchone()

    def asides_live(self, name: str | None = None) -> list[sqlite3.Row]:
        if name:
            return list(self.conn.execute(
                "SELECT * FROM aside WHERE status = 'live' AND name = ? ORDER BY id", (name,)
            ))
        return list(self.conn.execute(
            "SELECT * FROM aside WHERE status = 'live' ORDER BY id"
        ))

    def aside_close(self, aside_id: int, status: str = "done") -> None:
        self.conn.execute(
            "UPDATE aside SET status = ?, ended_at = ? WHERE id = ?", (status, now(), aside_id)
        )

    def aside_run_start(
        self,
        aside_id: int,
        wake: str,
        cause_seq: int | None,
        token: str = "",
        task_id: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO aside_run (aside_id, wake, cause_seq, started_at, token, task_id) "
            "VALUES (?,?,?,?,?,?)",
            (aside_id, wake, cause_seq, now(), token or None, task_id),
        )
        return int(cur.lastrowid)

    def aside_run(self, run_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM aside_run WHERE id = ?", (run_id,)
        ).fetchone()

    def aside_run_open(self, aside_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM aside_run WHERE aside_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (aside_id,),
        ).fetchone()

    def aside_runs_open(self) -> list[sqlite3.Row]:
        """Все незакрытые побочные ходы: за ними следит проход движка."""
        return list(self.conn.execute(
            "SELECT r.*, a.name, a.scope, a.scope_key, a.task_id FROM aside_run r "
            "JOIN aside a ON a.id = r.aside_id WHERE r.ended_at IS NULL ORDER BY r.id"
        ))

    def aside_runs_in_sessions(self, sids: list[str]) -> list[sqlite3.Row]:
        """Закрытые ходы, чьи сессии ещё живы в сайдбаре.

        Нужно уборке: сессия повода живёт один ход, и после сдачи её карточка
        уходит в архив. Список живых сессий даёт AoE, поэтому убранные сюда
        уже не попадают и второй раз не архивируются.
        """
        if not sids:
            return []
        места = ", ".join("?" * len(sids))
        return list(self.conn.execute(
            "SELECT r.*, a.name, a.session_id AS aside_session FROM aside_run r "
            "JOIN aside a ON a.id = r.aside_id "
            f"WHERE r.ended_at IS NOT NULL AND r.session_id IN ({места}) ORDER BY r.id",
            sids,
        ))

    def aside_run_sent(self, run_id: int, session_id: str | None = None) -> None:
        sets, values = ["prompt_sent_at = ?"], [now_precise()]
        if session_id is not None:
            sets.append("session_id = ?")
            values.append(session_id)
        self.conn.execute(
            f"UPDATE aside_run SET {', '.join(sets)} WHERE id = ?", [*values, run_id]
        )

    def aside_run_end(self, run_id: int, outcome: str | None, cost: float | None = None) -> None:
        self.conn.execute(
            "UPDATE aside_run SET ended_at = ?, outcome = ?, cost_usd = ? WHERE id = ?",
            (now(), outcome, cost, run_id),
        )

    def aside_runs_of(self, aside_id: int, task_id: str | None = None) -> list[sqlite3.Row]:
        """Ходы роли: все или только про эту задачу.

        У ролей с областью «проект» запись одна на весь проект, поэтому
        бюджет «ходов на задачу» считается по задаче, а не по записи.
        """
        if task_id:
            return list(self.conn.execute(
                "SELECT * FROM aside_run WHERE aside_id = ? AND task_id = ? ORDER BY id",
                (aside_id, task_id),
            ))
        return list(self.conn.execute(
            "SELECT * FROM aside_run WHERE aside_id = ? ORDER BY id", (aside_id,)
        ))

    # ── находки ──────────────────────────────────────────────────────────
    def note_add(
        self,
        aside_id: int,
        run_id: int | None,
        task_id: str | None,
        severity: str,
        title: str,
        body: str,
        options: list[dict],
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO aside_note (aside_id, run_id, task_id, severity, title, body, "
            "options, state, created_at) VALUES (?,?,?,?,?,?,?,'open',?)",
            (
                aside_id, run_id, task_id, severity, title, body,
                json.dumps(options, ensure_ascii=False), now(),
            ),
        )
        return int(cur.lastrowid)

    def note(self, note_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM aside_note WHERE id = ?", (note_id,)
        ).fetchone()

    def notes(self, state: str | None = None, task_id: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM aside_note WHERE 1=1"
        args: list = []
        if state:
            sql += " AND state = ?"
            args.append(state)
        if task_id:
            sql += " AND task_id = ?"
            args.append(task_id)
        return list(self.conn.execute(sql + " ORDER BY id", args))

    def note_state(self, note_id: int, state: str, **fields) -> None:
        sets = ["state = ?"]
        values: list = [state]
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            values.append(value)
        self.conn.execute(
            f"UPDATE aside_note SET {', '.join(sets)} WHERE id = ?", [*values, note_id]
        )

    # ── курсор подписки ──────────────────────────────────────────────────
    def cursor_of(self, name: str, scope_key: str) -> int:
        """Докуда роль разобрала журнал. `-1` — курсора ещё нет вовсе.

        Ноль от «нет курсора» отличается: на чистой базе журнал начинается
        с первого события, и потерять его нельзя.
        """
        row = self.conn.execute(
            "SELECT seq FROM aside_cursor WHERE name = ? AND scope_key = ?", (name, scope_key)
        ).fetchone()
        return int(row["seq"]) if row else -1

    def cursor_set(self, name: str, scope_key: str, seq: int) -> None:
        self.conn.execute(
            "INSERT INTO aside_cursor (name, scope_key, seq) VALUES (?,?,?) "
            "ON CONFLICT(name, scope_key) DO UPDATE SET seq = excluded.seq",
            (name, scope_key, seq),
        )

    def events_after(self, seq: int, kinds: tuple[str, ...], limit: int = 200) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(kinds))
        return list(self.conn.execute(
            f"SELECT * FROM event WHERE seq > ? AND kind IN ({marks}) ORDER BY seq LIMIT ?",
            (seq, *kinds, limit),
        ))

    def last_seq(self) -> int:
        row = self.conn.execute("SELECT MAX(seq) AS s FROM event").fetchone()
        return int(row["s"] or 0)

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

    def path_steps(self, task_id: str) -> list[str]:
        """Путь задачи по шагам из движений; повторный вход помечен `⟲`.

        Одна функция на промпт («Где ты») и на панель («Путь задачи»): два
        экземпляра одного алгоритма разошлись бы при первой правке.
        """
        steps = [
            m["to_step"]
            for m in reversed(self.moves(task_id, limit=40))
            if m["to_step"] and m["to_step"] != "done"
        ]
        out: list[str] = []
        seen: set[str] = set()
        for s in steps:
            if out and out[-1].lstrip("⟲ ") == s:
                continue
            out.append(f"⟲ {s}" if s in seen else s)
            seen.add(s)
        return out

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
