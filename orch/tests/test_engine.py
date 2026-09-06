"""Движок против поддельного AoE. Сценарии — `PLAN.md` §11."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


# ── подмостки ────────────────────────────────────────────────────────────
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
    assert fake.colors[sid] == "red"

    engine.button(task_id, task["revision"], "accept", comment="Годится.")
    engine.reconcile()
    assert engine.db.task(task_id)["step"] == "three"

    sid = turn(engine, fake, task_id, "three", 1, None)
    task = engine.db.task(task_id)
    assert task["status"] == DONE and task["closed_at"]


def test_возврат_ролью_и_предел_заходов(engine, fake, repo):
    task_id = start(engine, repo)
    sid = turn(engine, fake, task_id, "one", 1, None)

    # two возвращает на one
    sid = turn(engine, fake, task_id, "two", 1, "back")
    assert engine.db.task(task_id)["step"] == "one"

    # one сдаёт снова, two идёт вторым заходом
    sid = turn(engine, fake, task_id, "one", 2, None)
    assert engine.db.task(task_id)["step"] == "two"

    # второй заход two снова back — предел заходов у two равен 2
    sid = turn(engine, fake, task_id, "two", 2, "back")
    assert engine.db.task(task_id)["step"] == "one"

    sid = turn(engine, fake, task_id, "one", 3, None)
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "max_runs"


def test_ещё_заход_на_пределе_поднимает_предел(engine, fake, repo):
    """Кнопка на пределе заходов обязана дать заход, а не остановить снова."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")
    turn(engine, fake, task_id, "one", 2, None)
    turn(engine, fake, task_id, "two", 2, "back")
    turn(engine, fake, task_id, "one", 3, None)
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "max_runs"

    assert "предел поднят" in engine.button(task_id, task["revision"], "again")
    engine.reconcile()
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and task["step"] == "two"
    assert len(engine.db.runs_of_step(task_id, "two")) == 3


def test_нет_сигнала(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.finish_turn(sid)          # ход кончился, сигнала нет
    engine.reconcile()
    # Первый раз движок сам просит закончить и подать сигнал.
    assert "подай сигнал" in fake.prompts[-1][1]
    assert engine.db.task(task_id)["status"] == RUNNING

    fake.finish_turn(sid)          # роль снова молчит
    engine.reconcile()
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


def test_ошибка_дважды_останавливает(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.set_status(sid, "Error")
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == RUNNING
    fake.set_status(sid, "Error")
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "error"


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
    assert "правил владелец после сдачи" in fake.prompts[-1][1]


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
    import orch.engine as mod

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
    assert names == ["sub-review-defects.md", "sub-review-security.md"]
    # У шага без подагентов список пуст.
    assert engine.sub_prompts(deep.step("scoping")) == []
