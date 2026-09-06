"""Воркер плагина AoE: движок оркестратора и панели.

Пока — каркас: протокол, слоты, приём кликов. Движок и содержимое панелей
приходят на этапах 1–2 (`orch/PLAN.md` §5, §8). Каркас нужен раньше, чтобы
спайк 4 проверил живьём: панель рисуется, клик доходит до воркера с
`session_id`, `composer.read` отдаёт черновик поля ввода.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from .db import Db
from .engine import Engine, Settings
from .rpc import Rpc, RpcError, log

PLUGIN_ID = "dev.sadovskii.orch"
STATE_DIR = Path.home() / ".local" / "share" / "orch"
# Журнал кликов: короткая память для панели и материал для спайка 4.
ACTIONS = STATE_DIR / "plugin-actions.jsonl"


class Worker:
    def __init__(self) -> None:
        self.rpc = Rpc(self.handle)
        self.last_action: dict | None = None
        self.started = time.time()
        self.settings: dict = {}
        # Сессии, которым уже нарисованы слоты на сессию (`pane`,
        # `composer-action`). Хост не сообщает о появлении сессии, поэтому
        # список наполняется проходом движка и кликами.
        self.session_slots: set[str] = set()
        self.engine: Engine | None = None

    # ── входящие вызовы хоста ────────────────────────────────────────────
    def handle(self, method: str, params: dict):
        tail = method.rsplit(".", 1)[-1] if method.startswith("plugin.") else method
        if method == "plugin.settings.changed":
            self.read_settings()
            self.push_all()
            return {}
        if tail == "status":
            return {
                "ok": True,
                "message": f"orch: воркер жив {int(time.time() - self.started)} с",
            }
        if method.startswith("orch."):
            self.on_action(method, params)
            return {}
        log(f"orch-plugin: неизвестный метод {method}")
        return NotImplemented

    def on_action(self, method: str, params: dict) -> None:
        """Клик по кнопке панели или по кнопке у поля ввода."""
        record = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": method,
            "session_id": params.get("session_id"),
            "params": {k: v for k, v in params.items() if k != "session_id"},
        }
        self.last_action = record
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with ACTIONS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        log("orch-plugin: клик", json.dumps(record, ensure_ascii=False))
        sid = record["session_id"]
        if sid:
            self.session_slots.add(sid)
        self.push_all()

    # ── исходящие вызовы хоста ───────────────────────────────────────────
    # Ключи объявлены в `aoe-plugin.toml`; хост отдаёт по одному за вызов.
    SETTING_DEFAULTS = {
        "poll_secs": 5,
        "max_running": 3,
        "cost_warn_usd": 5,
        "default_chain": "deep",
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

    def ui_set(self, slot: str, ident: str, payload: dict, session_id: str | None = None) -> None:
        params = {"slot": slot, "id": ident, "payload": payload}
        if session_id:
            params["session_id"] = session_id
        try:
            self.rpc.call("ui.state.set", params)
        except RpcError as exc:
            log(f"orch-plugin: ui.state.set {slot}/{ident}: {exc}")

    def push_all(self) -> None:
        self.ui_set("home-pane", "tasks", self.home_pane())
        for sid in sorted(self.session_slots):
            self.ui_set("pane", "task", self.task_pane(sid), session_id=sid)
            self.ui_set("composer-action", "move", self.composer_action(), session_id=sid)

    # ── содержимое панелей (наполняется на этапе 2) ───────────────────────
    def home_pane(self) -> dict:
        blocks: list[dict] = [{"kind": "heading", "text": "Задачи"}]
        if self.last_action:
            act = self.last_action
            composer = (act["params"].get("composer") or {}).get("text")
            blocks.append(
                {
                    "kind": "row",
                    "label": f"последний клик: {act['method']}",
                    "sublabel": f"сессия {act['session_id']}",
                    "value": act["at"],
                    "mono": True,
                }
            )
            if composer is not None:
                blocks.append(
                    {
                        "kind": "row",
                        "label": "черновик поля ввода",
                        "sublabel": composer[:200] or "(пусто)",
                        "mono": True,
                    }
                )
        else:
            blocks.append({"kind": "note", "text": "движок ещё не запущен"})
        blocks.append(
            {
                "kind": "action",
                "label": "Проверка кнопки",
                "method": "orch.ping",
                "params": {"from": "home-pane"},
            }
        )
        return {
            "title": "orch",
            "default_location": "right",
            "icon": "list-checks",
            "blocks": blocks,
        }

    def task_pane(self, session_id: str) -> dict:
        blocks: list[dict] = [{"kind": "heading", "text": "Задача"}]
        blocks.append(
            {"kind": "row", "label": "сессия", "value": session_id, "mono": True}
        )
        if self.last_action:
            blocks.append(
                {
                    "kind": "row",
                    "label": "последний клик",
                    "value": self.last_action["method"],
                    "mono": True,
                }
            )
        blocks.append(
            {
                "kind": "action",
                "label": "Проверка кнопки в сессии",
                "method": "orch.ping",
                "params": {"from": "pane"},
            }
        )
        return {
            "title": "orch",
            "default_location": "right",
            "icon": "list-checks",
            "blocks": blocks,
        }

    def composer_action(self) -> dict:
        return {
            "label": "Двинуть с этим текстом",
            "method": "orch.move_with_text",
            "icon": "arrow-right",
            "tooltip": "Комментарий владельца к движению задачи",
        }

    # ── жизненный цикл ───────────────────────────────────────────────────
    def run(self) -> int:
        reader = threading.Thread(target=self.rpc.serve, name="orch-rpc", daemon=True)
        reader.start()
        self.read_settings()
        self.start_engine()
        self.push_all()
        while not self.rpc.stopped.wait(timeout=self.poll_secs):
            self.tick()
        log("orch-plugin: stdin закрыт, выходим")
        return 0

    @property
    def poll_secs(self) -> float:
        try:
            return max(2.0, float(self.settings.get("poll_secs", 5)))
        except (TypeError, ValueError):
            return 5.0

    def tick(self) -> None:
        """Проход движка: одно действие на задачу, дальше перерисовка панелей."""
        if self.engine is None:
            return
        try:
            self.engine.reconcile()
        except Exception as exc:  # noqa: BLE001 — воркер не падает от одной задачи
            log(f"orch-plugin: проход движка упал: {exc!r}")
        self.push_all()

    def start_engine(self) -> None:
        self.engine = Engine(
            Db(),
            settings=Settings(
                poll_secs=self.poll_secs,
                max_running=int(self.settings.get("max_running", 3)),
                cost_warn_usd=float(self.settings.get("cost_warn_usd", 5)),
                default_chain=str(self.settings.get("default_chain", "deep")),
            ),
        )


def run_standalone(poll_secs: float) -> int:
    """Движок без плагина: пока панель не поставлена в рабочий демон.

    Тот же `reconcile`, что и в воркере, — отдельного кода нет.
    """
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
