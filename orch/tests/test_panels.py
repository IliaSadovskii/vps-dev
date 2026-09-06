"""Панели: что владелец видит и какие кнопки ему предлагают."""

from __future__ import annotations

import json

import pytest

from orch import panels
from orch.db import RUNNING, WAITING

from test_engine import monkey_chain, session_of, start, turn


def blocks_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_пустая_панель_зовёт_завести_задачу(engine):
    pane = panels.home_pane(engine.db)
    assert "Задач нет" in blocks_text(pane)
    assert "orch.new_task" in blocks_text(pane)


def test_идущая_задача_в_разделе_едут(engine, fake, repo):
    task_id = start(engine, repo)
    pane = panels.home_pane(engine.db)
    text = blocks_text(pane)
    assert "Едут" in text and task_id in text
    assert "claude/haiku" in text
    assert pane["footer"]["text"] == "едут"


def test_ждущая_задача_первой_и_с_кнопками(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    pane = panels.home_pane(engine.db)
    text = blocks_text(pane)
    assert "Ждут вас" in text
    assert "orch.accept" in text and "orch.back" in text
    assert "Вернуть на one" in text
    assert pane["footer"]["tone"] == "danger"


def test_кнопки_несут_текущую_ревизию(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    pane = panels.home_pane(engine.db)
    carrying = [a for a in _actions(pane) if "params" in a]
    assert carrying
    for action in carrying:
        assert action["params"]["revision"] == task["revision"]


def test_кнопки_зависят_от_причины(engine, fake, repo):
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    fake.finish_turn(sid)
    engine.reconcile()      # автоматическая просьба закончить
    fake.finish_turn(sid)
    engine.reconcile()      # остановка «нет сигнала»
    pane = panels.home_pane(engine.db)
    methods = {a["method"] for a in _actions(pane)}
    assert "orch.again" in methods and "orch.accept_as_is" in methods
    assert "orch.accept" not in methods


def test_вопрос_роли_не_даёт_кнопок_а_зовёт_в_чат(engine, fake, repo):
    task_id = start(engine, repo)
    fake.set_status(session_of(engine, task_id), "Waiting")
    engine.reconcile()
    pane = panels.home_pane(engine.db)
    assert "ответьте ей в чате" in blocks_text(pane)
    # Кроме вечной «Новой задачи», решать тут нечем: отвечают в чате.
    assert [a["method"] for a in _actions(pane)] == ["orch.new_task"]


def test_панель_задачи_показывает_путь_файлы_и_лист(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://127.0.0.1:8065")
    text = blocks_text(pane)
    assert "one → two" in text
    assert f"/api/sessions/s9/file?path=.orch/{task_id}/artifacts/one.md" in text
    assert "Лист автономии" in text
    assert "Журнал" in text


def test_панель_задачи_показывает_последний_ответ_orch(engine, fake, repo):
    from orch import signals

    task_id = start(engine, repo)
    ws = _ws(engine, task_id)
    signals.write_aux(ws.signals, "refused", "one", 1, "исход 'нет' не существует")
    sid = session_of(engine, task_id)
    fake.finish_turn(sid)
    engine.reconcile()
    fake.finish_turn(sid)
    engine.reconcile()
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://x")
    assert "не существует" in blocks_text(pane)


def test_лист_автономии_не_даёт_щёлкать_пройденные_шаги(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://x")
    rows = [
        r
        for b in pane["blocks"]
        if b.get("title") == "Лист автономии"
        for r in b["children"]
    ]
    by_step = {r["label"]: r for r in rows}
    assert "method" not in by_step["one"]      # пройден
    assert "method" in by_step["two"]          # текущий
    assert "method" in by_step["three"]


def test_дорогой_ход_помечен(engine, fake, repo):
    task_id = start(engine, repo)
    fake.cost = 12.5
    turn(engine, fake, task_id, "one", 1, None)
    pane = panels.home_pane(engine.db, cost_warn=5.0)
    assert "$12" in blocks_text(pane)


def test_лист_новой_задачи_рисует_переключатели(engine):
    from orch.chain import chains_dir, load

    chain = load(chains_dir() / "smoke.yml")
    draft = {
        "chain": "smoke",
        "project_path": "/projects/kandev-trial",
        "text": "",
        "sheet": chain.default_sheet(),
    }
    pane = panels.home_pane(engine.db, draft)
    text = blocks_text(pane)
    assert "Лист автономии" in text
    assert "orch.sheet_toggle" in text
    assert "orch.launch" in text and "orch.backlog" in text
    # Без текста запускать нечего.
    launch = [a for a in _actions(pane) if a["method"] == "orch.launch"][0]
    assert launch["disabled"] is True
    draft["text"] = "Добавить удаление заметки."
    pane = panels.home_pane(engine.db, draft)
    launch = [a for a in _actions(pane) if a["method"] == "orch.launch"][0]
    assert launch["disabled"] is False


def test_панель_влезает_в_предел_хоста(engine, fake, repo):
    """64 КиБ на слот — предел хоста; панель должна оставаться далеко под ним."""
    monkey_chain(engine)
    for i in range(40):
        engine.create_task(chain_name="t", project_path=str(repo), text=f"задача {i}")
    engine.reconcile()
    size = len(json.dumps(panels.home_pane(engine.db), ensure_ascii=False).encode())
    assert size < 64 * 1024, size


def _actions(pane: dict) -> list[dict]:
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("kind") == "action" and node.get("method"):
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(pane)
    return out


def _ws(engine, task_id):
    from orch.workspace import Workspace

    task = engine.db.task(task_id)
    return Workspace(task["worktree_path"] or task["project_path"], task_id)


def test_ворота_шага_с_одним_переходом_без_исхода_в_тексте(engine, fake, repo):
    """У шага с одним переходом исхода нет — «исходом None» владельцу не показываем."""
    import json as _json

    task_id = start(engine, repo)
    sheet = _json.loads(engine.db.task(task_id)["human_sheet"])
    sheet["one"]["after"] = True
    with engine.db.tx():
        engine.db.bump(task_id, human_sheet=_json.dumps(sheet, ensure_ascii=False))
    turn(engine, fake, task_id, "one", 1, None)
    text = blocks_text(panels.home_pane(engine.db))
    assert "None" not in text
    assert "закончил ход. Принять" in text


def test_очистка_поля_живёт_в_нагрузке_кнопки(engine):
    """Отдельная посылка с очисткой затирается перерисовкой — она в кнопке."""
    op = {"kind": "set-text", "id": "clear-1", "text": ""}
    payload = panels.composer_action(None, clear_op=op)
    assert payload["draft_operation"] == op
    assert payload["method"] == "orch.new_task"
    assert "draft_operation" not in panels.composer_action(None)


def test_прикреплённый_комментарий_виден_в_панели_задачи(engine, fake, repo):
    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    pane = panels.task_pane(
        engine.db, task, "s9", "http://x", comment="Верни одну строку."
    )
    assert "Комментарий к следующему движению" in blocks_text(pane)
    assert "Верни одну строку." in blocks_text(pane)


def test_на_пределе_заходов_владелец_выбирает_исход(engine, fake, repo):
    """«Принять как есть» не повторяет прошлый исход: он и ведёт по кругу."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "back")
    turn(engine, fake, task_id, "one", 2, None)
    turn(engine, fake, task_id, "two", 2, "back")
    turn(engine, fake, task_id, "one", 3, None)
    assert engine.db.task(task_id)["wait_reason"] == "max_runs"

    labels = [a["label"] for a in _actions(panels.home_pane(engine.db))]
    assert "Принять как «ok» → three" in labels
    assert "Принять как «back» → one" in labels

    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept_as_is", target="ok")
    assert engine.db.task(task_id)["step"] == "three"


def test_путь_задачи_ведёт_в_сессии_заходов(engine, fake, repo):
    """Сайдбар прячет сессии шагов — путь в панели должен быть дорогой к ним."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://127.0.0.1:8065")
    rows = [
        r
        for b in pane["blocks"]
        if b.get("title") == "Путь задачи"
        for r in b["children"]
    ]
    assert rows[0]["label"] == "one"
    assert rows[0]["href"] == f"http://127.0.0.1:8065/session/{sid}"
    assert rows[-1]["selected"] is True          # текущий шаг помечен


def _draft(**kw):
    from orch.chain import chains_dir, load

    d = {
        "chain": "smoke",
        "project_path": "/projects/kandev-trial",
        "text": "Доработать вход.",
        "sheet": load(chains_dir() / "smoke.yml").default_sheet(),
    }
    d.update(kw)
    return d


def _row(pane, label):
    for b in pane["blocks"]:
        if b.get("kind") == "row" and b.get("label") == label:
            return b
    return None


def test_строка_ветки_предлагает_взять_чужую(engine):
    row = _row(panels.home_pane(engine.db, _draft()), "ветка")
    assert row["value"] == "новая"
    assert row["method"] == "orch.pick_branch"


def test_ожидание_ссылки_блокирует_запуск(engine):
    pane = panels.home_pane(engine.db, _draft(awaiting="branch"))
    assert _row(pane, "ветка")["value"] == "жду ссылку"
    launch = [a for a in _actions(pane) if a["method"] == "orch.launch"][0]
    assert launch["disabled"] is True
    # Кнопка у поля говорит, чего от неё ждут.
    assert panels.composer_action(None, draft_open=True, awaiting="branch")["label"] == (
        "Взять ветку из поля"
    )


def test_выбранная_ветка_видна_и_пускает(engine):
    pane = panels.home_pane(engine.db, _draft(branch="feature/x"))
    row = _row(pane, "ветка")
    assert row["value"] == "feature/x" and row["value_tone"] == "success"
    launch = [a for a in _actions(pane) if a["method"] == "orch.launch"][0]
    assert launch["disabled"] is False


def test_занятая_ветка_не_даёт_запустить(engine):
    pane = panels.home_pane(engine.db, _draft(branch="feature/x", branch_holder="T9"))
    row = _row(pane, "ветка")
    assert "занята задачей T9" in row["sublabel"] and row["value_tone"] == "danger"
    for a in _actions(pane):
        if a["method"] in ("orch.launch", "orch.backlog"):
            assert a["disabled"] is True


def test_лист_новой_задачи_рисуется_в_сессии_где_его_открыли(engine, fake, repo):
    """Кнопка у поля стоит в сессии — значит и «Запустить» должна быть там.

    Пока лист жил только в общей панели на обзоре, человек, нажавший кнопку
    внутри сессии, видел уведомление «теперь Запустить» и пустой экран.
    """
    import orch.plugin as mod

    worker = mod.Worker.__new__(mod.Worker)
    worker.engine = engine
    worker.draft = _draft(session_id="s42")
    worker.drawn = {}
    worker.settings = {}
    worker.session_of_task = {}
    worker.clear_ops = {}
    pushed = []
    worker.ui_set = lambda slot, ident, payload, session_id=None: pushed.append(
        (slot, session_id, payload)
    )
    worker.sessions_now = lambda: [{"id": "s42"}]
    worker._push_if_changed = mod.Worker._push_if_changed.__get__(worker)
    worker._refresh_session_map = mod.Worker._refresh_session_map.__get__(worker)
    worker._clear_op = mod.Worker._clear_op.__get__(worker)
    worker.settings = {"aoe_url": "http://x"}
    mod.Worker.push_all(worker, force=True)

    panes = [(sid, p) for slot, sid, p in pushed if slot == "pane"]
    assert panes, "лист не попал в панель сессии"
    sid, payload = panes[0]
    assert sid == "s42"
    assert payload["title"] == "orch · новая задача"
    assert any(b.get("method") == "orch.launch" for b in _flat(payload["blocks"]))


def _flat(blocks):
    for b in blocks:
        yield b
        for key in ("children",):
            if isinstance(b.get(key), list):
                yield from _flat(b[key])
