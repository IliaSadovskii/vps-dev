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
        # Черновик новой задачи: лист автономии, который владелец щёлкает до
        # запуска. Один на весь плагин, потому что общая панель одна и
        # session_id в её кликах пустой; в черновике помним, из какой сессии
        # он заведён — оттуда берётся проект и туда возвращается очистка поля.
        self.draft: dict | None = None
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
        # Просьба очистить поле ввода: держится в полезной нагрузке кнопки,
        # пока не устареет. Ключ — сессия, значение — операция и время.
        self.clear_ops: dict[str, tuple[dict, float]] = {}
        # Комментарий владельца, прикреплённый к следующему движению задачи.
        # Клик по кнопке панели черновика поля ввода не несёт — его отдают
        # только кнопке у поля, — поэтому текст приходит отдельно и ждёт
        # здесь, пока владелец выберет движение.
        self.comments: dict[str, str] = {}

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

    def btn_focus(self, session_id, params) -> None:
        """Строка ждущей задачи в общей панели: ничего не меняет, только жест."""

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

    # ── кнопка у поля ввода ──────────────────────────────────────────────
    def btn_move_with_text(self, session_id, params) -> None:
        """«Двинуть с этим текстом»: черновик становится комментарием движения."""
        text = ((params.get("composer") or {}).get("text") or "").strip()
        if self.engine is None:
            return
        if self.draft is not None and self.draft.get("awaiting") == "branch":
            self.take_branch(session_id, text)
            return
        if self.draft is not None:
            self.draft["text"] = text
            self.draft["session_id"] = session_id
            if not self.draft.get("project_path"):
                self.draft["project_path"] = self._project_of_session(session_id) or ""
            self.notify("orch", "текст задачи взят, теперь «Запустить»")
            self.clear_composer(session_id)
            return
        task = self._task_of_session(session_id)
        if task is None:
            self.notify("orch", "эта сессия не принадлежит задаче", tone="warn")
            return
        if not text:
            self.comments.pop(task["id"], None)
            self.notify("orch", "поле пустое: комментарий снят", tone="warn")
            return
        self.comments[task["id"]] = text
        self.notify(
            f"{task['id']}: комментарий прикреплён",
            "теперь выберите движение кнопкой в панели",
        )
        self.clear_composer(session_id)

    def btn_new_task(self, session_id, params) -> None:
        """Открыть лист автономии новой задачи."""
        if self.engine is None:
            return
        chain_name = str(self.settings.get("default_chain", "deep"))
        try:
            chain = load_chain(chains_dir() / f"{chain_name}.yml")
        except ChainError as exc:
            self.notify("orch", f"цепочка {chain_name}: {exc}", tone="danger")
            return
        text = ((params.get("composer") or {}).get("text") or "").strip()
        project = self._project_of_session(session_id)
        self.draft = {
            "chain": chain_name,
            "project_path": project or "",
            "text": text,
            "sheet": chain.default_sheet(),
            "session_id": session_id,
        }

    def btn_pick_branch(self, session_id, params) -> None:
        """Строка «ветка»: попросить ссылку, либо снять уже выбранную."""
        if not self.draft:
            return
        if params.get("cancel") or self.draft.get("branch"):
            self.draft.pop("branch", None)
            self.draft.pop("branch_holder", None)
            self.draft.pop("branch_error", None)
            self.draft.pop("awaiting", None)
            return
        self.draft["awaiting"] = "branch"
        self.draft.pop("branch_error", None)
        self.notify(
            "orch: жду ссылку на ветку",
            "вставьте в поле ввода ссылку на ветку или на PR и нажмите кнопку у поля",
        )

    def take_branch(self, session_id: str, text: str) -> None:
        """Ссылка из поля ввода стала веткой задачи."""
        from .branchref import BranchRefError, parse

        draft = self.draft
        if draft is None or self.engine is None:
            return
        try:
            branch = parse(text, draft.get("project_path"))
        except BranchRefError as exc:
            draft["branch_error"] = str(exc)
            self.notify("orch: не понял ссылку", str(exc)[:200], tone="warn")
            return
        draft.pop("branch_error", None)
        draft.pop("awaiting", None)
        draft["branch"] = branch
        busy = self.engine.task_on_branch(branch)
        draft["branch_holder"] = busy["id"] if busy else None
        if busy:
            self.notify(
                f"orch: ветка {branch} занята задачей {busy['id']}",
                "закройте ту задачу или выберите другую ветку",
                tone="warn",
            )
        else:
            self.notify(f"orch: работаем в ветке {branch}", "теперь «Запустить»")
        self.clear_composer(session_id)

    def btn_sheet_toggle(self, session_id, params) -> None:
        if not self.draft:
            return
        knobs = self.draft["sheet"].setdefault(params["step"], {"after": False, "ask": True})
        knob = params["knob"]
        knobs[knob] = not bool(knobs.get(knob))

    def btn_launch(self, session_id, params): self._create_draft(backlog=False)
    def btn_backlog(self, session_id, params): self._create_draft(backlog=True)

    def btn_cancel_new(self, session_id, params) -> None:
        self.draft = None

    def _create_draft(self, backlog: bool) -> None:
        draft = self.draft
        if not draft or self.engine is None:
            return
        if not draft.get("text"):
            self.notify("orch", "текста задачи нет", tone="warn")
            return
        if not draft.get("project_path"):
            self.notify("orch", "не понял, в каком проекте задача", tone="warn")
            return
        if draft.get("branch_holder"):
            self.notify(
                "orch", f"ветка занята задачей {draft['branch_holder']}", tone="warn"
            )
            return
        edits = {}
        for step, knobs in draft["sheet"].items():
            edits[f"{step}.after"] = knobs["after"]
            edits[f"{step}.ask"] = knobs["ask"]
        try:
            task_id = self.engine.create_task(
                chain_name=draft["chain"],
                project_path=draft["project_path"],
                text=draft["text"],
                sheet_edits=edits,
                backlog=backlog,
                branch=draft.get("branch"),
            )
        except (ChainError, OSError) as exc:
            self.notify("orch", f"задача не создалась: {exc}", tone="danger")
            return
        self.draft = None
        self.notify(f"{task_id} создана", "в бэклоге" if backlog else "поехала")
        self.clear_composer(draft.get("session_id") or "")

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

    # Сколько держим просьбу очистить поле, чтобы браузер успел её забрать.
    CLEAR_TTL_S = 120.0

    def clear_composer(self, session_id: str) -> None:
        """Очистить поле ввода: текст уже стал комментарием движения."""
        if not session_id:
            return
        self.clear_ops[session_id] = (
            {"kind": "set-text", "id": f"clear-{int(time.time() * 1000)}", "text": ""},
            time.time(),
        )

    def _clear_op(self, session_id: str) -> dict | None:
        entry = self.clear_ops.get(session_id)
        if not entry:
            return None
        op, at = entry
        if time.time() - at > self.CLEAR_TTL_S:
            self.clear_ops.pop(session_id, None)
            return None
        return op

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
        draft = self.draft
        self._push_if_changed(
            ("home-pane", ""),
            panels.home_pane(db, draft, cost_warn),
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
                panels.task_pane(
                    db,
                    task,
                    session_id,
                    self.base_url,
                    cost_warn,
                    comment=self.comments.get(task_id),
                ),
                "pane",
                "task",
                session_id,
                force,
            )
        # Кнопка у поля ввода — в каждой живой сессии: из чужой сессии ею
        # набирают текст новой задачи, из сессии задачи — комментарий движения.
        for row in self.sessions_now():
            session_id = row.get("id")
            if not session_id or row.get("archived"):
                continue
            task_id = self.session_of_task.get(session_id)
            task = db.task(task_id) if task_id else None
            self._push_if_changed(
                ("composer-action", session_id),
                panels.composer_action(
                    task,
                    draft_open=self.draft is not None,
                    awaiting=(self.draft or {}).get("awaiting"),
                    clear_op=self._clear_op(session_id),
                ),
                "composer-action",
                "move",
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

    def _task_of_session(self, session_id: str):
        if self.engine is None:
            return None
        task_id = self.session_of_task.get(session_id)
        return self.engine.db.task(task_id) if task_id else None

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
