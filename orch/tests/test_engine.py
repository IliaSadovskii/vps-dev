"""Движок против поддельного AoE. Сценарии — `PLAN.md` §11."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch.chain import ChainError
from orch.chain import parse as parse_chain
from orch.db import ABANDONED, BACKLOG, DONE, QUEUED, RUNNING, WAITING

CHAIN = """
name: t
steps:
  - id: one
    run: {agent: claude, model: haiku}
    artifact: [one.md]
    next: two
  - id: two
    run: {agent: claude, model: haiku}
    prompt: {reads: [one.md]}
    artifact: [two.md]
    next:
      ok: three
      back: one
    human:
      after: [ok]
      ask: false
      moves: [one]
    limits: {max_runs: 2}
  - id: three
    run: {agent: claude, model: haiku}
    context: continue
    artifact: [three.md]
    next: done
"""


# Цепочка, где шаг просит перечитать сам себя: возврат на себя круг не
# открывает, поэтому предел заходов бьётся именно здесь.
CHAIN_SELF = """
name: t
steps:
  - id: one
    run: {agent: claude, model: haiku}
    artifact: [one.md]
    next:
      again: one
      ok: two
    limits: {max_runs: 2}
  - id: two
    run: {agent: claude, model: haiku}
    artifact: [two.md]
    next: done
"""


def monkey_chain_self(engine):
    import orch.engine as mod

    mod.load_chain = lambda path: parse_chain(CHAIN_SELF, source="тест")


def start_self(engine, repo):
    """Задача на цепочке с возвратом на себя: `start` ставит обычную."""
    engine.db.conn.execute("DELETE FROM task")
    monkey_chain_self(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="Проверить предел."
    )
    engine.reconcile()
    return task_id


# ── подмостки ────────────────────────────────────────────────────────────

def до_остановки_без_сигнала(engine, fake, sid):
    """Довести заход до остановки «нет сигнала».

    Движок толкает несколько раз и выдерживает паузу между толчками, поэтому
    после каждого прохода состариваем отметку толчка: иначе тест ждал бы
    реального времени.
    """
    from orch.engine import NUDGES_BEFORE_STOP

    def состарить():
        engine.db.conn.execute(
            "UPDATE event SET at = '2000-01-01T00:00:00Z' "
            "WHERE kind IN ('auto_continue', 'idle_seen')"
        )
        engine.db.conn.commit()

    for _ in range(NUDGES_BEFORE_STOP + 1):
        fake.finish_turn(sid)
        # Первый проход только отмечает простой: толчок идёт, когда простой
        # устоялся (`IDLE_SETTLE_S`) — промпт в живую сессию обрывает ей ход.
        engine.reconcile()
        состарить()
        engine.reconcile()
        состарить()

def start(engine, repo, **kw):
    """Создать задачу, поставить в очередь и довести до первого промпта."""
    engine.db.conn.execute("DELETE FROM task")
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="Проверить механику.", **kw
    )
    engine.reconcile()
    return task_id


def monkey_chain(engine):
    """Тестовая цепочка вместо файла на диске."""
    import orch.engine as mod

    def load(path):
        return parse_chain(CHAIN, source="тест")

    mod.load_chain = load


def ws_of(engine, task_id):
    from orch.workspace import Workspace

    task = engine.db.task(task_id)
    return Workspace(task["worktree_path"] or task["project_path"], task_id)


def sign(engine, task_id, step, run, outcome, body="## Итог\nготово\n", artifact=None):
    """Роль написала артефакт и вызвала `orch done`."""
    ws = ws_of(engine, task_id)
    ws.artifacts.mkdir(parents=True, exist_ok=True)
    for name in artifact or [f"{step}.md"]:
        (ws.artifacts / name).write_text(body, encoding="utf-8")
    from orch import signals

    signals.write_done(ws.signals, step, run, outcome)


def turn(engine, fake, task_id, step, run, outcome, **kw):
    """Роль отработала ход целиком: артефакт, сигнал, конец хода, два прохода.

    Проходов два не для красоты: движок делает одно действие на задачу за
    проход (`PLAN.md` §2), поэтому первый применяет сигнал и двигает шаг, а
    второй стартует заход следующего шага.
    """
    sid = session_of(engine, task_id)
    sign(engine, task_id, step, run, outcome, **kw)
    fake.finish_turn(sid)
    engine.reconcile()
    engine.reconcile()
    return sid


def session_of(engine, task_id):
    row = engine.db.conn.execute(
        "SELECT session_id FROM run WHERE task_id = ? AND session_id IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row["session_id"] if row else None


# ── сценарии ─────────────────────────────────────────────────────────────
def test_прямой_путь_до_конца(engine, fake, repo):
    task_id = start(engine, repo)
    assert engine.db.task(task_id)["step"] == "one"
    assert len(fake.prompts) == 1

    turn(engine, fake, task_id, "one", 1, None)
    assert engine.db.task(task_id)["step"] == "two"

    sid = turn(engine, fake, task_id, "two", 1, "ok")
    # У шага two ворота на исходе ok: задача встала.
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "gate"
    # Ворота — не поломка: жёлтый. Красный остаётся для «сломалось».
    assert fake.colors[sid] == "amber"

    engine.button(task_id, task["revision"], "accept", comment="Годится.")
    engine.reconcile()
    assert engine.db.task(task_id)["step"] == "three"

    sid = turn(engine, fake, task_id, "three", 1, None)
    task = engine.db.task(task_id)
    assert task["status"] == DONE and task["closed_at"]


def test_возврат_ролью_открывает_шагу_новый_предел(engine, fake, repo):
    """Работа, честно отправленная выше по цепочке, начинает круг заново.

    Иначе задача, которую Ревью кода вернуло в Реализацию, тут же встаёт
    «предел заходов» на самом Ревью, потратившем заходы в прошлом круге
    (T26 и T35, 2026-09-09).
    """
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")     # two вернул работу на one
    turn(engine, fake, task_id, "one", 2, None)
    turn(engine, fake, task_id, "two", 2, "back")
    turn(engine, fake, task_id, "one", 3, None)

    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["step"] == "two"
    assert len(engine.db.runs_of_step(task_id, "two")) == 3, "третий заход не начался"


def test_петля_возвратов_упирается_во_владельца(engine, fake, repo, monkeypatch):
    """Круг, открытый ролью, снимает предел — значит петлю держит свой счёт."""
    import orch.engine as mod

    monkeypatch.setattr(mod, "MAX_LOOPS", 2)
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    for заход in (1, 2, 3):
        turn(engine, fake, task_id, "two", заход, "back")
        turn(engine, fake, task_id, "one", заход + 1, None)
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "loops"


def test_возврат_на_себя_круг_не_открывает(engine, fake, repo):
    """Шаг, который просит перечитать сам себя, упирается в свой предел."""
    task_id = start_self(engine, repo)
    turn(engine, fake, task_id, "one", 1, "again")
    turn(engine, fake, task_id, "one", 2, "again")
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "max_runs"


def test_ещё_заход_на_пределе_поднимает_предел(engine, fake, repo):
    """Кнопка на пределе заходов обязана дать заход, а не остановить снова."""
    task_id = start_self(engine, repo)
    turn(engine, fake, task_id, "one", 1, "again")
    turn(engine, fake, task_id, "one", 2, "again")
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "max_runs"

    assert "предел поднят" in engine.button(task_id, task["revision"], "again")
    engine.reconcile()
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["step"] == "one"
    assert len(engine.db.runs_of_step(task_id, "one")) == 3


def test_цена_хода_читается_из_ленты_кадров(engine, fake, repo):
    """Лента AoE отдаёт `frames`; по выдуманному ключу `events` цена терялась."""
    from orch.aoe import Aoe

    aoe = Aoe.__new__(Aoe)
    aoe.call = lambda *a, **kw: {
        "frames": [
            {"event": {"UsageUpdated": {"usage": {"used": 1, "cost": None}}}},
            {"event": {"UsageUpdated": {"usage": {"used": 2, "cost_usd": 1.25}}}},
        ]
    }
    assert Aoe.usage(aoe, "s1")[0] == 1.25

    # Поставщик цены не сообщает (подписка) — честный `None`, а не ноль.
    aoe.call = lambda *a, **kw: {"frames": [{"event": {"UsageUpdated": {"usage": {"cost": None}}}}]}
    assert Aoe.usage(aoe, "s1")[0] is None


def test_нет_сигнала(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.finish_turn(sid)          # ход кончился, сигнала нет
    engine.reconcile()
    # Сразу движок не толкает: промпт в живую сессию обрывает ей ход, а
    # `Idle` от AoE бывает преждевременным. Первый проход только отмечает
    # простой (`IDLE_SETTLE_S`).
    assert "подай сигнал" not in fake.prompts[-1][1]
    engine.db.conn.execute("UPDATE event SET at = '2000-01-01T00:00:00Z' WHERE kind = 'idle_seen'")
    engine.db.conn.commit()
    engine.reconcile()
    # Простой устоялся — движок просит закончить и подать сигнал.
    assert "подай сигнал" in fake.prompts[-1][1]
    assert engine.db.task(task_id)["status"] == RUNNING

    # Толчков несколько, и между ними пауза: роль, ждущая подагентов, тоже
    # кончает ход молча.
    до_остановки_без_сигнала(engine, fake, sid)
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "no_signal"
    assert fake.urgent[sid] is True

    engine.button(task_id, task["revision"], "again", comment="Заверши и подай сигнал.")
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING
    # Комментарий владельца доехал до роли дословно.
    assert "Заверши и подай сигнал." in fake.prompts[-1][1]


def test_артефакта_нет_сигнал_не_принимается(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    from orch import signals

    signals.write_done(ws_of(engine, task_id).signals, "one", 1, None)
    fake.finish_turn(sid)
    engine.reconcile()
    # Сигнал был, файла нет — это не «нет сигнала», причина другая.
    assert engine.db.task(task_id)["wait_reason"] == "artifact"


def test_четыре_состояния_после_рестарта_idle_сначала_просит_закончить(engine, fake, repo):
    """`Idle` без сигнала — сначала просьба закончить, остановка потом."""
    task_id = start(engine, repo)
    fake.finish_turn(session_of(engine, task_id))
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING


def test_исход_не_из_списка(engine, fake, repo):
    task_id = start(engine, repo)
    sid = turn(engine, fake, task_id, "one", 1, None)

    sid = turn(engine, fake, task_id, "two", 1, "выдумка")
    assert engine.db.task(task_id)["wait_reason"] == "bad_outcome"


def test_устаревшая_кнопка_отклоняется(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.finish_turn(sid)
    engine.reconcile()
    task = engine.db.task(task_id)
    stale = task["revision"]

    assert engine.button(task_id, stale, "again") == "ещё заход"
    # Второй клик той же ревизией — ревизия уже другая.
    assert "устаревшая" in engine.button(task_id, stale, "again")
    moves = [m for m in engine.db.moves(task_id) if m["actor"] == "human"]
    assert len(moves) == 1


def test_сигнал_и_кнопка_одновременно(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    sign(engine, task_id, "one", 1, None)
    fake.finish_turn(sid)
    engine.reconcile()          # сигнал применился первым, шаг two
    task = engine.db.task(task_id)
    assert task["step"] == "two"
    # Кнопка, нарисованная до сигнала, несёт старую ревизию.
    assert "устаревшая" in engine.button(task_id, task["revision"] - 1, "accept")


def test_stop_после_сигнала_принимается(engine, fake, repo):
    """Отмена отменяет ход, не работу: сигнал и артефакт на месте."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    sign(engine, task_id, "one", 1, None)
    fake.set_status(sid, "Idle")
    fake.finish_turn(sid)
    engine.reconcile()
    assert engine.db.task(task_id)["step"] == "two"


def test_падение_между_транзакцией_и_созданием_сессии(engine, fake, repo):
    task_id = start(engine, repo)
    # Имитируем падение: заход есть, сессии у него нет.
    run = engine.db.open_run(task_id)
    with engine.db.tx():
        engine.db.conn.execute("UPDATE run SET session_id = NULL WHERE id = ?", (run["id"],))
    before = len(fake.rows)
    engine.reconcile()
    # Ключ идемпотентности тот же — вторая сессия не родилась.
    assert len(fake.rows) == before
    assert engine.db.open_run(task_id)["session_id"] is not None


@pytest.mark.parametrize(
    "status, worker, ждём",
    [
        ("Running", "running", RUNNING),   # ждём, ничего не делаем
        ("Idle", "running", RUNNING),      # без сигнала: сначала просим закончить
        ("Error", "running", RUNNING),     # первый раз «продолжай»
        ("Stopped", "absent", RUNNING),    # воркер умер — будим промптом
    ],
)
def test_четыре_состояния_сессии_после_рестарта(engine, fake, repo, status, worker, ждём):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    if status == "Idle":
        fake.finish_turn(sid)
    else:
        fake.set_status(sid, status, worker)
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == ждём


def test_сессия_исчезла(engine, fake, repo):
    task_id = start(engine, repo)
    fake.drop(session_of(engine, task_id))
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == ABANDONED


def test_ошибка_дважды_останавливает(engine, fake, repo, clock):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Error")
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING
    # Через пять секунд статус после «продолжай» ещё не сменился — это не
    # вторая ошибка, а та же. Останавливаемся только по выдержке.
    fake.set_status(sid, "Error")
    clock.tick(5)
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING
    clock.tick(40)
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "error"


def test_ещё_заход_после_ошибки_заводит_новую_сессию(engine, fake, repo, clock):
    """Задача встала с открытым заходом (сессия в ошибке). «Ещё заход» обязан
    закрыть его, иначе движок снова смотрит на ту же мёртвую сессию."""
    task_id = start(engine, repo)
    first = session_of(engine, task_id)
    fake.set_status(first, "Error")
    engine.reconcile()                                   # «продолжай»
    fake.set_status(first, "Error")                      # и снова ошибка
    clock.tick(40)
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "error"

    assert engine.button(task_id, task["revision"], "again") == "ещё заход"
    assert engine.db.open_run(task_id) is None
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["wait_reason"] is None
    run = engine.db.open_run(task_id)
    assert run is not None and run["n"] == 2 and run["session_id"] != first
    # И ещё через пять секунд задача всё ещё едет, а не встала снова.
    clock.tick(5)
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING


def test_вернуть_после_ошибки_следит_за_новым_заходом(engine, fake, repo, clock):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)          # шаг two
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Error")
    engine.reconcile()
    fake.set_status(sid, "Error")
    clock.tick(40)
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "error" and task["step"] == "two"

    engine.button(task_id, task["revision"], "back", target="one", comment="заново")
    engine.reconcile()
    run = engine.db.open_run(task_id)
    assert run["step"] == "one" and run["n"] == 2
    assert "заново" in fake.prompts[-1][1]


def test_подталкивание_не_закрывает_ход_на_следующем_проходе(engine, fake, repo, clock):
    """После «заверши ход» статус ещё пять секунд остаётся `Idle`. Раньше
    движок принимал старый `Idle` за конец нового хода и закрывал заход как
    «нет сигнала», пока роль работала (T16, 22:50:38 → 22:50:43)."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    clock.tick(50)
    fake.rows[sid]["status"] = "Idle"
    fake.rows[sid]["idle_entered_at"] = clock.stamp()
    from orch.engine import IDLE_SETTLE_S

    clock.tick(10)
    engine.reconcile()                                   # отметили простой
    clock.tick(IDLE_SETTLE_S)
    engine.reconcile()                                   # подтолкнули
    assert "подай сигнал" in fake.prompts[-1][1]
    assert engine.db.open_run(task_id) is not None

    # Следующий проход: статус в AoE ещё не сменился.
    fake.rows[sid]["status"] = "Idle"
    clock.tick(5)
    engine.reconcile()
    assert engine.db.open_run(task_id) is not None
    assert engine.db.task(task_id)["status"] == RUNNING
    assert len(fake.prompts) == 2

    # Роль доработала и сдала ход — заход принят как обычно.
    clock.tick(60)
    sign(engine, task_id, "one", 1, None)
    fake.rows[sid]["idle_entered_at"] = clock.stamp()
    engine.reconcile()
    assert engine.db.task(task_id)["step"] == "two"


def test_побудка_воркера_идёт_с_выдержкой(engine, fake, repo, clock):
    """Три попытки не сгорают за пятнадцать секунд: каждая ждёт полминуты."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Stopped", worker="absent")

    def wakes():
        return len(engine.db.run_events(task_id, "worker_wake", engine.db.open_run(task_id)["id"]))

    clock.tick(5); engine.reconcile(); assert wakes() == 0
    clock.tick(30); engine.reconcile(); assert wakes() == 1
    fake.set_status(sid, "Stopped", worker="absent")
    clock.tick(5); engine.reconcile(); assert wakes() == 1
    clock.tick(30); engine.reconcile(); assert wakes() == 2
    fake.set_status(sid, "Stopped", worker="absent")
    clock.tick(35); engine.reconcile(); assert wakes() == 3
    fake.set_status(sid, "Stopped", worker="absent")
    clock.tick(35); engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "no_worker"
    # «Ещё заход» отсюда заводит новую сессию, как и обещает панель.
    engine.button(task_id, task["revision"], "again")
    engine.reconcile()
    assert engine.db.open_run(task_id)["session_id"] != sid


def test_отказ_в_вопросе_не_повторяется_каждый_проход(engine, fake, repo, clock):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)          # шаг two, ask: false
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Waiting")
    engine.reconcile()
    assert fake.cancels.count(sid) == 1
    fake.set_status(sid, "Waiting")
    clock.tick(5)
    engine.reconcile()
    assert fake.cancels.count(sid) == 1
    clock.tick(40)
    engine.reconcile()
    assert fake.cancels.count(sid) == 2


def test_кривая_заявка_не_останавливает_движок(engine, fake, repo, tmp_path, monkeypatch):
    import orch.inbox as mod

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(mod, "INBOX", inbox)
    (inbox / "bad.json").write_text(
        json.dumps({"kind": "button", "task": "T1", "revision": None, "action": "again"}),
        encoding="utf-8",
    )
    task_id = start(engine, repo)                        # проход с кривой заявкой внутри
    assert not (inbox / "bad.json").exists()
    assert any(e["kind"] == "inbox_rejected" for e in engine.db.events(limit=20))
    assert len(fake.prompts) == 1                        # задача поехала, движок не упал


def test_выключенные_вопросы_отменяют_ход(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    sign(engine, task_id, "one", 1, None)
    fake.finish_turn(sid)
    engine.reconcile()          # сигнал принят, шаг two
    engine.reconcile()          # заход шага two начался; у него ask: false

    sid = session_of(engine, task_id)
    fake.set_status(sid, "Waiting")
    engine.reconcile()
    assert sid in fake.cancels
    assert "реши сам" in fake.prompts[-1][1]
    assert engine.db.task(task_id)["status"] == RUNNING


def test_вопросы_включены_задача_ждёт(engine, fake, repo):
    task_id = start(engine, repo)     # шаг one, ask по умолчанию true
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Waiting")
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "ask"
    assert sid not in fake.cancels


def test_ответ_владельца_снимает_остановку_на_вопросе(engine, fake, repo):
    """Ответ в чате возвращает задачу в работу без всякой кнопки."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Waiting")
    engine.reconcile()
    assert engine.db.task(task_id)["wait_reason"] == "ask"

    fake.set_status(sid, "Running")     # владелец ответил, роль продолжила
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["wait_reason"] is None
    assert fake.colors[sid] == "amber"

    sign(engine, task_id, "one", 1, None)
    fake.finish_turn(sid)
    engine.reconcile()
    assert engine.db.task(task_id)["step"] == "two"


def test_ворота_только_на_названном_исходе(engine, fake, repo):
    task_id = start(engine, repo)
    sid = turn(engine, fake, task_id, "one", 1, None)

    sid = session_of(engine, task_id)
    sign(engine, task_id, "two", 1, "back")   # ворота стоят только на ok
    fake.finish_turn(sid)
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["step"] == "one"


def test_лист_автономии_правится_и_снимает_ворота(engine, fake, repo):
    task_id = start(engine, repo)
    sheet = json.loads(engine.db.task(task_id)["human_sheet"])
    sheet["two"]["after"] = False
    with engine.db.tx():
        engine.db.bump(task_id, human_sheet=json.dumps(sheet, ensure_ascii=False))

    sid = turn(engine, fake, task_id, "one", 1, None)
    sid = turn(engine, fake, task_id, "two", 1, "ok")
    assert engine.db.task(task_id)["step"] == "three"


def test_очередь_max_running(engine, fake, repo):
    monkey_chain(engine)
    engine.settings.max_running = 2
    ids = [
        engine.create_task(chain_name="t", project_path=str(repo), text=f"задача {i}")
        for i in range(4)
    ]
    engine.reconcile()
    running = [t["id"] for t in engine.db.tasks((RUNNING,))]
    queued = [t["id"] for t in engine.db.tasks((QUEUED,))]
    assert len(running) == 2 and len(queued) == 2
    assert set(running) | set(queued) == set(ids)


def test_бэклог_не_едет_пока_не_запустят(engine, fake, repo):
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="потом", backlog=True
    )
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == BACKLOG
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "start")
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING


def test_правка_артефакта_владельцем_видна_следующей_роли(engine, fake, repo):
    task_id = start(engine, repo)
    sid = turn(engine, fake, task_id, "one", 1, None)
    # Владелец правит файл роли one руками, пока идёт two.
    ws = ws_of(engine, task_id)
    (ws.artifacts / "one.md").write_text("## Итог\nправка владельца\n", encoding="utf-8")

    sid = turn(engine, fake, task_id, "two", 1, "back")
    assert "изменился после того, как его роль сдала ход" in fake.prompts[-1][1]


def test_возврат_кнопкой_только_по_moves(engine, fake, repo):
    task_id = start(engine, repo)
    sid = turn(engine, fake, task_id, "one", 1, None)
    sid = turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    assert "вернуть можно на" in engine.button(task_id, task["revision"], "back", target="three")
    assert engine.button(task_id, task["revision"], "back", target="one") == "вернул на one"


def test_continue_продолжает_сессию_того_же_агента(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    sid = session_of(engine, task_id)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    # Шаг three с `context: continue` не создаёт новую сессию.
    assert session_of(engine, task_id) == sid


def test_continue_берёт_сессию_убранную_из_живых(engine, fake, repo):
    """Сессия предыдущего шага может быть уже не в `state=live`.

    В AoE нет `GET /api/sessions/{id}`, а полный список отдаёт и архив;
    движок обязан её найти, иначе `continue` молча заводит чистую сессию и
    роль теряет память.
    """
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    sid = session_of(engine, task_id)
    turn(engine, fake, task_id, "two", 1, "ok")
    fake.archived.append(sid)          # сессия ушла из живых
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    assert session_of(engine, task_id) == sid


def test_исчезнувшая_из_живых_но_живая_сессия_не_брошена(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.archived.append(sid)
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING


def test_заявка_из_inbox_становится_задачей(engine, fake, repo, tmp_path, monkeypatch):
    import orch.inbox as mod

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(mod, "INBOX", inbox)
    monkey_chain(engine)
    (inbox / "a.json").write_text(
        json.dumps({"chain": "t", "project_path": str(repo), "text": "из заявки"}),
        encoding="utf-8",
    )
    engine.reconcile()
    assert [t["text"] for t in engine.db.tasks()] == ["из заявки"]
    assert not list(inbox.glob("*.json"))


def test_роли_подагентов_берутся_из_текста_роли(engine, repo):
    """Маска по имени шага не находит `sub-review-*` для шага `code-review`."""
    from orch.chain import chains_dir, load

    deep = load(chains_dir() / "deep.yml")
    paths = engine.sub_prompts(deep.step("code-review"))
    names = sorted(p.rsplit("/", 1)[-1] for p in paths)
    assert names == [
        "sub-review-defects.md",
        "sub-review-security.md",
        "sub-review-simplicity.md",
    ]
    # У шага без подагентов список пуст.
    assert engine.sub_prompts(deep.step("scoping")) == []


def test_модель_ставится_до_промпта(engine, fake, repo):
    """`agent_model` при создании сессии до Claude не доезжает: без явной
    установки ход пошёл бы на модели адаптера по умолчанию."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    assert fake.model_now(sid) == "haiku"        # модель шага из цепочки
    # Модель ставится раньше промпта, а не после него.
    assert fake.prompts and fake.prompts[0][0] == sid


def test_отказ_поставить_модель_не_останавливает_но_виден(engine, fake, repo):
    fake.model_apply_fails = True
    task_id = start(engine, repo)
    kinds = [e["kind"] for e in engine.db.events(task_id, limit=10)]
    assert "model_not_applied" in kinds
    assert engine.db.task(task_id)["status"] == RUNNING


def test_имя_ветки_не_кончается_дефисом(engine, repo):
    """Обрезка длинного титула не должна оставлять дефис на хвосте: имя ветки
    в базе разойдётся с настоящей веткой и `orch push` откажет."""
    from orch.naming import slug as _slug

    assert _slug("Разработать модуль аутентификации и авторизации") == "razrabotat-modul-autentifikacii"
    assert not _slug("Разработать модуль аутентификации и авторизации").endswith("-")
    for title in ("а" * 40, "Проверка модели в сессии", "!!!", "one two three four five six"):
        got = _slug(title)
        assert got and not got.startswith("-") and not got.endswith("-"), (title, got)


def test_задача_на_существующей_ветке(engine, fake, repo, tmp_path):
    """Доработка открытого PR: задача садится на его ветку, а не заводит свою."""
    import subprocess

    monkey_chain(engine)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "branch", "feature/pr-4"], cwd=repo, check=True, env=env)

    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="доработать PR", branch="feature/pr-4"
    )
    assert engine.db.task(task_id)["branch"] == "feature/pr-4"

    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING
    # Копия сделана из существующей ветки, а не заведена новая.
    assert task["worktree_path"].endswith("feature/pr-4")
    heads = subprocess.run(["git", "branch", "--format=%(refname:short)"],
                           cwd=repo, capture_output=True, text=True, env=env).stdout.split()
    assert heads.count("feature/pr-4") == 1


def test_на_одну_ветку_копятся_задачи_а_работает_одна(engine, repo):
    """Две задачи в одной копии писали бы `.orch/` друг поверх друга.

    Поэтому заводятся обе, а в работу выходит одна: вторая ждёт очереди.
    """
    monkey_chain(engine)
    first = engine.create_task(
        chain_name="t", project_path=str(repo), text="первая", branch="общая"
    )
    second = engine.create_task(
        chain_name="t", project_path=str(repo), text="вторая", branch="общая"
    )
    assert engine.db.task(second)["branch"] == "общая"

    engine.promote_queue()
    assert engine.db.task(first)["status"] == RUNNING
    assert engine.db.task(second)["status"] == "queued"

    with engine.db.tx():
        engine.db.bump(first, status="done")
    engine.promote_queue()
    assert engine.db.task(second)["status"] == RUNNING


def test_задача_на_свободную_ветку_обгоняет_ждущую_ветки(engine, repo):
    """Ворота ветки держат только свою очередь, а не всю."""
    monkey_chain(engine)
    first = engine.create_task(
        chain_name="t", project_path=str(repo), text="первая", branch="общая"
    )
    engine.create_task(chain_name="t", project_path=str(repo), text="вторая", branch="общая")
    third = engine.create_task(
        chain_name="t", project_path=str(repo), text="третья", branch="своя"
    )
    engine.promote_queue()
    assert engine.db.task(first)["status"] == RUNNING
    assert engine.db.task(third)["status"] == RUNNING


def test_закрытая_задача_ветку_не_держит(engine, fake, repo):
    monkey_chain(engine)
    first = engine.create_task(chain_name="t", project_path=str(repo), text="первая", branch="общая")
    with engine.db.tx():
        engine.db.bump(first, status="done")
    second = engine.create_task(chain_name="t", project_path=str(repo), text="вторая", branch="общая")
    assert engine.db.task(second)["branch"] == "общая"


def test_база_ответвления_запоминается(engine, repo):
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="от релиза", base="release/1.2"
    )
    assert engine.db.task(task_id)["base_branch"] == "release/1.2"


def test_задачу_можно_закрыть_и_она_отпускает_ветку(engine, repo):
    """Заявка из бэклога, которая никогда не поедет, не должна держать ветку."""
    monkey_chain(engine)
    first = engine.create_task(
        chain_name="t", project_path=str(repo), text="заявка", branch="общая", backlog=True
    )
    task = engine.db.task(first)
    assert engine.button(first, task["revision"], "close") == "закрыта"
    assert engine.db.task(first)["status"] == "closed"
    # Ветка свободна: на ней можно завести новую задачу.
    second = engine.create_task(
        chain_name="t", project_path=str(repo), text="новая", branch="общая"
    )
    assert engine.db.task(second)["branch"] == "общая"


def test_мастер_открывается_с_каталогом_цепочек(engine, fake, repo):
    """Панель не умеет полей ввода: цепочку и ветку спрашивает мастер в чате."""
    sid = engine.open_wizard(str(repo))
    assert sid is not None
    отправлено = [text for target, text in fake.prompts if target == sid]
    assert отправлено, "мастеру не отправили промпт"
    text = отправлено[0]
    assert "Мастер задачи" in text
    assert "Цепочки:" in text and "`deep`" in text
    assert str(repo) in text
    # Сессия одна на проект: второй вызов не плодит новую.
    assert engine.open_wizard(str(repo)) == sid


def test_мастер_из_бэклога_видит_заявку_и_режим(engine, fake, repo):
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="починить вход", backlog=True
    )
    sid = engine.open_wizard(str(repo), task_id, "text")
    text = [t for target, t in fake.prompts if target == sid][0]
    assert f"Заявка {task_id} из бэклога" in text
    assert "починить вход" in text
    assert "orch task edit" in text and "Задачу не запускай" in text


def test_группа_задачи_начинается_с_имени_проекта(engine, fake, repo):
    """`vps-dev/T35 · …`: с осью «по группе» задачи проекта встают рядом."""
    monkey_chain(engine)
    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    assert task["group_path"] == f"{repo.name}/{task_id} · {task['title']}"
    assert fake.rows[session_of(engine, task_id)]["group_path"] == task["group_path"]


def test_заявка_из_бэклога_едет_под_своим_номером(engine, fake, repo):
    """Номер задачи не меняется от бэклога до PR.

    Заявку уже назвали в панели, в ветке и в разговоре: новый номер на выходе
    из бэклога рвал эту связь — ветка `t29-…` оказывалась под задачей `T35`.
    """
    monkey_chain(engine)
    заявка = engine.create_task(
        chain_name="t", project_path=str(repo), text="черновик", backlog=True
    )
    ветка = engine.db.task(заявка)["branch"]
    поехала = engine.release_task(заявка, chain_name="t", preset=None, text="настоящая")
    assert поехала == заявка, "заявка поехала под новым номером"
    задача = engine.db.task(заявка)
    assert задача["status"] in ("queued", "running")
    assert задача["text"] == "настоящая", "мастер не переписал ТЗ"
    assert задача["branch"] == ветка, "ветку заявки потеряли"
    assert задача["title"] == "настоящая", "титул остался от черновика"
    assert len(engine.db.tasks()) == 1, "рядом осталась вторая карточка"
    assert [e["kind"] for e in engine.db.events(заявка)].count("created") == 1


def test_отпущенная_заявка_держит_неназванное(engine, fake, repo):
    """Мастер приносит только то, что владелец назвал; остальное — из заявки."""
    monkey_chain(engine)
    заявка = engine.create_task(
        chain_name="t", project_path=str(repo), text="черновик", backlog=True,
        branch="pr-42", base="release", notify_gates=True,
    )
    лист = engine.db.task(заявка)["human_sheet"]
    engine.release_task(заявка)
    задача = engine.db.task(заявка)
    assert задача["branch"] == "pr-42" and задача["base_branch"] == "release"
    assert задача["notify_gates"] == 1, "звать в Telegram перестали молча"
    assert задача["human_sheet"] == лист, "лист автономии переписали без спроса"
    assert задача["text"] == "черновик"


def test_заявка_start_из_inbox_отпускает_задачу(engine, fake, repo):
    """Путь целиком: `orch task start` → файл в `inbox/` → движок."""
    import orch.inbox as inbox_mod

    monkey_chain(engine)
    заявка = engine.create_task(
        chain_name="t", project_path=str(repo), text="черновик", backlog=True
    )
    (inbox_mod.INBOX / "z.json").write_text(
        json.dumps({"kind": "start", "task": заявка, "chain": "t", "text": "настоящая"}),
        encoding="utf-8",
    )
    engine.take_inbox()
    assert engine.db.task(заявка)["status"] == QUEUED
    assert engine.db.task(заявка)["text"] == "настоящая"
    assert len(engine.db.tasks()) == 1


def test_отпустить_можно_только_заявку(engine, fake, repo):
    """Поехавшую задачу вторым `start` не перезапустить."""
    monkey_chain(engine)
    поехала = start(engine, repo)
    with pytest.raises(ChainError) as exc:
        engine.release_task(поехала)
    assert "не в бэклоге" in str(exc.value)
    with pytest.raises(ChainError):
        engine.release_task("T404")


def test_тз_правится_только_у_заявки(engine, fake, repo):
    """У поехавшей задачи текст уже в промптах прошлых шагов."""
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="старое", backlog=True
    )
    engine.edit_text(task_id, "новое ТЗ целиком")
    assert engine.db.task(task_id)["text"] == "новое ТЗ целиком"

    поехала = start(engine, repo)
    ответ = engine.edit_text(поехала, "поздно")
    assert "уже не в бэклоге" in ответ
    assert engine.db.task(поехала)["text"] != "поздно"


def test_титул_без_разметки(engine):
    """Мастер пишет ТЗ с markdown, а в панели строка должна читаться."""
    from orch.naming import title_from as _title_from

    assert _title_from("**Цель.** Показать дату у каждой заметки в list") == (
        "Показать дату у каждой заметки в list"
    )
    assert _title_from("# Заголовок\nтекст") == "Заголовок"
    assert _title_from("") == "задача"
    # Обрезанный титул не должен читаться как обрывок фразы: рвём по границе.
    assert _title_from(
        "**Цель.** PR #4 уехал автономно без владельца; привести его к соглашениям"
    ) == "PR 4 уехал автономно без владельца…"


def test_сессия_с_группой_orch_становится_мастером(engine, fake, repo):
    """Второй вход: штатная модалка «New session», в поле Group — `orch`."""
    session = fake.create(
        path=str(repo),
        agent="claude",
        model="sonnet",
        effort=None,
        title="Malay",
        group="orch",
        idempotency_key="ручная",
    )
    engine.reconcile()
    assert fake.rows[session.id]["group_path"] == f"{repo.name}/мастер"
    assert fake.titles[session.id].startswith("Мастер · ")
    text = [t for target, t in fake.prompts if target == session.id][0]
    assert "Мастер задачи" in text and "Цепочки:" in text
    # Второй проход не шлёт промпт снова: группа уже не метка.
    engine.reconcile()
    assert len([1 for target, _ in fake.prompts if target == session.id]) == 1


def test_сессии_задач_не_путаются_с_меткой(engine, fake, repo):
    """У сессии шага группа `orch/T5 · …` — усыновлять её нельзя."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    before = len(fake.prompts)
    engine.adopt_wizards(fake.sessions())
    assert len(fake.prompts) == before


def test_метка_orch_читается_и_из_титула(engine, fake, repo):
    """Поле «дополнительные аргументы» плагину не видно — метим титулом."""
    session = fake.create(
        path=str(repo), agent="claude", model="sonnet", effort=None,
        title="orch правки в списке", group="", idempotency_key="титул",
    )
    engine.reconcile()
    assert fake.rows[session.id]["group_path"] == f"{repo.name}/мастер"
    assert [t for target, t in fake.prompts if target == session.id]


def test_обычная_сессия_владельца_не_трогается(engine, fake, repo):
    """Слово orch внутри титула — не метка: метка стоит в начале."""
    session = fake.create(
        path=str(repo), agent="claude", model="sonnet", effort=None,
        title="читаю про orch", group="", idempotency_key="чужая",
    )
    engine.reconcile()
    assert fake.rows[session.id]["group_path"] == ""
    assert not [t for target, t in fake.prompts if target == session.id]


def _worktree(repo, branch: str):
    """Чужая рабочая копия ветки: так выглядит наследие прошлой задачи."""
    import subprocess

    path = repo.parent / f"{repo.name}-worktrees" / branch
    subprocess.run(
        ["git", "worktree", "add", "-q", str(path), "-b", branch],
        cwd=repo, check=True, capture_output=True,
    )
    return path


def test_брошенная_копия_ветки_освобождается(engine, fake, repo):
    """Задача на ветке открытого PR: копию под неё оставила прошлая задача."""
    monkey_chain(engine)
    старая = _worktree(repo, "feature/pr")
    (старая / ".orch").mkdir()          # служебный сор работой не считается
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="доработка PR", branch="feature/pr"
    )
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == "running", task["wait_reason"]
    assert not старая.exists()
    assert Path(task["worktree_path"]).is_dir()


def test_копия_с_работой_не_трогается(engine, fake, repo):
    """Незакоммиченные правки чужой задачи — не наше дело: решает владелец."""
    monkey_chain(engine)
    старая = _worktree(repo, "feature/dirty")
    (старая / "черновик.py").write_text("важное", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "черновик.py"], cwd=старая, check=True)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="доработка", branch="feature/dirty"
    )
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == "waiting" and task["wait_reason"] == "branch_busy"
    assert старая.exists() and (старая / "черновик.py").exists()
    from orch import panels

    assert "несохранённая работа" in panels._what_to_decide(engine.db, task)


def test_ветку_живой_задачи_не_отбираем(engine, fake, repo):
    """Две задачи в одной ветке писали бы `.orch/` в один каталог.

    Поэтому вторая не отбирает копию, а стоит в очереди, пока первая на
    воротах, и едет, когда та закрыта.
    """
    monkey_chain(engine)
    первая = start(engine, repo)
    ветка = engine.db.task(первая)["branch"]
    with engine.db.tx():
        engine.db.bump(первая, status="waiting", wait_reason="gate")
    engine.db.conn.execute(
        "INSERT INTO task (id, chain, chain_yaml, title, text, project_path, branch, "
        "group_path, status, human_sheet, revision, created_at) "
        "VALUES ('T99','t',?, 'вторая','вторая',?,?,'orch/T99','queued','{}',1,?)",
        (engine.db.task(первая)["chain_yaml"], str(repo), ветка, "2026-09-06T00:00:00Z"),
    )
    engine.db.conn.commit()
    engine.reconcile()
    task = engine.db.task("T99")
    assert task["status"] == "queued" and task["wait_reason"] is None
    assert task["worktree_path"] is None

    with engine.db.tx():
        engine.db.bump(первая, status="closed", wait_reason=None)
    engine.reconcile()
    assert engine.db.task("T99")["status"] in ("running", "waiting")


def test_ветку_берём_второй_копией_если_старую_не_снять(engine, fake, repo, monkeypatch):
    """Git сверяет путь строкой, и снять чужую копию удаётся не всегда."""
    from orch import engine as mod

    monkey_chain(engine)
    старая = _worktree(repo, "feature/stuck")
    monkeypatch.setattr(mod, "remove_worktree", lambda *a, **k: "fatal: validation failed")
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="доработка", branch="feature/stuck"
    )
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == "running", task["wait_reason"]
    assert старая.exists(), "чужую копию не трогаем, раз снять её не вышло"
    assert Path(task["worktree_path"]).is_dir()


def test_мастер_уходит_в_архив_заведя_задачу(engine, fake, repo):
    """Рядом с ходами его строку не поставить, а вечная строка в стороне — сор."""
    monkey_chain(engine)
    sid = engine.open_wizard(str(repo))
    assert fake.rows[sid]["group_path"] == f"{repo.name}/мастер"
    task_id = engine.create_task(chain_name="t", project_path=str(repo), text="новая")
    assert sid in fake.archived
    assert fake.titles[sid] == f"{task_id} · постановка"
    assert engine.db.task(task_id)["wizard_session"] == sid

    from orch import panels

    pane = panels.task_pane(engine.db, engine.db.task(task_id), "s9", "http://x")
    assert "постановка" in json.dumps(pane, ensure_ascii=False)
    assert f"http://x/session/{sid}" in json.dumps(pane, ensure_ascii=False)


def test_один_мастер_одна_заявка(engine, fake, repo):
    """Заявка в бэклог, запуск или правка ТЗ — после любого мастер в архиве."""
    monkey_chain(engine)
    sid = engine.open_wizard(str(repo))
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="идея раз", backlog=True
    )
    assert sid in fake.archived
    assert engine.db.task(task_id)["wizard_session"] == sid
    assert engine.free_wizard(str(Path(repo).resolve())) is None

    editor = engine.open_wizard(str(repo), task_id, "text")
    assert editor != sid
    engine.edit_text(task_id, "идея раз, точнее")
    assert editor in fake.archived


def test_следующая_задача_получает_нового_мастера(engine, fake, repo):
    """Уехавшая в задачу сессия не должна возвращаться по ключу."""
    monkey_chain(engine)
    первый = engine.open_wizard(str(repo))
    engine.create_task(chain_name="t", project_path=str(repo), text="первая")
    второй = engine.open_wizard(str(repo))
    assert второй != первый


def test_свободный_мастер_переиспользуется(engine, fake, repo):
    """Пока мастер не занят задачей, второй раз его не плодим."""
    первый = engine.open_wizard(str(repo))
    assert engine.open_wizard(str(repo)) == первый


def test_брошенная_задача_убирает_за_собой_копию(engine, fake, repo):
    """Сессии удалили руками — ждать от задачи нечего, копия только занимает диск."""
    task_id = start(engine, repo)
    copy = Path(engine.db.task(task_id)["worktree_path"])
    assert copy.is_dir()
    fake.rows.clear()               # владелец удалил сессии
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == "abandoned"
    engine.reconcile()              # уборка на следующем проходе
    task = engine.db.task(task_id)
    assert task["archived_at"]
    assert not copy.exists()


def test_копия_снимается_даже_под_другим_путём(engine, fake, repo, tmp_path):
    """Каталог проекта бывает доступен под двумя путями, git сверяет строкой."""
    import subprocess

    from orch.workspace import main_worktree, remove_worktree

    # Второй путь к тому же каталогу: так на машине живут `/projects/x` и
    # `~/projects/x`.
    alias = tmp_path / "alias"
    alias.symlink_to(repo)
    copy = repo.parent / f"{repo.name}-orch" / "t1-x"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(copy), "-b", "t1-x"],
        cwd=alias, check=True, capture_output=True,
    )
    assert main_worktree(alias).samefile(repo)
    assert remove_worktree(alias, copy) == ""
    assert not copy.exists()


def test_стенд_поднимает_роль_а_движок_даёт_ей_порты(engine, fake, repo, monkeypatch):
    """Проекты поднимаются по-разному, движок этого не знает — зовём роль."""
    from orch import stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {"APP_PORT": 8020})
    downs = []
    monkeypatch.setattr(stands, "down", lambda task, name: downs.append(name) or "")

    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    assert engine.button(task_id, task["revision"], "stand") == "роль «Стенд» поднимает окружение"
    task = engine.db.task(task_id)
    sid = engine.stand_session(task_id)
    assert sid and fake.rows[sid]["title"] == f"🧪 {task_id} · стенд"
    prompt = [t for target, t in fake.prompts if target == sid][0]
    assert "# Стенд" in prompt and task["stand"] in prompt and "8020" in prompt

    # Роль сообщила адрес — он виден в панели ссылкой.
    engine.stand_result(task_id, 8020, None)
    task = engine.db.task(task_id)
    assert task["stand_port"] == 8020

    from orch import panels

    assert "8020" in json.dumps(panels.task_pane(engine.db, task, "s9", "http://x"), ensure_ascii=False)

    # Закрытие задачи зовёт уборщика, а не гасит само.
    name = task["stand"]
    engine.button(task_id, task["revision"], "close")
    task = engine.db.task(task_id)
    assert engine.teardown_session(task_id), "уборку должна делать роль"
    assert downs == [], "движок не гасит, пока уборщик работает"

    # Уборщик отдал блок — движок это увидел и закрыл вопрос.
    monkeypatch.setattr(stands, "gone", lambda n: n == name)
    engine.watch_teardown()
    task = engine.db.task(task_id)
    assert task["stand"] is None and engine.teardown_session(task_id) is None


def test_роль_стенда_сообщает_о_неудаче(engine, fake, repo, monkeypatch):
    """«Не поднялся» должно быть видно владельцу, а не молча пропасть, и
    после этого стенд можно поднять снова."""
    from orch import panels, stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {})
    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "stand")
    first = engine.stand_session(task_id)
    engine.stand_result(task_id, None, "нет docker-compose.yml")
    kinds = [(e["kind"], e["payload"]) for e in engine.db.events(task_id, limit=5)]
    assert any(k == "stand_failed" and "docker-compose" in (p or "") for k, p in kinds)
    task = engine.db.task(task_id)
    assert task["stand_port"] is None and engine.stand_session(task_id) is None

    pane = json.dumps(panels.task_pane(engine.db, task, "s9", "http://x"), ensure_ascii=False)
    assert "Поднять стенд снова" in pane and "docker-compose" in pane
    assert engine.button(task_id, task["revision"], "stand") == "роль «Стенд» поднимает окружение"
    assert engine.stand_session(task_id) not in (None, first)


def test_заказанный_стенд_поднимается_на_любой_остановке(engine, fake, repo, monkeypatch):
    """У задачи без ворот ворот не будет, а смотреть владелец придёт всё равно."""
    from orch import stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {"APP_PORT": 8020})
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="посмотреть глазами",
        sheet_edits={"one.after": True}, stand=True,
    )
    engine.reconcile()
    turn(engine, fake, task_id, "one", 1, None)     # шаг сдан, задача на воротах
    task = engine.db.task(task_id)
    assert task["status"] == "waiting" and task["wait_reason"] == "gate"
    assert engine.stand_session(task_id), "к воротам стенд должен уже подниматься"


def test_движок_добивает_уборку_если_роль_не_справилась(engine, fake, repo, monkeypatch):
    """Стенд обязан погаснуть: агент — предпочтительный путь, но не единственный."""
    from orch import stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {"APP_PORT": 8020})
    monkeypatch.setattr(stands, "gone", lambda name: False)
    downs = []
    monkeypatch.setattr(stands, "down", lambda task, name: downs.append(name) or "")

    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "stand")
    engine.stand_result(task_id, 8020, None)
    task = engine.db.task(task_id)
    name = task["stand"]
    engine.button(task_id, task["revision"], "close")

    engine.watch_teardown()                      # уборщик ещё в силе — ждём
    assert downs == []

    with engine.db.tx():                         # прошло больше отпущенного
        engine.db.conn.execute(
            "UPDATE aside_run SET started_at = '2020-01-01T00:00:00Z' WHERE id IN "
            "(SELECT r.id FROM aside_run r JOIN aside a ON a.id = r.aside_id "
            "WHERE a.name = 'stand-down' AND a.scope_key = ?)",
            (task_id,),
        )
    engine.watch_teardown()
    assert downs == [name]
    task = engine.db.task(task_id)
    assert task["stand"] is None and engine.teardown_session(task_id) is None
    kinds = [e["kind"] for e in engine.db.events(task_id, limit=6)]
    assert "teardown_forced" in kinds


def test_копия_живёт_пока_убирают_стенд(engine, fake, repo, monkeypatch):
    """Уборщик работает в этой копии: снести её раньше — оставить стенд живым."""
    from orch import stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {"APP_PORT": 8020})
    monkeypatch.setattr(stands, "gone", lambda name: False)
    monkeypatch.setattr(stands, "down", lambda task, name: "")

    task_id = start(engine, repo)
    copy = Path(engine.db.task(task_id)["worktree_path"])
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "stand")
    fake.rows.clear()                       # сессии удалили — задача брошена
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == "abandoned"
    engine.reconcile()
    assert copy.is_dir(), "копию нельзя сносить, пока уборщик в ней работает"

    monkeypatch.setattr(stands, "gone", lambda name: True)
    engine.reconcile()                      # уборщик отчитался
    engine.reconcile()                      # теперь можно и копию
    assert not copy.exists()


def test_стенд_поднимается_и_без_ворот(engine, fake, repo, monkeypatch):
    """Задача с выключенными воротами встаёт иначе — на вопросе или без сигнала."""
    from orch import stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {"APP_PORT": 8020})
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="без ворот",
        sheet_edits={"one.after": False}, stand=True,
    )
    engine.reconcile()
    sid = session_of(engine, task_id)
    до_остановки_без_сигнала(engine, fake, sid)
    task = engine.db.task(task_id)
    assert task["status"] == "waiting" and engine.stand_session(task_id)


def test_комментарий_владельца_доезжает_до_роли_куда_он_вернул(engine, fake, repo):
    """Слова владельца — единственное «почему» для роли, к которой он вернул.

    Кнопка панели комментария не несёт; он приходит через `orch gate back
    --comment` или `orch task move --comment`, и должен оказаться в промпте
    того захода, который владелец завёл этим движением.
    """
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")     # ворота на исходе ok
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "gate"

    engine.button(task_id, task["revision"], "back", target="one", comment="граница не та")
    engine.reconcile()
    text = fake.prompts[-1][1]
    assert "## Комментарии владельца" in text
    assert "граница не та" in text
    assert "вернул владелец с комментарием" in text


def test_возврат_кнопкой_без_комментария_не_обещает_его_роли(engine, fake, repo):
    """Пустая рубрика «Комментарии владельца» и обещание «он ниже» — враньё."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)

    engine.button(task_id, task["revision"], "back", target="one")
    engine.reconcile()
    text = fake.prompts[-1][1]
    assert "## Комментарии владельца" not in text
    assert "вернул владелец кнопкой, без комментария" in text


def test_кнопка_владельца_добавляет_заход_шагу_с_исчерпанным_пределом(engine, fake, repo):
    """Предел заходов держит роли, а не владельца: он послал — шаг обязан пойти."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")          # ворота на исходе ok

    # У шага `one` предел по умолчанию три; посылаем туда пять раз и каждый
    # раз шаг обязан завести заход, а не встать по `max_runs`.
    for _ in range(5):
        task = engine.db.task(task_id)
        assert "вернул на one" in engine.button(task_id, task["revision"], "back", target="one")
        engine.reconcile()
        task = engine.db.task(task_id)
        assert task["wait_reason"] != "max_runs", "кнопка привела задачу на запертый шаг"
        run = engine.db.open_run(task_id)
        assert run is not None and run["step"] == "one"
        turn(engine, fake, task_id, "one", run["n"], None)

    assert len(engine.db.runs_of_step(task_id, "one")) == 6


def test_контекст_own_возвращает_роль_в_её_же_сессию(engine, fake, repo, monkeypatch):
    """Сведение после ревью идёт там же, где шаг работал в первый раз."""
    chain = parse_chain(CHAIN.replace(
        "  - id: two\n    run: {agent: claude, model: haiku}",
        "  - id: two\n    context: own\n    run: {agent: claude, model: haiku}",
    ), "t")
    monkeypatch.setattr(engine, "chain_of", lambda task: chain)

    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    first = engine.db.last_run_of_step(task_id, "two")["session_id"]
    turn(engine, fake, task_id, "two", 1, "back")     # исход back — снова в one
    turn(engine, fake, task_id, "one", 2, None)
    second = engine.db.last_run_of_step(task_id, "two")["session_id"]
    assert second == first, "второй заход шага должен идти в его же сессии"


def test_сессия_прошлого_шага_перестаёт_звать(engine, fake, repo):
    """Два зовущих шага сразу — владелец не знает, какой из них ждёт его."""
    task_id = start(engine, repo)
    first = session_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    assert fake.urgent.get(first) is False
    assert fake.notify.get(first) is False


def test_возврат_ролью_называет_её_файл_путём(engine, fake, repo):
    """«Читай её файл» без пути — роль ищет работу наугад."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")     # two вернул задачу в one
    text = fake.prompts[-1][1]
    assert "вернула роль two" in text
    assert "two.md`) и есть твоя работа" in text


def test_запоздавший_сигнал_поднимает_вставшую_задачу(engine, fake, repo):
    """Роль, ждавшая подагентов, подала `orch done` уже после остановки."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    до_остановки_без_сигнала(engine, fake, sid)
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "no_signal"

    sign(engine, task_id, "one", 1, None)      # сигнал пришёл с опозданием
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["step"] == "two"
    assert [e for e in engine.db.events(task_id, limit=20) if e["kind"] == "late_signal"]


def test_повторный_заход_со_своей_сессией_нумеруется(engine, fake, repo):
    """Две строки одного шага в сайдбаре без номера не различить."""
    from orch.naming import session_title

    assert session_title("T1", "code-review") == "T1 · code-review"
    assert session_title("T1", "code-review", 2) == "T1 · code-review 2"
    # Шаг, возвращающийся в свою же сессию, остаётся одной строкой.
    assert session_title("T1", "plan", 2, own_session=True) == "T1 · plan"

    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")     # вернулись в one
    engine.reconcile()
    sid = session_of(engine, task_id)
    assert fake.rows[sid]["title"] == f"{task_id} · one 2"


def test_возврат_владельца_обновляет_предел_шагов_ниже(engine, fake, repo):
    """Круг начат владельцем — шаги ниже идут со своим полным пределом."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")     # two → one
    turn(engine, fake, task_id, "one", 2, None)
    turn(engine, fake, task_id, "two", 2, "ok")       # предел two (2) выбран, ворота
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "gate"

    # Владелец вернул работу в one: круг начинается заново.
    engine.button(task_id, task["revision"], "back", target="one")
    engine.reconcile()
    run = engine.db.open_run(task_id)
    turn(engine, fake, task_id, "one", run["n"], None)
    task = engine.db.task(task_id)
    assert task["wait_reason"] != "max_runs", "предел прошлого круга не пускает на шаг"
    assert engine.db.open_run(task_id)["step"] == "two"


# ── предохранитель и сторожа (`ASIDE-PLAN.md` §10, §2) ───────────────────
def kinds(engine, task_id=None):
    rows = engine.db.conn.execute(
        "SELECT kind FROM event" + (" WHERE task_id = ?" if task_id else ""),
        (task_id,) if task_id else (),
    )
    return [r["kind"] for r in rows]


def test_заход_отмечен_событиями_старта_и_конца(engine, fake, repo):
    """Начало и конец захода — поводы проснуться для побочных ролей."""
    task_id = start(engine, repo)
    assert "run_started" in kinds(engine, task_id)

    turn(engine, fake, task_id, "one", 1, None)
    ended = [
        json.loads(r["payload"])
        for r in engine.db.conn.execute(
            "SELECT payload FROM event WHERE kind = 'run_ended' AND task_id = ?", (task_id,)
        )
    ]
    assert len(ended) == 1
    assert ended[0]["step"] == "one" and ended[0]["signalled"] is True


def test_предел_работающих_сессий_придерживает_новый_заход(engine, fake, repo):
    """Сессий столько, сколько выдержит машина: шаг ждёт, а не падает."""
    engine.settings.max_sessions = 1
    first = engine.create_task(chain_name="t", project_path=str(repo), text="Первая.")
    monkey_chain(engine)
    engine.reconcile()
    assert engine.db.open_run(first) is not None      # первая поехала

    second = engine.create_task(chain_name="t", project_path=str(repo), text="Вторая.")
    engine.reconcile()
    assert engine.db.open_run(second) is None, "вторая задача завела сессию сверх предела"
    assert "sessions_capped" in kinds(engine)

    # Первая закончила ход — место освободилось, вторая едет.
    fake.set_status(session_of(engine, first), "idle")
    engine.settings.max_sessions = 2
    engine.reconcile()
    assert engine.db.open_run(second) is not None


def test_нехватка_памяти_придерживает_заход(engine, fake, repo, monkeypatch):
    import orch.engine as mod

    monkeypatch.setattr(mod, "free_memory_mb", lambda: 100)
    task_id = engine.create_task(chain_name="t", project_path=str(repo), text="Тесная машина.")
    monkey_chain(engine)
    engine.reconcile()
    assert engine.db.open_run(task_id) is None
    assert "memory_low" in kinds(engine)


def test_сторож_замечает_две_задачи_в_одном_файле(engine, fake, repo):
    """Соседей не видит ни один шаг: это факт, и его считает git, а не модель."""
    import json as _json

    monkey_chain(engine)
    первая = engine.create_task(chain_name="t", project_path=str(repo), text="Первая.")
    вторая = engine.create_task(chain_name="t", project_path=str(repo), text="Вторая.")
    engine.reconcile()

    for task_id in (первая, вторая):
        task = engine.db.task(task_id)
        (Path(task["worktree_path"]) / "общий.py").write_text("правка\n", encoding="utf-8")
    engine.reconcile()

    clash = [
        _json.loads(r["payload"])
        for r in engine.db.conn.execute("SELECT payload FROM event WHERE kind = 'watch_file_clash'")
    ]
    assert clash and "общий.py" in clash[0]["files"]
    assert {clash[0]["with"], clash[0]["pair"].split("+")[0]} == {первая, вторая}


def test_автономию_живой_задачи_переставляют_целиком(engine, fake, repo):
    """«Не трогай меня до конца» — это восемь щелчков в панели, а нужен один."""
    import json as _json

    task_id = start(engine, repo)
    sheet = _json.loads(engine.db.task(task_id)["human_sheet"])
    assert sheet["two"]["after"] == ["ok"]

    assert "переставлена" in engine.set_autonomy(task_id, None, {"*.after": False, "*.ask": False})
    sheet = _json.loads(engine.db.task(task_id)["human_sheet"])
    assert all(v["after"] is False and v["ask"] is False for v in sheet.values())

    # Пресет цепочки берётся целиком, поверх него — точечные правки.
    assert "переставлена" in engine.set_autonomy(task_id, None, {"two.after": True})
    sheet = _json.loads(engine.db.task(task_id)["human_sheet"])
    assert sheet["two"]["after"] is True and sheet["one"]["after"] is False


def test_приёмка_владельцем_пишет_конец_задачи(engine, fake, repo):
    """На конец задачи подписаны роли; без события они молча не срабатывают."""
    import json as _json

    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    turn(engine, fake, task_id, "three", 1, None)

    task = engine.db.task(task_id)
    assert task["status"] == "done"
    концы = [
        _json.loads(r["payload"] or "{}")
        for r in engine.db.conn.execute(
            "SELECT payload FROM event WHERE kind = 'done' AND task_id = ?", (task_id,)
        )
    ]
    assert len(концы) == 1, "событие конца задачи не одно"


def test_стенд_не_считается_убранным_пока_живы_контейнеры(monkeypatch):
    """`ports free` снимает учёт, а контейнер остаётся держать порт."""
    from orch import stand as stands

    вызовы = []

    def подделка(args, cwd=None, timeout=600.0):
        вызовы.append(args)

        class Ответ:
            returncode = 1 if args[:2] == ["ports", "which"] else 0
            stdout = "abc123\n" if args[:2] == ["docker", "ps"] and живые else ""
            stderr = ""

        return Ответ()

    monkeypatch.setattr(stands, "_run", подделка)

    живые = True
    assert not stands.gone("проект-t1"), "стенд с живым контейнером не убран"

    живые = False
    assert stands.gone("проект-t1")


def _вернуть(engine, fake, repo, действие):
    """Довести задачу до ворот на шаге `two` и нажать возврат на `one`."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "gate"
    ответ = engine.button(task_id, task["revision"], действие, target="one")
    return task_id, ответ


def test_возврат_с_памятью_ничего_не_забывает(engine, fake, repo):
    """Обычный возврат — это доводка: файлы и заходы нижних шагов на месте."""
    task_id, ответ = _вернуть(engine, fake, repo, "back")
    ws = ws_of(engine, task_id)
    assert "вернул на one" in ответ
    assert (ws.artifacts / "two.md").exists()
    assert all(not r["void_at"] for r in engine.db.runs_of_step(task_id, "two"))


def test_возврат_начисто_забывает_заходы_и_убирает_артефакты(engine, fake, repo):
    """Переиграли решение: нижние шаги идут заново и не читают своё прошлое.

    Так план после переигранного Решения видел старое `plan-review.md`,
    считал ревью пройденным и уходил на ворота (T26).
    """
    task_id, ответ = _вернуть(engine, fake, repo, "back_clean")
    ws = ws_of(engine, task_id)
    assert "начисто" in ответ
    # Файл нижнего шага уехал в историю, а свой файл шага-цели остался: роль
    # перепишет его сама, а соседям он нужен как основание.
    assert not (ws.artifacts / "two.md").exists()
    assert (ws.artifacts / "one.md").exists()
    убранные = list(ws.history.glob("cleared-*/two.md"))
    assert убранные, "артефакт нижнего шага не сохранён в истории"
    # Забыты и заход нижнего шага, и последний заход самого шага-цели: его
    # сессию шаг с памятью больше не подхватит.
    assert all(r["void_at"] for r in engine.db.runs_of_step(task_id, "two"))
    assert engine.db.runs_of_step(task_id, "one")[-1]["void_at"]
    # Забытый заход не съедает предел: круг начинается заново.
    engine.reconcile()
    свежие = [r for r in engine.db.runs_of_step(task_id, "one") if not r["void_at"]]
    assert len(свежие) == 1 and engine.db.task(task_id)["status"] == RUNNING


def test_живую_роль_не_толкают_даже_когда_aoe_говорит_idle(engine, fake, repo, monkeypatch, tmp_path):
    """`Idle` от моста бывает преждевременным: роль ещё пишет.

    Толчок в такой момент обрывает ей генерацию (T26: восемь обрывов за
    прогон устроил сам движок). Признак жизни берём мимо AoE — по файлу
    транскрипта, который агент пишет сам.
    """
    from orch import digest as dg

    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.acp_ids[sid] = "cec73527-жив"

    # Транскрипт этой сессии только что писался.
    root = engine.db.task(task_id)["worktree_path"] or str(repo)
    monkeypatch.setattr(dg, "TRANSCRIPTS", tmp_path / "projects")
    папка = dg.TRANSCRIPTS / dg.project_slug(root)
    папка.mkdir(parents=True)
    (папка / "cec73527-жив.jsonl").write_text("{}\n", encoding="utf-8")

    fake.finish_turn(sid)
    engine.db.conn.execute("UPDATE event SET at = '2000-01-01T00:00:00Z' WHERE kind = 'idle_seen'")
    engine.db.conn.commit()
    engine.reconcile()
    engine.reconcile()
    assert "подай сигнал" not in fake.prompts[-1][1], "движок оборвал живую роль"
    assert engine.db.task(task_id)["status"] == RUNNING
    # Связь «сессия AoE → файл транскрипта» запомнена: скелет хода больше не
    # склеивается из чужих сессий той же рабочей копии.
    run = engine.db.conn.execute(
        "SELECT acp_session_id FROM run WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)
    ).fetchone()
    assert run["acp_session_id"] == "cec73527-жив"

    # Роль замолчала — файл больше не растёт, и толчок доходит как обычно.
    import os
    старое = 0
    os.utime(папка / "cec73527-жив.jsonl", (старое, старое))
    engine.reconcile()                                   # отметили простой
    engine.db.conn.execute("UPDATE event SET at = '2000-01-01T00:00:00Z' WHERE kind = 'idle_seen'")
    engine.db.conn.commit()
    engine.reconcile()                                   # выдержка вышла — толчок
    assert "подай сигнал" in fake.prompts[-1][1]
