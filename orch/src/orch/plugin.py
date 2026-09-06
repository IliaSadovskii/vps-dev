"""Воркер плагина AoE: движок оркестратора и панели.

Один процесс, две обязанности: проход движка раз в `poll_secs` и перерисовка
панелей из состояния базы. Панели — чистые функции (`panels.py`), кнопки
несут ревизию задачи; всё, что кнопка меняет, идёт через `Engine.button`,
поэтому писатель базы остаётся один.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from pathlib import Path

from . import panels
from .chain import ChainError, chains_dir, load as load_chain
from .engine import _title_from as _title_of
from .db import Db, EngineLock
from .engine import Engine, Settings
from .rpc import Rpc, RpcError, log

PLUGIN_ID = "dev.sadovskii.orch"
STATE_DIR = Path.home() / ".local" / "share" / "orch"


class Worker:
    def __init__(self) -> None:
        self.rpc = Rpc(self.handle)
        self.started = time.time()
        self.settings: dict = {}
        self.engine: Engine | None = None
        self.lock: EngineLock | None = None
        # Что уже нарисовано: перерисовываем только при смене ревизии, чтобы
        # не гонять 64 КиБ каждые пять секунд.
        self.drawn: dict[tuple[str, str], str] = {}
        self.session_of_task: dict[str, str] = {}
        # Клик приходит в своём потоке (иначе воркер запирает сам себя на
        # ответе хоста), а соединение SQLite привязано к потоку, в котором
        # создано. Поэтому всё, что трогает базу, кладётся в очередь и
        # исполняется в потоке движка; `wake` будит его сразу, без ожидания
        # следующего опроса.
        self.pending: queue.Queue[tuple[str, str, dict]] = queue.Queue()
        self.wake = threading.Event()

    # ── входящие вызовы хоста ────────────────────────────────────────────
    def handle(self, method: str, params: dict):
        tail = method.rsplit(".", 1)[-1]
        if method == "plugin.settings.changed":
            self.read_settings()
            self.push_all(force=True)
            return {}
        if method == "plugin.command.invoke" or tail == "status":
            return {"ok": True, "message": self.status_line()}
        if method.startswith("orch."):
            self.on_action(tail, params)
            return {}
        log(f"orch-plugin: неизвестный метод {method}")
        return NotImplemented

    def status_line(self) -> str:
        if self.engine is None:
            return "orch: панели рисую, задачи двигает другой процесс"
        db = self.engine.db
        return (
            f"orch: ждут вас {len(db.tasks(('waiting',)))}, "
            f"едут {len(db.tasks(('running',)))}, "
            f"в очереди {len(db.tasks(('queued',)))}"
        )

    def on_action(self, action: str, params: dict) -> None:
        session_id = params.get("session_id") or ""
        log(f"orch-plugin: кнопка {action} {json.dumps(params, ensure_ascii=False)[:300]}")
        if getattr(self, f"btn_{action}", None) is None:
            log(f"orch-plugin: кнопки {action} нет")
            return
        self.pending.put((action, session_id, params))
        self.wake.set()

    def drain_actions(self) -> bool:
        """Исполнить накопленные клики в потоке движка. True — что-то было."""
        did = False
        while True:
            try:
                action, session_id, params = self.pending.get_nowait()
            except queue.Empty:
                return did
            did = True
            try:
                getattr(self, f"btn_{action}")(session_id, params)
            except Exception as exc:  # noqa: BLE001 — клик не роняет воркер
                log(f"orch-plugin: кнопка {action} упала: {exc!r}")
                self.notify("orch", f"кнопка не сработала: {exc}", tone="danger")

    # ── кнопки задачи ────────────────────────────────────────────────────
    def _move(self, params: dict, action: str) -> None:
        if self.engine is None:
            self.notify("orch", "движок ведёт другой процесс", tone="warn")
            return
        task_id = params["task"]
        comment = params.get("comment") or self.comments.pop(task_id, None)
        answer = self.engine.button(
            task_id, params["revision"], action, params.get("target"), comment
        )
        self.notify(f"{task_id}: {answer}", comment[:120] if comment else None)

    def btn_accept(self, session_id, params): self._move(params, "accept")
    def btn_accept_as_is(self, session_id, params): self._move(params, "accept")
    def btn_again(self, session_id, params): self._move(params, "again")
    def btn_back(self, session_id, params): self._move(params, "back")
    def btn_start(self, session_id, params): self._move(params, "start")
    def btn_close(self, session_id, params): self._move(params, "close")

    def btn_sheet_step(self, session_id, params) -> None:
        """Клик по строке листа задачи: ворота → вопросы → и то и другое → ничего."""
        if self.engine is None:
            return
        db = self.engine.db
        task = db.task(params["task"])
        if task is None or int(params["revision"]) != int(task["revision"]):
            return
        sheet = json.loads(task["human_sheet"] or "{}")
        knobs = sheet.setdefault(params["step"], {"after": False, "ask": True})
        after, ask = bool(knobs.get("after")), bool(knobs.get("ask"))
        after, ask = _next_knobs(after, ask)
        knobs["after"], knobs["ask"] = after, ask
        with db.tx():
            db.bump(task["id"], human_sheet=json.dumps(sheet, ensure_ascii=False))
            db.event(task["id"], "sheet_edited", {"step": params["step"], **knobs})

    def btn_wizard(self, session_id, params) -> None:
        """«Новая задача» и «В работу»: разговор вместо листа переключателей.

        Панель не умеет ни поля ввода, ни дропдауна, поэтому цепочку, ветку и
        автономию спрашивает мастер в чате (`UX-PLAN.md`).
        """
        if self.engine is None:
            self.notify("orch", "движок ведёт другой процесс", tone="warn")
            return
        task_id = params.get("task")
        project = params.get("project")
        if task_id:
            task = self.engine.db.task(task_id)
            if task is None or int(params.get("revision", -1)) != int(task["revision"]):
                return
            project = task["project_path"]
        if not project:
            project = self._project_of_session(session_id)
        if not project:
            self.notify("orch", "не понял, в каком проекте задача", tone="warn")
            return
        sid = self.engine.open_wizard(project, task_id, params.get("mode") or "start")
        if sid is None:
            self.notify("orch", "мастер не открылся, смотрите журнал", tone="danger")
            return
        self.notify(
            "orch: мастер задачи открыт",
            "он в сайдбаре, группа «orch/мастер» — отвечайте ему в чате",
        )

    def btn_focus(self, session_id, params) -> None:
        """Строка ждущей задачи в общей панели: ничего не меняет, только жест."""

    # ── кнопка у поля ввода ──────────────────────────────────────────────
    # ── исходящие вызовы хоста ───────────────────────────────────────────
    SETTING_DEFAULTS = {
        "poll_secs": 5,
        "max_running": 3,
        "cost_warn_usd": 5,
        "default_chain": "deep",
        "aoe_url": "",
    }

    def read_settings(self) -> None:
        settings = {}
        for key, default in self.SETTING_DEFAULTS.items():
            try:
                value = self.rpc.call("config.get", {"key": key}).get("value")
            except RpcError as exc:
                log(f"orch-plugin: config.get {key}: {exc}")
                value = None
            settings[key] = default if value is None else value
        self.settings = settings
        if self.engine:
            self.engine.settings = self._settings_object()
            self.engine.aoe.base = self.base_url

    def _settings_object(self) -> Settings:
        return Settings(
            poll_secs=self.poll_secs,
            max_running=int(self.settings.get("max_running", 3)),
            cost_warn_usd=float(self.settings.get("cost_warn_usd", 5)),
            default_chain=str(self.settings.get("default_chain", "deep")),
            aoe_url=str(self.settings.get("aoe_url") or ""),
        )

    @property
    def base_url(self) -> str:
        from .aoe import BASE

        return str(self.settings.get("aoe_url") or BASE).rstrip("/")

    def ui_set(self, slot: str, ident: str, payload: dict, session_id: str | None = None) -> None:
        params = {"slot": slot, "id": ident, "payload": payload}
        if session_id:
            params["session_id"] = session_id
        try:
            self.rpc.call("ui.state.set", params)
        except RpcError as exc:
            log(f"orch-plugin: ui.state.set {slot}/{ident}: {exc}")

    def notify(self, title: str, body: str | None, tone: str = "info") -> None:
        try:
            self.rpc.call("ui.notify", {"title": title, "body": body, "tone": tone})
        except RpcError:
            pass

    def sessions_now(self) -> list[dict]:
        try:
            return self.rpc.call("sessions.list", {}).get("sessions", [])
        except RpcError as exc:
            log(f"orch-plugin: sessions.list: {exc}")
            return []

    # ── перерисовка ──────────────────────────────────────────────────────
    def push_all(self, force: bool = False) -> None:
        if self.engine is None:
            self.ui_set("home-pane", "tasks", _no_engine_pane())
            return
        db = self.engine.db
        cost_warn = float(self.settings.get("cost_warn_usd", 5))
        self._push_if_changed(
            ("home-pane", ""),
            panels.home_pane(db, self.known_projects(), cost_warn),
            "home-pane",
            "tasks",
            None,
            force,
        )
        self._refresh_session_map(db)
        for session_id, task_id in self.session_of_task.items():
            task = db.task(task_id)
            if task is None:
                continue
            self._push_if_changed(
                ("pane", session_id),
                panels.task_pane(db, task, session_id, self.base_url, cost_warn),
                "pane",
                "task",
                session_id,
                force,
            )
            # Бейдж на строке сессии: подсветку «сюда посмотри» хост рисует
            # сам по `urgent`, а зачем смотреть — знаем только мы.
            chain = self.engine.chain_of(task)
            place = panels.step_place(task, chain)
            self._push_if_changed(
                ("row-badge", session_id),
                panels.row_badge(db, task, *place),
                "row-badge",
                "step",
                session_id,
                force,
            )

    def _push_if_changed(self, key, payload, slot, ident, session_id, force) -> None:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if not force and self.drawn.get(key) == blob:
            return
        self.drawn[key] = blob
        self.ui_set(slot, ident, payload, session_id=session_id)

    def _refresh_session_map(self, db: Db) -> None:
        """Какая сессия какой задаче принадлежит — из заходов, без догадок."""
        self.session_of_task = {
            row["session_id"]: row["task_id"]
            for row in db.conn.execute(
                "SELECT DISTINCT session_id, task_id FROM run "
                "WHERE session_id IS NOT NULL AND task_id IN "
                "(SELECT id FROM task WHERE status IN ('running','waiting','queued'))"
            )
        }

    def known_projects(self) -> list[str]:
        """Проекты, в которых есть задачи или живые сессии.

        Кнопке «Новая задача» нужен проект, а клик по общей панели приходит
        без сессии, поэтому выбор показываем строками (`panels._new_task_blocks`).
        """
        out: list[str] = []
        if self.engine is not None:
            for row in self.engine.db.conn.execute(
                "SELECT DISTINCT project_path FROM task WHERE project_path IS NOT NULL"
            ):
                if row["project_path"] not in out:
                    out.append(row["project_path"])
        for row in self.sessions_now():
            path = row.get("project_path")
            if path and path not in out and _is_project_root(path):
                out.append(path)
        return sorted(out)

    def _project_of_session(self, session_id: str) -> str | None:
        for row in self.sessions_now():
            if row.get("id") == session_id:
                return row.get("project_path") or None
        return None

    # ── жизненный цикл ───────────────────────────────────────────────────
    def run(self) -> int:
        reader = threading.Thread(target=self.rpc.serve, name="orch-rpc", daemon=True)
        reader.start()
        self.read_settings()
        self.start_engine()
        self.push_all(force=True)
        while not self.rpc.stopped.is_set():
            self.wake.wait(timeout=self.poll_secs)
            self.wake.clear()
            if self.rpc.stopped.is_set():
                break
            self.tick()
        log("orch-plugin: stdin закрыт, выходим")
        return 0

    @property
    def poll_secs(self) -> float:
        try:
            return max(2.0, float(self.settings.get("poll_secs", 5)))
        except (TypeError, ValueError):
            return 5.0

    def start_engine(self) -> None:
        self.lock = EngineLock()
        if not self.lock.acquire():
            log(
                "orch-plugin: движок уже занят другим процессом — этот воркер "
                "рисует панели, но задачи не двигает"
            )
            self.engine = None
            return
        self.engine = self._new_engine()

    def _new_engine(self) -> Engine:
        from .aoe import Aoe

        settings = self._settings_object()
        return Engine(Db(), Aoe(self.base_url), settings)

    def tick(self) -> None:
        if self.engine is None:
            # Замок мог освободиться: движок из терминала выключили.
            if self.lock and self.lock.acquire():
                self.engine = self._new_engine()
                log("orch-plugin: движок подхвачен этим воркером")
            else:
                self.drain_actions()
                self.push_all()
                return
        clicked = self.drain_actions()
        try:
            self.engine.reconcile()
        except Exception as exc:  # noqa: BLE001 — воркер не падает от одной задачи
            log(f"orch-plugin: проход движка упал: {exc!r}")
        self.push_all(force=clicked)


def _is_project_root(path: str) -> bool:
    """Корень проекта, а не рабочая копия задачи.

    У копии, сделанной `git worktree add`, `.git` — файл со ссылкой на общий
    каталог, у настоящего корня — каталог. Без этой проверки список проектов
    зарастает копиями прошлых задач: они тоже сессии со своим `project_path`.
    """
    root = Path(path)
    return (root / ".git").is_dir()


def _next_knobs(after: bool, ask: bool) -> tuple[bool, bool]:
    """Круг переключателя строки листа: ничего → ворота → вопросы → оба."""
    order = [(False, False), (True, False), (False, True), (True, True)]
    try:
        return order[(order.index((after, ask)) + 1) % len(order)]
    except ValueError:
        return (True, False)


def _no_engine_pane() -> dict:
    return {
        "title": "orch",
        "default_location": "right",
        "icon": "list-checks",
        "blocks": [
            {"kind": "heading", "text": "Задачи"},
            {
                "kind": "note",
                "tone": "warn",
                "text": "Движок ведёт другой процесс: панель только читает.",
            },
        ],
    }


def run_standalone(poll_secs: float) -> int:
    """Движок без плагина: пока панель не поставлена в рабочий демон.

    Тот же `reconcile`, что и в воркере, — отдельного кода нет.
    """
    lock = EngineLock()
    if not lock.acquire():
        log("orch-plugin: движок уже запущен другим процессом; выхожу")
        return 1
    engine = Engine(Db())
    log(f"orch-plugin: движок без панели, опрос {poll_secs} с")
    try:
        while True:
            engine.reconcile()
            time.sleep(poll_secs)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--once" in args:
        lock = EngineLock()
        if not lock.acquire():
            log("orch-plugin: движок уже запущен другим процессом; выхожу")
            return 1
        Engine(Db()).reconcile()
        return 0
    if "--no-rpc" in args:
        secs = 5.0
        for a in args:
            if a.startswith("--poll="):
                secs = float(a.split("=", 1)[1])
        return run_standalone(secs)
    return Worker().run()


if __name__ == "__main__":
    sys.exit(main())
