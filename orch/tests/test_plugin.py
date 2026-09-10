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


def test_у_каждой_кнопки_панели_есть_обработчик_и_наоборот():
    """Кнопки были мертвы сутки: панель звала метод, которого у воркера нет,
    а тесты идут против поддельного AoE и клика хоста не видят. Сверка
    источников — единственное, что ловит это без живого хоста."""
    import inspect
    import re

    from orch import panels

    source = inspect.getsource(panels)
    в_панели = set(re.findall(r'"orch\.([a-z_]+)"', source))
    # Кнопки остановок собираются как `f"orch.{action}"` по словарю причин.
    в_панели |= {a for actions in panels.BUTTONS_BY_REASON.values() for a in actions}
    assert {"accept", "again", "sheet_step", "note", "wizard"} <= в_панели, в_панели
    у_воркера = {name[4:] for name in dir(Worker) if name.startswith("btn_")}
    assert в_панели <= у_воркера, f"кнопки без обработчика: {sorted(в_панели - у_воркера)}"
    assert у_воркера <= в_панели, f"обработчики без кнопки: {sorted(у_воркера - в_панели)}"


def test_кнопка_без_обработчика_кричит_владельцу(tmp_path, repo):
    """Раньше — строка в stderr воркера, которого никто не читает."""
    w, fake = worker_with_engine(tmp_path, repo)
    w.on_action("teleport", {"task": "T1"})
    assert not w.drain_actions()
    notices = [p for m, p in w.rpc.calls if m == "ui.notify"]
    assert notices and notices[-1]["tone"] == "danger" and "teleport" in notices[-1]["body"]


def test_отказ_aoe_на_оформлении_попадает_в_журнал_и_к_владельцу(tmp_path, repo):
    from orch.aoe import AoeError

    w, fake = worker_with_engine(tmp_path, repo)
    w.aoe_quiet_failed(AoeError(405, "Method Not Allowed", "/api/sessions/abc/archive"))
    событие = w.engine.db.events(limit=1)[0]
    assert событие["kind"] == "aoe_call_failed"
    assert "/api/sessions/{id}/archive" in событие["payload"] and "405" in событие["payload"]
    notices = [p for m, p in w.rpc.calls if m == "ui.notify"]
    assert notices and notices[-1]["tone"] == "warn"


def test_движок_воркера_подписан_на_тихие_отказы(tmp_path, monkeypatch):
    """Хук в клиенте ничего не стоит, если воркер его не подключил."""
    import orch.plugin as mod

    monkeypatch.setattr(mod, "Db", lambda: Db(tmp_path / "orch.db"))
    w = Worker()
    w.rpc = FakeRpc()
    w.read_settings()
    engine = w._new_engine()
    assert engine.aoe.on_quiet_error == w.aoe_quiet_failed
