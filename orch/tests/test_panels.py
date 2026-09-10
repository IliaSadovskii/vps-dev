"""Панели: что владелец видит и какие кнопки ему предлагают."""

from __future__ import annotations

import json

import pytest

from orch import panels
from orch.db import RUNNING, WAITING

from test_engine import monkey_chain, session_of, start, turn



def до_остановки_без_сигнала(engine, fake, sid):
    """Довести заход до остановки «нет сигнала».

    Движок толкает несколько раз и выдерживает паузу между толчками, поэтому
    после каждого прохода состариваем отметку толчка: иначе тест ждал бы
    реального времени.
    """
    from tests.test_engine import до_остановки_без_сигнала as довести

    довести(engine, fake, sid)

def blocks_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_пустая_панель_зовёт_завести_задачу(engine):
    pane = panels.home_pane(engine.db, ["/projects/kandev-trial"])
    assert "бэклог пуст" in blocks_text(pane)
    assert "orch.wizard" in blocks_text(pane)


def test_идущая_задача_не_занимает_обзор_а_видна_в_подвале(engine, fake, repo):
    """Про едущие рассказывает сайдбар, обзор — витрина (`UX-PLAN.md`)."""
    task_id = start(engine, repo)
    pane = panels.home_pane(engine.db)
    разделы = [b.get("title") for b in pane["blocks"] if b.get("kind") == "section"]
    assert "Едут" not in разделы and "Очередь" not in разделы
    assert pane["footer"]["text"] == "едут" and pane["footer"]["value"] == "1"


def test_бейдж_строки_сессии_говорит_зачем_смотреть(engine, fake, repo):
    """Подсветку строки хост даёт по `urgent`, а причину — наш бейдж."""
    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    chain = engine.chain_of(task)
    sid = session_of(engine, task_id)
    badge = panels.row_badge(engine.db, task, sid, chain)
    assert badge["text"] == "one 1/3" and badge["tone"] == "info"

    до_остановки_без_сигнала(engine, fake, sid)
    task = engine.db.task(task_id)
    badge = panels.row_badge(engine.db, task, sid, chain)
    assert badge["tone"] == "danger"
    assert "нет сигнала" in badge["text"] and "one" in badge["text"]


def test_строка_прошлого_шага_молчит(engine, fake, repo):
    """У задачи много сессий: бейдж есть только у текущей.

    Пометка «ворота» на строке прошлого шага была бы ложью, а его исход стоил
    второй строки высоты в сайдбаре на каждой из восьми строк задачи.
    """
    task_id = start(engine, repo)
    первая = session_of(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)     # шаг сдан, задача на шаге two
    task = engine.db.task(task_id)
    chain = engine.chain_of(task)
    assert panels.row_badge(engine.db, task, первая, chain) == {}
    текущая = panels.row_badge(engine.db, task, session_of(engine, task_id), chain)
    assert текущая["text"].startswith("two")


def test_предел_заходов_объясняет_что_случилось(engine, fake, repo):
    """На воротах владельцу нужен контекст, а не только кнопки.

    «Предел заходов» — самая непонятная остановка: шаг отработал чисто, а
    задача встала. Без «как сюда пришли» решать не из чего.
    """
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    with engine.db.tx():
        engine.db.bump(task_id, status="waiting", wait_reason="max_runs", step="one")
    task = engine.db.task(task_id)
    текст = panels._what_to_decide(engine.db, task)
    assert "Как сюда пришли: one 1 →" in текст
    assert "уже сходил" in текст
    assert "Ещё заход" in текст and "Принять как есть" in текст


def test_ждущая_задача_первой_и_с_кнопками(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    pane = panels.home_pane(engine.db)
    text = blocks_text(pane)
    assert "Ждут вас" in text
    assert "orch.accept" in text and "orch.back" in text
    assert "Вернуть на «Заглушка one»" in text or "Вернуть на «one»" in text
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
    до_остановки_без_сигнала(engine, fake, sid)
    pane = panels.home_pane(engine.db)
    methods = {a["method"] for a in _actions(pane)}
    assert "orch.again" in methods and "orch.accept_as_is" in methods
    assert "orch.accept" not in methods


def test_вопрос_роли_не_даёт_кнопок_а_зовёт_в_чат(engine, fake, repo):
    task_id = start(engine, repo)
    fake.set_status(session_of(engine, task_id), "Waiting")
    engine.reconcile()
    pane = panels.home_pane(engine.db, [str(repo)])
    assert "ответьте ей в чате" in blocks_text(pane)
    # Кроме вечной «Новой задачи», решать тут нечем: отвечают в чате.
    методы = {b.get("method") for b in _flat(pane["blocks"]) if b.get("method")}
    assert методы == {"orch.wizard"}
    assert not _actions(pane)


def test_строка_ждущей_задачи_ничего_не_нажимает(engine, fake, repo):
    """Строка была кликабельной впустую: метод ничего не делал."""
    task_id = start(engine, repo)
    sid = session_of(engine, task_id)
    до_остановки_без_сигнала(engine, fake, sid)
    строки = [
        b
        for b in _flat(panels.home_pane(engine.db)["blocks"])
        if b.get("kind") == "row" and task_id in str(b.get("label"))
    ]
    assert строки and all("method" not in r for r in строки)


def test_панель_задачи_показывает_путь_файлы_и_лист(engine, fake, repo):
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://127.0.0.1:8065")
    text = blocks_text(pane)
    assert "one → two" in text
    # Файлы ролей открываются файловым менеджером машины, а не служебным
    # маршрутом AoE: тот отдаёт JSON.
    assert f":{panels.FILES_PORT}/files" in text and f"/{task_id}/artifacts/one.md" in text
    assert "Лист автономии" in text
    assert "Журнал" in text


def test_панель_задачи_показывает_последний_ответ_orch(engine, fake, repo):
    from orch import signals

    task_id = start(engine, repo)
    ws = _ws(engine, task_id)
    signals.write_aux(ws.signals, "refused", "one", 1, "исход 'нет' не существует")
    sid = session_of(engine, task_id)
    до_остановки_без_сигнала(engine, fake, sid)
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
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://x", cost_warn=5.0)
    assert "$12" in blocks_text(pane)


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


def test_ворота_не_называют_владельцу_исход(engine, fake, repo):
    """Имя исхода — словарь движка: ни `None`, ни `choice` владельцу не показываем."""
    import json as _json

    task_id = start(engine, repo)
    sheet = _json.loads(engine.db.task(task_id)["human_sheet"])
    sheet["one"]["after"] = True
    with engine.db.tx():
        engine.db.bump(task_id, human_sheet=_json.dumps(sheet, ensure_ascii=False))
    turn(engine, fake, task_id, "one", 1, None)
    text = blocks_text(panels.home_pane(engine.db))
    assert "None" not in text
    assert "закончил ход и ждёт вас" in text
    assert "исходом" not in text


def test_на_пределе_заходов_владелец_выбирает_исход(engine, fake, repo):
    """«Принять как есть» не повторяет прошлый исход: он и ведёт по кругу."""
    from tests.test_engine import start_self

    task_id = start_self(engine, repo)
    turn(engine, fake, task_id, "one", 1, "again")
    turn(engine, fake, task_id, "one", 2, "again")
    assert engine.db.task(task_id)["wait_reason"] == "max_runs"

    labels = [a["label"] for a in _actions(panels.home_pane(engine.db))]
    assert any("Считать ход законченным" in x for x in labels)
    assert len([x for x in labels if "Считать ход законченным" in x]) == 2

    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept_as_is", target="ok")
    assert engine.db.task(task_id)["step"] == "two"


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
    assert rows[0]["href"] == f"https://{panels.HOST}:8065/session/{sid}"
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


def _flat(blocks):
    for b in blocks:
        yield b
        for key in ("children",):
            if isinstance(b.get(key), list):
                yield from _flat(b[key])


def test_очередь_видна_на_обзоре_с_причиной(engine, repo):
    """Задача в очереди сессии не имеет: не покажи её тут — пропадёт совсем."""
    from test_engine import monkey_chain

    monkey_chain(engine)
    первая = engine.create_task(
        chain_name="t", project_path=str(repo), text="первая", branch="общая"
    )
    engine.create_task(chain_name="t", project_path=str(repo), text="вторая", branch="общая")
    with engine.db.tx():
        engine.db.bump(первая, status="waiting", wait_reason="gate")

    pane = panels.home_pane(engine.db)
    строки = [b for b in _flat(pane["blocks"]) if b.get("kind") == "row"]
    вторая = [r for r in строки if "вторая" in r["label"]][0]
    assert f"работает {первая}" in вторая["sublabel"]
    assert вторая["value"] == "общая"


def test_заявка_из_бэклога_не_запускается_щелчком_по_строке(engine, repo):
    """Раньше строка целиком запускала задачу: случайный тык уводил в работу."""
    from test_engine import monkey_chain

    monkey_chain(engine)
    engine.create_task(
        chain_name="t", project_path=str(repo), text="заявка роли",
        backlog=True, author="T7",
    )
    pane = panels.home_pane(engine.db)
    строки = [b for b in _flat(pane["blocks"]) if b.get("kind") == "row"]
    заявка = [r for r in строки if "заявка роли" in r["label"]][0]
    assert "method" not in заявка, "строка бэклога не должна запускать задачу"
    assert "завела роль задачи T7" in заявка["sublabel"]

    методы = {a["method"] for a in _actions(pane)}
    # «В работу» ведёт к мастеру: цепочку, ветку и автономию спрашивают в чате.
    assert методы == {"orch.wizard", "orch.close"}
    assert "orch.start" not in методы
    режимы = {
        a["params"].get("mode") for a in _actions(pane) if a["method"] == "orch.wizard"
    }
    assert режимы == {None, "text"}


def test_снятая_задача_не_попадает_в_готово(engine, repo):
    """«Закрыл заявку» и «довёл до конца» — разные вещи, и в панели тоже."""
    from test_engine import monkey_chain

    monkey_chain(engine)
    сделана = engine.create_task(chain_name="t", project_path=str(repo), text="сделана")
    снята = engine.create_task(
        chain_name="t", project_path=str(repo), text="снята", backlog=True
    )
    with engine.db.tx():
        engine.db.bump(сделана, status="done", closed_at="2026-09-06T00:00:00Z")
    t = engine.db.task(снята)
    engine.button(снята, t["revision"], "close")

    pane = panels.home_pane(engine.db)
    разделы = {b.get("title"): b for b in pane["blocks"] if b.get("kind") == "section"}
    # Прошлого на обзоре нет вовсе: ни готовых, ни снятых (2026-09-07).
    assert set(разделы) == {"Новая задача"}
    assert engine.db.task(сделана)["status"] == "done"
    assert engine.db.task(снята)["status"] == "closed"


def test_рабочие_копии_задач_не_считаются_проектами(tmp_path):
    """Иначе список «Новая задача» зарастает копиями прошлых задач."""
    import subprocess

    from orch.plugin import _is_project_root

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    copy = tmp_path / "repo-orch" / "t1-x"
    copy.mkdir(parents=True)
    subprocess.run(
        ["git", "worktree", "add", "-q", str(copy), "-b", "t1-x"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    assert _is_project_root(str(root))
    assert not _is_project_root(str(copy))


def test_панель_показывает_три_состояния_стенда(engine, fake, repo, monkeypatch):
    """Кнопка, «поднимается», адрес — и причина, если сорвалось."""
    from orch import stand as stands

    monkeypatch.setattr(stands, "claim", lambda task: (stands.name_of(task), ""))
    monkeypatch.setattr(stands, "ports_of", lambda name: {"APP_PORT": 8020})
    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    строки = json.dumps(panels.task_pane(engine.db, task, "s9", "http://x"), ensure_ascii=False)
    assert "Поднять стенд" in строки

    engine.button(task_id, task["revision"], "stand")
    task = engine.db.task(task_id)
    assert "поднимается" in blocks_text(panels.task_pane(engine.db, task, "s9", "http://x"))

    engine.stand_result(task_id, None, "нет docker-compose.yml")
    task = engine.db.task(task_id)
    текст = blocks_text(panels.task_pane(engine.db, task, "s9", "http://x"))
    # Причина видна, и стенд можно поднять снова: сессия роли отпущена.
    assert "Поднять стенд снова" in текст and "docker-compose" in текст

    engine.stand_result(task_id, 8020, None)
    task = engine.db.task(task_id)
    assert ":8020/" in blocks_text(panels.task_pane(engine.db, task, "s9", "http://x"))


def test_файлы_ролей_только_написанные_и_текущий_первым(engine, fake, repo):
    """Ссылка на ненаписанный файл вела бы в пустоту; на воротах нужен файл
    той роли, что только что сдала ход."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")          # ворота на two
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://x")
    files = [b for b in pane["blocks"] if b.get("title") == "Файлы ролей"][0]["children"]
    assert [r["label"] for r in files] == ["two.md", "one.md"]
    assert "текущий шаг" in files[0]["sublabel"]
    assert "three.md" not in blocks_text(pane)


def test_бэклог_строкой_а_не_простынёй(engine, repo):
    from test_engine import monkey_chain

    monkey_chain(engine)
    engine.create_task(
        chain_name="t", project_path=str(repo), text="идея: " + "слово " * 300, backlog=True
    )
    pane = panels.home_pane(engine.db)
    rows = [b for b in _flat(pane["blocks"]) if b.get("kind") == "row" and "идея" in b["label"]]
    assert len(rows) == 1 and len(rows[0]["sublabel"]) < 200 and len(rows[0]["tooltip"]) <= 800
    assert not [b for b in _flat(pane["blocks"]) if b.get("kind") == "note" and "слово" in b.get("text", "")]


def test_панель_задачи_говорит_словами_а_не_кодами(engine, fake, repo):
    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    pane = panels.task_pane(engine.db, task, "s9", "http://x")
    head = pane["blocks"][0]
    assert head["value"] == "едет" and task["branch"] in head["sublabel"]
    journal = [b for b in pane["blocks"] if b.get("title") == "Журнал"][0]["children"]
    assert any(r["label"] == "промпт отправлен роли" for r in journal)
    assert not any("{" in r["sublabel"] for r in journal)


def test_ссылки_панели_ведут_на_адрес_машины_а_не_на_петлю():
    """Панель читают снаружи машины: `127.0.0.1` там не открывается."""
    from orch.panels import HOST, public

    assert public("http://127.0.0.1:8065/session/s1") == f"https://{HOST}:8065/session/s1"
    assert public("http://localhost:8065/a?b=c") == f"https://{HOST}:8065/a?b=c"
    # Чужой адрес не трогаем: стенд задачи уже отдан по имени машины.
    assert public(f"https://{HOST}:8030/") == f"https://{HOST}:8030/"


def test_находка_рисуется_в_панели_с_кнопками(engine, fake, repo):
    """Без бота панель — единственное место, где видно находку роли."""
    from orch import panels

    from tests.test_engine import start

    task_id = start(engine, repo)
    aside_id = engine.db.aside_open("tune", "run", task_id, task_id)
    with engine.db.tx():
        engine.db.note_add(
            aside_id, None, task_id, "hold", "Ревью читало не тот файл", "Подробности.",
            [{"verb": "restart", "target": None, "label": "перезапустить шаг"}],
        )
    pane = panels.task_pane(engine.db, engine.db.task(task_id), "s1", "http://x")
    callout = next(b for b in pane["blocks"]
                   if b.get("kind") == "callout" and b.get("title") == "Ревью читало не тот файл")
    labels = [a["label"] for a in callout["actions"]]
    assert labels[0] == "Ничего не делать" and "перезапустить шаг" in labels
    assert all(a["method"] == "orch.note" for a in callout["actions"])


def test_решения_под_рукой_всегда(engine, fake, repo):
    """Пауза, «начать шаг заново» и «закрыть» нужны и тогда, когда задача едет.

    Раньше эти три вещи жили только в кнопках остановки — то есть были
    недоступны ровно тогда, когда прогон едет не туда (T37, 2026-09-10).
    """
    from orch import panels

    from tests.test_engine import start

    task_id = start(engine, repo)
    pane = panels.task_pane(engine.db, engine.db.task(task_id), "s1", "http://x")
    решения = next(b for b in pane["blocks"] if b.get("title") == "Решения")
    методы = [a["method"] for a in решения["children"]]
    assert методы[:2] == ["orch.pause", "orch.restart_step"]
    assert методы[-1] == "orch.close"
    откаты = [a for a in решения["children"] if a["method"] == "orch.rewind"]
    assert [a["params"]["target"] for a in откаты] == ["one", "two", "three"], (
        "откатить можно на любой шаг цепочки, а не только на разрешённые возвраты"
    )

    task = engine.db.task(task_id)
    assert "на паузе" in engine.button(task_id, task["revision"], "pause")
    задача = engine.db.task(task_id)
    assert задача["wait_reason"] == "paused"
    # На паузе движок задачу не трогает: проход не заводит новых заходов.
    было = len(engine.db.runs_of_step(task_id, "one"))
    engine.reconcile()
    assert len(engine.db.runs_of_step(task_id, "one")) == было

    pane = panels.task_pane(engine.db, engine.db.task(задача["id"]), "s1", "http://x")
    решения = next(b for b in pane["blocks"] if b.get("title") == "Решения")
    assert "orch.pause" not in [a["method"] for a in решения["children"]], "уже на паузе"


def test_подпись_кнопки_зависит_от_остановки(engine, fake, repo):
    """«Ещё заход» на паузе — враньё: захода не было, надо «Продолжить»."""
    from orch import panels

    from tests.test_engine import start

    task_id = start(engine, repo)
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "pause")

    pane = panels.task_pane(engine.db, engine.db.task(task_id), "s1", "http://x")
    callout = next(b for b in pane["blocks"] if b.get("kind") == "callout")
    assert [a["label"] for a in callout["actions"]] == ["Продолжить"]


def test_панель_закрытой_задачи_рисуется_без_ворот(engine, fake, repo):
    """Панель рисуется толчком: перестанешь обновлять — в сессии навсегда
    застынет кадр с кнопкой «Принять» у принятой задачи."""
    from orch import panels

    from tests.test_engine import start, turn

    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    turn(engine, fake, task_id, "three", 1, None)

    task = engine.db.task(task_id)
    assert task["status"] == "done"
    pane = panels.task_pane(engine.db, task, "s1", "http://x")
    вердикты = [b for b in pane["blocks"] if b.get("kind") == "callout"]
    assert not вердикты, "у закрытой задачи не должно быть ворот с кнопками"
    шапка = pane["blocks"][0]
    assert шапка["value"] == "готово"
