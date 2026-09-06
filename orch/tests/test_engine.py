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
    from orch.engine import _slug

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


def test_ветка_занятая_живой_задачей_отклоняется(engine, repo):
    """Две задачи в одной копии писали бы `.orch/` друг поверх друга."""
    from orch.chain import ChainError

    monkey_chain(engine)
    engine.create_task(chain_name="t", project_path=str(repo), text="первая", branch="общая")
    with pytest.raises(ChainError) as exc:
        engine.create_task(chain_name="t", project_path=str(repo), text="вторая", branch="общая")
    assert "занята задачей" in str(exc.value)


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
    assert engine.db.task(first)["status"] == "done"
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


def test_задача_из_заявки_закрывает_её(engine, fake, repo):
    """Мастер заводит задачу с `--from-backlog`: заявка не должна остаться."""
    monkey_chain(engine)
    заявка = engine.create_task(
        chain_name="t", project_path=str(repo), text="черновик", backlog=True
    )
    новая = engine.create_task(
        chain_name="t", project_path=str(repo), text="настоящая", from_backlog=заявка
    )
    assert engine.db.task(заявка)["status"] == "done"
    assert engine.db.task(заявка)["wait_reason"] == "closed_by_owner"
    assert engine.db.task(новая)["status"] in ("queued", "running")


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
    from orch.engine import _title_from

    assert _title_from("**Цель.** Показать дату у каждой заметки в list") == (
        "Показать дату у каждой заметки в list"
    )
    assert _title_from("# Заголовок\nтекст") == "Заголовок"
    assert _title_from("") == "задача"


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
    assert fake.rows[session.id]["group_path"] == "orch/мастер"
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
    assert fake.rows[session.id]["group_path"] == "orch/мастер"
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
    """Две задачи в одной ветке писали бы `.orch/` в один каталог."""
    monkey_chain(engine)
    первая = start(engine, repo)
    ветка = engine.db.task(первая)["branch"]
    with engine.db.tx():
        engine.db.bump(первая, status="waiting", wait_reason="gate")
    вторая = engine.db.conn.execute(
        "INSERT INTO task (id, chain, chain_yaml, title, text, project_path, branch, "
        "group_path, status, human_sheet, revision, created_at) "
        "VALUES ('T99','t',?, 'вторая','вторая',?,?,'orch/T99','queued','{}',1,?)",
        (engine.db.task(первая)["chain_yaml"], str(repo), ветка, "2026-09-06T00:00:00Z"),
    )
    engine.db.conn.commit()
    engine.reconcile()
    task = engine.db.task("T99")
    assert task["wait_reason"] == "branch_busy"
    from orch import panels

    assert первая in panels._what_to_decide(engine.db, task)


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
