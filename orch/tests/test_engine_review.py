"""Ревью движка 2026-09-10: дефекты, найденные чтением, каждый со сценарием.

Сценарии здесь — не «как должно быть в идеале», а «что ломалось»: каждый
тест падал на коде до правки (проверено, ломая правку обратно).
"""

from __future__ import annotations

import json
import subprocess

from orch import signals
from orch.db import DONE, RUNNING, WAITING
from test_engine import (
    CHAIN,
    monkey_chain,
    session_of,
    sign,
    start,
    start_self,
    turn,
    ws_of,
    до_остановки_без_сигнала,
)


def _commit(root, name: str, msg: str) -> str:
    (root / name).write_text(msg, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg],
        cwd=root, check=True,
    )
    return _head(root)


def _head(root) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()


# ── папка задачи и git ───────────────────────────────────────────────────
def test_папка_задачи_исключена_из_git_в_рабочей_копии(engine, fake, repo):
    """`info/exclude` писался в `.git/worktrees/<имя>/info/`, а git читает
    только общий: `.orch/` стоял как `??` в каждой копии задачи, и
    `git add -A` роли уносил папку задачи в PR (живая копия T37)."""
    task_id = start(engine, repo)
    ws = ws_of(engine, task_id)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ws.root, capture_output=True, text=True
    ).stdout
    assert ".orch" not in status, status
    assert subprocess.run(["git", "check-ignore", "-q", ".orch/x"], cwd=ws.root).returncode == 0


# ── сигналы забытых заходов ──────────────────────────────────────────────
def test_после_возврата_начисто_старый_сигнал_не_сходит_за_новый(engine, fake, repo):
    """Заход после «начисто» снова первый — и файл `one-1.json` от забытого
    захода лежит на месте. Движок принимал его за сдачу нового хода, а
    `orch done` роли отказывал: «ход уже сдан» (T37, 2026-09-10, `scoping-1-refused-1.json`).
    """
    task_id = start(engine, repo)
    ws = ws_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)          # one сдан сигналом one-1.json
    ws.logs.mkdir(parents=True, exist_ok=True)
    (ws.logs / "two.txt").write_text("вывод команд two#1", encoding="utf-8")
    старый_промпт = (ws.prompts / "one-1.md").read_text(encoding="utf-8")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "restart_step", target="one")
    engine.reconcile()                                   # новый заход one, снова n=1
    run = engine.db.open_run(task_id)
    assert run["step"] == "one" and run["n"] == 1
    assert not signals.done_path(ws.signals, "one", 1).exists(), "сигнал забытого захода остался"
    assert list(ws.history.glob("cleared-*/signals/one-1.json")), "сигнал не сохранён в истории"
    # Промпт забытого захода тоже в истории, а не перезаписан новым.
    сохранённый = list(ws.history.glob("cleared-*/prompts/one-1.md"))
    assert сохранённый and сохранённый[0].read_text(encoding="utf-8") == старый_промпт
    # Лог стёртого шага ниже уехал, лог самого шага-цели роль дописывает.
    assert not (ws.logs / "two.txt").exists()
    assert list(ws.history.glob("cleared-*/logs/two.txt"))

    # Ход кончился без своего сигнала — движок не должен счесть его сданным.
    fake.finish_turn(session_of(engine, task_id))
    engine.reconcile()
    assert engine.db.task(task_id)["step"] == "one"
    assert engine.db.open_run(task_id) is not None, "заход закрыт чужим сигналом"
    # А роли ничто не мешает сдать ход самой: «ход уже сдан» больше не бывает.
    turn(engine, fake, task_id, "one", 1, None)
    assert engine.db.task(task_id)["step"] == "two"


def test_история_забытого_захода_не_перезаписывается_новым(engine, fake, repo):
    """После «начисто» новый первый заход писал `history/one-1/` поверх
    старого: «убрано в историю, владелец вправе прочитать» было неправдой
    (T37: `history/scoping-1/artifacts/scoping.md` датирован третьим заходом)."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None, body="## Итог\nпервая жизнь\n")
    ws = ws_of(engine, task_id)
    assert (ws.history / "one-1" / "artifacts" / "one.md").read_text(encoding="utf-8").endswith("первая жизнь\n")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "restart_step", target="one")
    engine.reconcile()
    turn(engine, fake, task_id, "one", 1, None, body="## Итог\nвторая жизнь\n")
    старые = list(ws.history.glob("cleared-*/history/one-1/artifacts/one.md"))
    assert старые and старые[0].read_text(encoding="utf-8").endswith("первая жизнь\n")
    assert (ws.history / "one-1" / "artifacts" / "one.md").read_text(encoding="utf-8").endswith("вторая жизнь\n")


def test_save_history_не_пишет_поверх_чужой_папки(tmp_path):
    """Страховка на случай, когда папку не убрали: старая уезжает в сторону."""
    from orch.workspace import Workspace

    ws = Workspace(tmp_path, "T1")
    ws.artifacts.mkdir(parents=True)
    (ws.artifacts / "one.md").write_text("старое", encoding="utf-8")
    ws.save_history("one", 1, None)
    (ws.artifacts / "one.md").write_text("новое", encoding="utf-8")
    ws.save_history("one", 1, None)
    assert (ws.history / "one-1" / "artifacts" / "one.md").read_text(encoding="utf-8") == "новое"
    в_стороне = [p for p in ws.history.glob("one-1.*") if p.is_dir()]
    assert в_стороне and (в_стороне[0] / "artifacts" / "one.md").read_text(encoding="utf-8") == "старое"


def test_откат_уносит_и_сигналы_забытых_заходов(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "rewind", target="one")
    ws = ws_of(engine, task_id)
    assert not signals.done_path(ws.signals, "one", 1).exists()


# ── запоздавший сигнал ───────────────────────────────────────────────────
def _встать_без_сигнала_на(engine, fake, repo, step: str):
    task_id = start(engine, repo)
    if step != "one":
        turn(engine, fake, task_id, "one", 1, None)
    if step == "three":
        turn(engine, fake, task_id, "two", 1, "ok")
        task = engine.db.task(task_id)
        engine.button(task_id, task["revision"], "accept")
        engine.reconcile()
    sid = session_of(engine, task_id)
    до_остановки_без_сигнала(engine, fake, sid)
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "no_signal"
    assert task["step"] == step
    return task_id


def test_запоздавший_сигнал_уважает_ворота(engine, fake, repo):
    """Ворота листа автономии действуют и на сигнал, пришедший с опозданием.

    Иначе задача с `after: [ok]` уезжала на следующий шаг мимо владельца —
    ровно там, где он просил остановиться.
    """
    task_id = _встать_без_сигнала_на(engine, fake, repo, "two")
    sign(engine, task_id, "two", 1, "ok")
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["step"] == "two", "запоздавший сигнал проскочил ворота"
    assert task["status"] == WAITING and task["wait_reason"] == "gate"


def test_запоздавший_сигнал_на_последнем_шаге_закрывает_задачу(engine, fake, repo):
    """`next: done` — конец задачи, а не шаг с именем «done».

    Движок писал `step = 'done'`, статус `running`, и каждый проход падал на
    `chain.step('done')` — задача висела вечно.
    """
    task_id = _встать_без_сигнала_на(engine, fake, repo, "three")
    sign(engine, task_id, "three", 1, None)
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == DONE and task["closed_at"] and task["step"] is None
    engine.reconcile()
    assert not [e for e in engine.db.events(task_id) if e["kind"] == "engine_error"]


def test_запоздавший_сигнал_без_артефакта_не_принимается(engine, fake, repo):
    """Сигнал написан руками, файла нет — это не сдача (правило то же, что в `on_idle`)."""
    task_id = _встать_без_сигнала_на(engine, fake, repo, "one")
    ws = ws_of(engine, task_id)
    signals.write_done(ws.signals, "one", 1, None)      # без артефакта
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["step"] == "one" and task["wait_reason"] == "no_signal"


# ── события захода ───────────────────────────────────────────────────────
def test_события_захода_не_путаются_с_заходом_с_похожим_номером(engine):
    """`LIKE '%"run": 1%'` ловил и заход 12: побудки и толчки считались чужие."""
    db = engine.db
    db.event("T1", "worker_wake", {"run": 1, "session": "a"})
    db.event("T1", "worker_wake", {"run": 12, "session": "b"})
    db.event("T1", "worker_wake", {"run": 1})
    assert len(db.run_events("T1", "worker_wake", 1)) == 2
    assert len(db.run_events("T1", "worker_wake", 12)) == 1
    assert db.run_events("T1", "worker_wake", 2) == []


def test_последний_ответ_orch_не_берётся_из_другого_захода(tmp_path):
    """`one-1*.json` подходил и к `one-10.json`, и к `one-12-refused-1.json`."""
    signals.write_done(tmp_path, "one", 1, None)
    signals.write_aux(tmp_path, "refused", "one", 12, "чужой отказ")
    got = signals.latest(tmp_path, "one", 1)
    assert got and got["run"] == 1 and got["kind"] == "done"


# ── кнопка владельца на идущем ходу ──────────────────────────────────────
def test_кнопка_на_идущем_ходу_обрывает_роль(engine, fake, repo):
    """Откат и «начать заново» доступны, пока роль работает. Заход закрывался
    в базе, а роль продолжала писать в ту же копию — уже поверх сброшенной
    ветки, рядом со следующей ролью."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)                    # сессия в `Running`
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "restart_step", target="one")
    assert sid in fake.cancels, "роль не остановлена, а её заход уже закрыт"


# ── откат ────────────────────────────────────────────────────────────────
def test_откат_не_архивирует_сессию_которую_делит_живой_заход(engine, fake, repo):
    """`three` идёт в сессии `two` (`context: continue`). Откат на `three`
    уносил в архив общую сессию, а `two` оставался живым заходом без неё."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    run = engine.db.open_run(task_id)
    assert run["step"] == "three"
    общая = run["session_id"]
    assert общая == engine.db.last_run_of_step(task_id, "two")["session_id"]

    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "rewind", target="three")
    assert общая not in fake.archived


def test_откат_не_сбрасывает_коммиты_шага_выше_сделанные_позже(engine, fake, repo):
    """Откат на `two` хранит `one.md`, переписанный после `two`, — но ветку
    сбрасывал к началу первого захода `two`, унося коммиты того же `one`."""
    task_id = start(engine, repo)
    ws = ws_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")        # two вернул на one
    _commit(ws.root, "a.txt", "работа two#1")
    engine.reconcile()                                   # one#2 стартует после коммита
    поздняя = _commit(ws.root, "b.txt", "работа one#2, позже two")
    turn(engine, fake, task_id, "one", 2, None)          # едем на two#2
    _commit(ws.root, "c.txt", "работа two#2")

    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "rewind", target="two")
    assert _head(ws.root) == поздняя, "откат унёс коммиты шага, который остался жив"


def test_откат_сохраняет_несохранённую_работу_в_запаске(engine, fake, repo):
    """`git reset --hard` стирал незакоммиченные правки роли безвозвратно:
    запаска ставилась на HEAD, а в HEAD их не было."""
    task_id = start(engine, repo)
    ws = ws_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    _commit(ws.root, "a.txt", "коммит роли")
    (ws.root / "черновик.txt").write_text("не успела закоммитить", encoding="utf-8")

    task = engine.db.task(task_id)
    ответ = engine.button(task_id, task["revision"], "rewind", target="one")
    assert "запаска" in ответ
    запаска = ответ.rsplit("запаска ", 1)[1].strip()
    assert not (ws.root / "черновик.txt").exists()
    в_запаске = subprocess.run(
        ["git", "show", f"{запаска}:черновик.txt"], cwd=ws.root, capture_output=True, text=True
    )
    assert в_запаске.returncode == 0 and "не успела" in в_запаске.stdout
    # Дерево чистое, а папка задачи на месте.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ws.root, capture_output=True, text=True
    ).stdout
    assert status.strip() == "", status
    assert (ws.path / "current.json").exists()


def test_откат_без_коммитов_всё_равно_убирает_незакоммиченное(engine, fake, repo):
    """Реализация правила дерево и не коммитила: `HEAD` совпадал с началом
    захода, откат выходил ни с чем, и следующая роль читала недоделки шага,
    которого «не было» (T37: 12 переписанных тестов и три новых файла)."""
    task_id = start(engine, repo)
    ws = ws_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)          # two#1 идёт, коммитов нет
    (ws.root / "tests_rewritten.py").write_text("правки Реализации", encoding="utf-8")
    task = engine.db.task(task_id)
    ответ = engine.button(task_id, task["revision"], "rewind", target="two")
    assert not (ws.root / "tests_rewritten.py").exists(), "недоделки забытого шага остались"
    assert "запаска" in ответ
    запаска = ответ.rsplit("запаска ", 1)[1].strip()
    assert subprocess.run(
        ["git", "show", f"{запаска}:tests_rewritten.py"], cwd=ws.root, capture_output=True
    ).returncode == 0


# ── круги и пределы ──────────────────────────────────────────────────────
def test_заход_в_ту_же_секунду_что_и_движение_считается_в_круге(engine, fake, repo):
    """Кнопка владельца и заход после неё пишутся в одну секунду (клик → тот
    же проход движка). По времени «строго позже» такой заход выпадал из
    круга, и предел давал на один заход больше (T37: движение 240 и заход 166
    в 02:13:53)."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")          # ворота на two
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "back", target="one")
    engine.reconcile()
    turn(engine, fake, task_id, "one", 2, None)          # two#2 стартует в ту же секунду
    chain = engine.chain_of(engine.db.task(task_id))
    task = engine.db.task(task_id)
    assert len(engine.runs_this_cycle(task, chain.step("two"), chain)) == 1


def test_ещё_заход_не_открывает_шагу_новый_круг(engine, fake, repo):
    """«Дать заход сверх предела» — один заход, а не полный предел заново.

    Любое движение владельца считалось началом круга для всех шагов, и роль,
    гоняющая себя по кругу, после кнопки получала ещё `max_runs` заходов.
    """
    task_id = start_self(engine, repo)
    turn(engine, fake, task_id, "one", 1, "again")
    turn(engine, fake, task_id, "one", 2, "again")
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "max_runs"
    assert "предел поднят" in engine.button(task_id, task["revision"], "again")
    engine.reconcile()
    turn(engine, fake, task_id, "one", 3, "again")       # роль снова просит себя
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "max_runs", "после одного добавленного захода предел не сработал"
    assert len(engine.db.runs_of_step(task_id, "one")) == 3


def test_продолжай_на_исчерпанном_пределе_даёт_заход_сам(engine, fake, repo):
    """Задача встала без сигнала на последнем допустимом заходе; «Продолжай»
    не должна упираться в «предел заходов» вторым щелчком."""
    task_id = start_self(engine, repo)
    turn(engine, fake, task_id, "one", 1, "again")
    sid = session_of(engine, task_id)
    до_остановки_без_сигнала(engine, fake, sid)          # заход 2 кончился молча
    task = engine.db.task(task_id)
    assert task["wait_reason"] == "no_signal"
    engine.button(task_id, task["revision"], "again")
    engine.reconcile()
    task = engine.db.task(task_id)
    assert task["status"] == RUNNING and engine.db.open_run(task_id)["n"] == 3


def test_событие_старта_захода_несёт_его_номер(engine, fake, repo):
    """`run_started.n` — номер захода, а не счёт по кругу: после возврата
    ролью второй заход шага объявлялся первым."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")
    turn(engine, fake, task_id, "one", 2, None)          # two#2
    run = engine.db.open_run(task_id)
    assert run["step"] == "two" and run["n"] == 2
    started = [
        json.loads(e["payload"]) for e in engine.db.events(task_id, limit=50)
        if e["kind"] == "run_started" and json.loads(e["payload"])["run"] == run["id"]
    ]
    assert started and started[0]["n"] == 2


# ── база ─────────────────────────────────────────────────────────────────
def test_сорвавшийся_commit_не_оставляет_открытой_транзакции(engine):
    """После неудачного COMMIT следующая транзакция падала на `BEGIN`:
    «cannot start a transaction within a transaction» — до перезапуска."""
    import sqlite3

    db = engine.db
    real = db.conn

    class Прокси:
        сорвать = True

        def __getattr__(self, name):
            return getattr(real, name)

        def execute(self, sql, *args):
            if sql == "COMMIT" and self.сорвать:
                self.сорвать = False
                raise sqlite3.OperationalError("database is locked")
            return real.execute(sql, *args)

    db.conn = Прокси()
    try:
        try:
            with db.tx():
                db.event("T1", "x", {})
        except sqlite3.OperationalError:
            pass
        assert not real.in_transaction
        with db.tx():
            db.event("T1", "y", {})
    finally:
        db.conn = real


def test_миграция_after_move_заполняет_старые_заходы(tmp_path):
    """Заход, начатый в ту же секунду, что и движение, — после него."""
    import sqlite3

    from orch.db import MIGRATIONS, Db

    # База, как она была до этой миграции: применяем файлы до 020 руками.
    path = tmp_path / "o.db"
    raw = sqlite3.connect(str(path))
    for file in sorted(MIGRATIONS.glob("*.sql")):
        number = int(file.name.split("_", 1)[0])
        if number > 20:
            continue
        raw.executescript(f"BEGIN;\n{file.read_text(encoding='utf-8')}\nPRAGMA user_version = {number};\nCOMMIT;")
    raw.executescript(
        "INSERT INTO task (id, chain, chain_yaml, title, text, project_path, status, "
        "human_sheet, revision, created_at) VALUES "
        "('T1','t','','t','t','/p','running','{}',1,'2026-01-01T00:00:00Z');"
        "INSERT INTO move (task_id, from_step, to_step, actor, trigger, revision, at) VALUES "
        "('T1', NULL, 'one', 'engine', 'start', 1, '2026-01-01T00:00:05Z'),"
        "('T1', 'one', 'one', 'human', 'button', 2, '2026-01-01T00:01:00Z');"
        "INSERT INTO run (task_id, step, n, context, started_at) VALUES "
        "('T1', 'one', 1, 'fresh', '2026-01-01T00:00:05Z'),"
        "('T1', 'one', 2, 'fresh', '2026-01-01T00:01:00Z');"
    )
    raw.close()

    db = Db(path)
    assert [r[0] for r in db.conn.execute("SELECT after_move FROM run ORDER BY id")] == [1, 2]
