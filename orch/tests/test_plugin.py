"""Воркер плагина: кнопки, настройки и состояние идут через поток движка."""

from __future__ import annotations

import threading

from orch.db import Db
from orch.engine import Engine, Settings
from orch.plugin import Worker
from conftest import FakeAoe
from test_engine import monkey_chain, session_of, sign


class FakeRpc:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.stopped = threading.Event()

    def call(self, method, params=None, timeout=30.0):
        self.calls.append((method, params or {}))
        if method == "config.get":
            return {"value": None}
        if method == "sessions.list":
            return {"sessions": []}
        return {}


def worker_with_engine(tmp_path, repo):
    w = Worker()
    w.rpc = FakeRpc()
    fake = FakeAoe()
    w.engine = Engine(Db(tmp_path / "orch.db"), fake, Settings())
    monkey_chain(w.engine)
    w.read_settings()
    return w, fake


def task_at_gate(w, fake, repo):
    task_id = w.engine.create_task(chain_name="t", project_path=str(repo), text="Кнопки.")
    w.engine.reconcile()
    sign(w.engine, task_id, "one", 1, None)
    fake.finish_turn(session_of(w.engine, task_id))
    w.engine.reconcile()
    w.engine.reconcile()
    sign(w.engine, task_id, "two", 1, "ok")
    fake.finish_turn(session_of(w.engine, task_id))
    w.engine.reconcile()
    task = w.engine.db.task(task_id)
    assert task["status"] == "waiting" and task["wait_reason"] == "gate"
    return task


def test_кнопка_панели_без_комментария_двигает_задачу(tmp_path, repo):
    """Клик приходит без `comment` — так собирает кнопки панель. Раньше воркер
    падал на несуществующем поле, и ни одна кнопка панели не работала."""
    w, fake = worker_with_engine(tmp_path, repo)
    task = task_at_gate(w, fake, repo)
    w.on_action("accept", {"task": task["id"], "revision": task["revision"]})
    assert w.drain_actions()
    assert w.engine.db.task(task["id"])["step"] == "three"
    notices = [p for m, p in w.rpc.calls if m == "ui.notify"]
    assert notices and "принято" in notices[-1]["title"]
    assert not any("не сработала" in (p.get("body") or "") for p in notices)


def test_смена_настроек_и_состояние_не_трогают_базу_из_чужого_потока(tmp_path, repo):
    w, fake = worker_with_engine(tmp_path, repo)
    w.push_all(force=True)
    seen = {}

    def host_thread():
        seen["settings"] = w.handle("plugin.settings.changed", {})
        seen["status"] = w.handle("plugin.dev.sadovskii.orch.status", {})

    th = threading.Thread(target=host_thread)
    th.start()
    th.join()
    assert seen["settings"] == {}
    assert seen["status"]["message"].startswith("orch:")
    assert w.settings_dirty.is_set()
    # Настройки перечитываются уже в потоке движка.
    w.tick()
    assert not w.settings_dirty.is_set()
    assert any(m == "config.get" for m, _ in w.rpc.calls)
