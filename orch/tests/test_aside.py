"""Побочные роли: описание, поводы, ходы, находки (`ASIDE-PLAN.md`)."""

from __future__ import annotations

import json

import pytest

from orch import asides
from orch.asides import AsideError, parse
from orch.db import WAITING

from tests.test_engine import monkey_chain, session_of, start, turn


SPEC = """
name: tune
title: Наладчик
scope: run
workspace: task
rights: [read, hold]
enabled: true
wakes:
  - on: [run_started]
    prompt: role-tune-start
    run: {agent: claude, model: sonnet}
  - on: [run_ended]
    prompt: role-tune-review
    run: {agent: claude, model: "opus[1m]", effort: medium}
  - on: [note_decided]
    prompt: role-tune-apply
    run: {agent: claude, model: "opus[1m]", effort: medium}
  - on: [done, closed]
    prompt: role-tune-summary
    run: {agent: claude, model: sonnet}
"""


@pytest.fixture
def tune(tmp_path, monkeypatch, engine):
    """Описание роли на диске вместо заводского каталога.

    Проход после включения ставит курсор роли на сегодня — так же, как на
    живой машине: включили, дальше смотрим только новое.
    """
    folder = tmp_path / "asides"
    folder.mkdir()
    (folder / "tune.yml").write_text(SPEC, encoding="utf-8")
    monkeypatch.setattr(asides, "factory_dir", lambda: folder)
    monkeypatch.setattr(asides, "user_dir", lambda: tmp_path / "нет")
    engine.reconcile()
    return folder


# ── описание ─────────────────────────────────────────────────────────────
def test_описание_читается_и_знает_свои_поводы(tune):
    spec = asides.load_by_name("tune")
    assert spec.kinds() == ("run_started", "run_ended", "note_decided", "done", "closed")
    assert spec.wake_for("run_ended").model == "opus[1m]"
    assert spec.may("hold") and not spec.may("pr")
    assert asides.enabled() and asides.enabled()[0].name == "tune"


def test_ключ_on_в_yaml_не_превращается_в_булево():
    """`on:` в YAML 1.1 — это True; описание всё равно должно читаться."""
    spec = parse("name: x\nwakes:\n  - on: run_ended\n    prompt: p\n")
    assert spec.kinds() == ("run_ended",)


@pytest.mark.parametrize(
    "text, кусок",
    [
        ("name: x\n", "ни одного повода"),
        ("name: x\nscope: небо\nwakes: [{on: a, prompt: p}]\n", "неизвестная область"),
        ("name: x\nrights: [rm]\nwakes: [{on: a, prompt: p}]\n", "неизвестные права"),
        ("name: x\nwakes: [{on: a, prompt: p}, {on: a, prompt: q}]\n", "в двух поводах"),
        ("name: x\nworkspace: где-то\nwakes: [{on: a, prompt: p}]\n", "рабочая копия"),
    ],
)
def test_кривое_описание_отвергается(text, кусок):
    with pytest.raises(AsideError) as exc:
        parse(text, source="тест")
    assert кусок in str(exc.value)


# ── поводы и ходы ────────────────────────────────────────────────────────
def пропуск(engine, run_id):
    return engine.db.aside_run(run_id)["token"] or ""


def повод_текст(fake):
    """Промпт последнего повода: следом за ним могла уехать заводка переписки."""
    return next(t for _, t in reversed(fake.prompts) if "Твой ход" in t)


def асайды(engine):
    return [dict(r) for r in engine.db.conn.execute(
        "SELECT a.name, r.wake, r.session_id, r.ended_at FROM aside_run r "
        "JOIN aside a ON a.id = r.aside_id ORDER BY r.id"
    )]


def test_роль_просыпается_на_старте_захода(engine, fake, repo, tune):
    task_id = start(engine, repo)          # старт уже дал событие run_started
    engine.reconcile()
    ходы = асайды(engine)
    assert [x["wake"] for x in ходы] == ["role-tune-start"]
    assert ходы[0]["session_id"], "роли не создали сессию"
    # Промпт роли получил свой номер хода и контекст задачи.
    текст = fake.prompts[-1][1]
    assert "Твой ход: `A1`" in текст and task_id in текст


def test_выключенная_роль_не_просыпается(engine, fake, repo, tune):
    (tune / "tune.yml").write_text(SPEC.replace("enabled: true", "enabled: false"), encoding="utf-8")
    engine.db.conn.execute("DELETE FROM aside_cursor")
    start(engine, repo)
    engine.reconcile()
    assert асайды(engine) == []


def test_роль_не_разбирает_журнал_до_своего_включения(engine, fake, repo, tune):
    """Включили на живой машине — прошлые задачи её не касаются."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    # Как будто роли на машине не было вовсе, пока эти задачи ехали.
    engine.db.conn.execute("DELETE FROM aside_cursor")
    engine.db.conn.execute("DELETE FROM aside_run")
    engine.db.conn.execute("DELETE FROM aside")
    engine.db.conn.commit()

    engine.reconcile()
    assert асайды(engine) == [], "роль подняла ходы о том, что было до неё"


def test_второй_повод_ждёт_конца_первого_хода(engine, fake, repo, tune):
    start(engine, repo)
    engine.reconcile()
    assert len(асайды(engine)) == 1
    engine.reconcile()
    assert len(асайды(engine)) == 1, "роль завела второй ход, не кончив первый"


def test_ход_роли_закрывается_когда_сессия_освободилась(engine, fake, repo, tune):
    start(engine, repo)
    engine.reconcile()
    sid = асайды(engine)[0]["session_id"]
    fake.finish_turn(sid)
    engine.reconcile()
    assert асайды(engine)[0]["ended_at"], "ход роли не закрылся"
    assert sid not in fake.archived, "сессия живёт до владельца"


def test_сессия_разбора_уезжает_в_архив_после_хода(engine, fake, repo, tune):
    """Повод со своей сессией: ход сдан — карточка не висит в сайдбаре (T26).

    Иначе за прогон их набегает по две на шаг, и живой работы в сайдбаре не
    видно. Найденное роль уже сложила в базу, сводку соберёт общая переписка.
    """
    (tune / "tune.yml").write_text(
        SPEC.replace(
            "  - on: [run_started]\n    prompt: role-tune-start",
            "  - on: [run_started]\n    prompt: role-tune-start\n    session: fresh",
        ),
        encoding="utf-8",
    )
    start(engine, repo)
    engine.reconcile()
    sid = асайды(engine)[0]["session_id"]
    engine.reconcile()
    assert sid not in fake.archived, "сессию убрали, пока ход ещё идёт"

    fake.finish_turn(sid)
    engine.reconcile()          # ход закрылся
    engine.reconcile()          # уборка увидела свободную сессию
    assert sid in fake.archived, "сессия разбора осталась в сайдбаре"


def test_роль_с_поводами_в_своих_сессиях_заводит_общую_переписку(engine, fake, repo, tune):
    """Карточка роли в сайдбаре есть с первого хода, а не с конца прогона.

    Поводы `session: fresh` живут в своих сессиях и уезжают в архив; без
    общей переписки роль на задаче не видна вовсе, а первое слово владельца
    прилетело бы агенту, который не знает, кто он.
    """
    (tune / "tune.yml").write_text(
        SPEC.replace(
            "  - on: [run_started]\n    prompt: role-tune-start",
            "  - on: [run_started]\n    prompt: role-tune-start\n    session: fresh",
        ),
        encoding="utf-8",
    )
    task_id = start(engine, repo)
    engine.reconcile()
    дом = engine.db.aside_live("tune", task_id)["session_id"]
    разбор = асайды(engine)[0]["session_id"]
    assert дом and дом != разбор, "общей переписки роли нет"
    заводка = [t for target, t in fake.prompts if target == дом]
    assert заводка and "Ты побочная роль" in заводка[0], "правила в переписку не уехали"

    fake.finish_turn(разбор)
    engine.reconcile()
    engine.reconcile()
    assert разбор in fake.archived and дом not in fake.archived


def test_повод_в_общую_переписку_не_шлёт_правила_заново(engine, fake, repo, tune):
    """Правила уехали при заводке переписки; повторять их каждый повод незачем."""
    (tune / "tune.yml").write_text(
        SPEC.replace(
            "  - on: [run_started]\n    prompt: role-tune-start",
            "  - on: [run_started]\n    prompt: role-tune-start\n    session: fresh",
        ),
        encoding="utf-8",
    )
    task_id = start(engine, repo)
    engine.reconcile()
    дом = engine.db.aside_live("tune", task_id)["session_id"]
    разбор = асайды(engine)[0]["session_id"]

    run_id = int(engine.db.aside_runs_open()[0]["id"])
    engine.aside_note(run_id, "tell", "Находка", "…", [], пропуск(engine, run_id))
    engine.aside_done(run_id, "done", пропуск(engine, run_id))
    engine.note_decision(1, "say", "Правь только промпт", who="панель")
    fake.finish_turn(разбор)
    fake.finish_turn(дом)
    for _ in range(4):
        engine.reconcile()

    в_дом = [t for target, t in fake.prompts if target == дом]
    assert len(в_дом) >= 2, "повод не доехал в общую переписку"
    assert "Ты побочная роль" not in в_дом[1], "правила уехали второй раз"
    assert "Твоя находка, на которую ответил владелец" in в_дом[1]


def test_строка_роли_помечена_знаком_и_бейджем(engine, fake, repo, tune):
    """Роль стоит в сайдбаре среди шагов задачи — её видно по знаку и бейджу."""
    from orch import panels

    (tune / "tune.yml").write_text(
        SPEC.replace("title: Наладчик", 'title: Наладчик\nicon: "🔧"'), encoding="utf-8"
    )
    start(engine, repo)
    engine.reconcile()
    sid = асайды(engine)[0]["session_id"]
    assert fake.rows[sid]["title"].startswith("T"), fake.rows[sid]["title"]
    assert fake.rows[sid]["title"].endswith("🔧"), "знак роли — в конце строки"
    assert "· Наладчик" in fake.rows[sid]["title"], "имя роли после номера задачи"
    assert fake.unread.get(sid) is False, "точки «не прочитано» нет и у роли"

    assert fake.pinned.get(sid) is True, "строка роли не закреплена наверху группы"

    бейдж = panels.aside_row_badge("Наладчик", "Шаг начал ход", идёт=True)
    assert бейдж["text"] == "шаг начал ход" and бейдж["tone"] == "info"
    дом = panels.aside_row_badge("Наладчик")
    assert дом["text"] == "наладчик" and дом["tone"] == "neutral"


def test_сводка_зовёт_владельца_а_обычный_ход_молчит(engine, fake, repo, tune):
    """Пуш по `Idle` — только на сводке конца прогона, иначе он на каждый шаг."""
    (tune / "tune.yml").write_text(
        SPEC.replace(
            "  - on: [done, closed]\n    prompt: role-tune-summary",
            "  - on: [done, closed]\n    attention: true\n    prompt: role-tune-summary",
        ),
        encoding="utf-8",
    )
    до_конца(engine, fake, repo)          # задача доезжает до конца
    engine.reconcile()
    ходы = асайды(engine)
    обычный = [x for x in ходы if x["wake"] != "role-tune-summary"]
    assert обычный and fake.notify.get(обычный[0]["session_id"]) is False, (
        "обычный ход зовёт владельца пушем"
    )
    for _ in range(12):                   # роль ходит по одному поводу за раз
        сводка = [x for x in асайды(engine) if x["wake"] == "role-tune-summary"]
        if сводка:
            break
        for открытый in engine.db.aside_runs_open():
            fake.finish_turn(открытый["session_id"])
        engine.reconcile()
    assert сводка, "сводка не завелась"
    assert fake.notify.get(сводка[-1]["session_id"]) is True


def test_прошлые_находки_дают_только_сводке(engine, fake, repo, tune):
    """Памяти между прогонами нет — вместо неё лента находок, и только итогу.

    Разбору одного хода чужие прогоны не нужны: это контекст на каждом шаге.
    """
    from tests.test_engine import monkey_chain, turn

    (tune / "tune.yml").write_text(
        SPEC.replace(
            "  - on: [done, closed]\n    prompt: role-tune-summary",
            "  - on: [done, closed]\n    history: 5\n    prompt: role-tune-summary",
        ),
        encoding="utf-8",
    )
    monkey_chain(engine)
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    engine.aside_note(run_id, "tell", "Промпт врёт про заход", "…", [], пропуск(engine, run_id))
    engine.aside_done(run_id, "done", пропуск(engine, run_id))
    engine.note_decision(1, "continue", "", who="panel")

    # Находка «прошлой задачи»: своя в ленту итога не идёт, а чужая — идёт.
    прошлая = engine.create_task(
        chain_name="t", project_path=str(repo), text="прошлая задача", backlog=True
    )
    with engine.db.tx():
        engine.db.conn.execute(
            "UPDATE aside_note SET task_id = ? WHERE id = 1", (прошлая,)
        )

    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    turn(engine, fake, task_id, "three", 1, None)

    разбор = [t for _, t in fake.prompts if "Твой ход" in t][-1]
    assert "Твои находки по прошлым задачам" not in разбор

    for _ in range(12):
        сводка = [x for x in асайды(engine) if x["wake"] == "role-tune-summary"]
        if сводка:
            break
        for sid in list(fake.rows):        # роль ходит по одному поводу за раз
            fake.finish_turn(sid)
        engine.reconcile()
    assert сводка, "сводка не завелась"
    текст = [t for target, t in fake.prompts if target == сводка[-1]["session_id"]][-1]
    assert "Твои находки по прошлым задачам" in текст
    assert прошлая in текст and "Промпт врёт про заход" in текст


def test_роль_кончается_вместе_с_задачей(engine, fake, repo, tune, monkeypatch):
    """Иначе запись роли `live` навсегда, а её переписка — строкой в сайдбаре."""
    import orch.engine as eng

    task_id = до_конца(engine, fake, repo)
    engine.reconcile()
    aside = engine.db.aside_live("tune", task_id)
    assert aside is not None, "роль не заводилась"
    сессии = {r["session_id"] for r in engine.db.aside_runs_of(int(aside["id"]))}

    monkeypatch.setattr(eng, "ARCHIVE_AFTER_H", 0)
    engine.archive_old()
    assert engine.db.aside_live("tune", task_id) is None, "роль осталась живой"
    assert engine.db.aside(int(aside["id"]))["status"] == "done"
    for sid in сессии:
        assert sid in fake.archived, "переписка роли осталась в сайдбаре"


def test_общая_переписка_роли_в_архив_не_уезжает(engine, fake, repo, tune):
    """Разговор владельца с ролью живёт весь прогон, чем бы ход ни кончился."""
    start(engine, repo)
    engine.reconcile()
    sid = асайды(engine)[0]["session_id"]
    fake.finish_turn(sid)
    engine.reconcile()
    engine.reconcile()
    assert sid not in fake.archived


# ── находки ──────────────────────────────────────────────────────────────
def test_находка_с_остановкой_ставит_задачу_на_владельца(engine, fake, repo, tune):
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = engine.db.aside_runs_open()[0]["id"]

    answer = engine.aside_note(
        int(run_id), "hold", "Ревью читало не тот файл",
        "Подробности.", [{"verb": "continue", "target": None, "label": "оставить"}],
        пропуск(engine, run_id),
    )
    assert "N1" in answer
    task = engine.db.task(task_id)
    assert task["status"] == WAITING and task["wait_reason"] == "aside_hold"
    note = engine.db.note(1)
    assert note["severity"] == "hold" and json.loads(note["options"])[0]["verb"] == "continue"
    # Остановка обязана останавливать: идущий ход шага обрывается, иначе роль
    # договорит и уедет дальше, а ответ владельца опоздает (T37, 2026-09-10).
    assert session_of(engine, task_id) in fake.cancels


def test_на_автономии_находка_не_останавливает_задачу(engine, fake, repo, tune):
    """«Решай сам» значит и для наблюдателя: остановка ради вопроса — тот же вопрос.

    Наладчик остановил T37 на шаге плана, хотя лист автономии выключил вопросы
    у всех шагов: задача замерла до ответа, которого владелец не ждал.
    """
    task_id = start(engine, repo)
    with engine.db.tx():
        engine.db.bump(task_id, human_sheet=json.dumps({"one": {"ask": False, "after": False}}))
    engine.reconcile()
    run_id = engine.db.aside_runs_open()[0]["id"]

    engine.aside_note(
        int(run_id), "hold", "Два правила решит агент молча", "Подробности.", [],
        пропуск(engine, run_id),
    )

    assert engine.db.note(1)["severity"] == "log", "находка остаётся, но весом «в сводку»"
    task = engine.db.task(task_id)
    assert task["status"] != WAITING and task["wait_reason"] != "aside_hold"
    assert session_of(engine, task_id) not in fake.cancels


def test_возврат_начисто_снимает_находки_переигранного_хода(engine, fake, repo, tune):
    """Забыли ход — забыли и то, что о нём сказали.

    Карточка с вопросом про план висела в панели, когда самого плана уже не
    было: задача поехала заново со scoping (T37, 2026-09-10).
    """
    monkey_chain(engine)
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)      # шаг one сдан, едем на two
    engine.reconcile()
    run_id = engine.db.aside_runs_open()[0]["id"]
    engine.aside_note(
        int(run_id), "log", "Замечание про шаг two", "Подробности.", [],
        пропуск(engine, run_id),
    )
    assert engine.db.note(1)["state"] == "open"

    task = engine.db.task(task_id)
    assert task["step"] == "two"
    engine.button(task_id, task["revision"], "back_clean", target="one")

    assert engine.db.note(1)["state"] == "dropped", "находка пережила переигранный ход"


def test_роль_без_права_останавливать_только_сообщает(engine, fake, repo, tune):
    (tune / "tune.yml").write_text(SPEC.replace("[read, hold]", "[read]"), encoding="utf-8")
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = engine.db.aside_runs_open()[0]["id"]
    engine.aside_note(int(run_id), "hold", "Что-то не то", "", [], пропуск(engine, run_id))
    assert engine.db.note(1)["severity"] == "log"
    assert engine.db.task(task_id)["status"] != WAITING


def test_роль_закрывает_свой_ход_сама(engine, fake, repo, tune):
    start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    ключ = пропуск(engine, run_id)
    assert "не подходит" in engine.aside_done(run_id, "clean", "чужой-пропуск")
    assert "принят" in engine.aside_done(run_id, "clean", ключ)
    assert engine.db.aside_run(run_id)["outcome"] == "clean"
    assert "уже закрыт" in engine.aside_done(run_id, None, ключ)


def test_предел_сессий_придерживает_и_побочную_роль(engine, fake, repo, tune):
    engine.settings.max_sessions = 1
    start(engine, repo)
    engine.reconcile()
    assert асайды(engine) == [], "роль заняла место сверх предела"


# ── промпт побочной роли ─────────────────────────────────────────────────
def test_промпт_склеен_из_общих_правил_роли_и_контекста(engine, fake, repo, tmp_path, monkeypatch):
    """Заводской Наладчик: общие правила, промпт повода, блок «Что случилось»."""
    from orch import asides as mod

    monkeypatch.setattr(mod, "user_dir", lambda: tmp_path / "нет")
    spec = mod.load_by_name("tune")
    объект = mod.Aside(
        name=spec.name, scope=spec.scope, wakes=spec.wakes, workspace="task",
        rights=spec.rights, includes=spec.includes,
        chains=(), budget={}, enabled=True, title=spec.title,
    )
    monkeypatch.setattr(mod, "enabled", lambda: [объект])
    monkeypatch.setattr(engine, "aside_specs", lambda: [объект])

    with engine.db.tx():                       # роль уже была включена до задачи
        engine.db.cursor_set("tune", "", 0)
    task_id = start(engine, repo)
    текст = повод_текст(fake)
    assert "Ты побочная роль" in текст, "общие правила не приклеились"
    assert "Наладчик: проверка входа" in текст, "промпт повода не приклеился"
    assert "Твой ход: `A1`" in текст and task_id in текст
    assert "Права, выданные тебе: hold, patch, pr, read" in текст


# ── Менеджер проекта ─────────────────────────────────────────────────────
MANAGER = """
name: manager
title: Менеджер проекта
scope: project
enabled: true
workspace: task
rights: [read, patch, pr]
mirror: worktree:project
wakes:
  - on: [done, closed]
    prompt: role-manager
    run: {agent: claude, model: sonnet}
"""


@pytest.fixture
def manager(tmp_path, monkeypatch, engine):
    folder = tmp_path / "asides-manager"
    folder.mkdir()
    (folder / "manager.yml").write_text(MANAGER, encoding="utf-8")
    monkeypatch.setattr(asides, "factory_dir", lambda: folder)
    monkeypatch.setattr(asides, "user_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(asides, "STATE_DIR", tmp_path)
    import orch.aside_role as mod

    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    with engine.db.tx():
        engine.db.cursor_set("manager", "", 0)
    return folder


def до_конца(engine, fake, repo):
    """Провести задачу по всей тестовой цепочке до `done`."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    turn(engine, fake, task_id, "three", 1, None)
    return task_id


def test_менеджер_просыпается_на_законченной_задаче(engine, fake, repo, manager):
    task_id = до_конца(engine, fake, repo)
    assert engine.db.task(task_id)["status"] == "done"
    engine.reconcile()
    assert [x["wake"] for x in асайды(engine)] == ["role-manager"]


# ── находки ревью: пропуск, курсор, бюджет, канал ────────────────────────
def test_чужой_пропуск_не_даёт_остановить_задачу(engine, fake, repo, tune):
    """Номер хода — маленькое целое; без пропуска его хватило бы, чтобы
    любая сессия застопорила любую задачу."""
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])

    отказ = engine.aside_note(run_id, "hold", "чужими руками", "", [], "угадал")
    assert "пропуск не подходит" in отказ
    assert engine.db.task(task_id)["status"] != WAITING
    assert engine.db.notes() == []


def test_повод_не_теряется_пока_роль_занята(engine, fake, repo, tune):
    """Роль одна на область: пока идёт её ход, повод ждёт за курсором.

    Раньше курсор переступал через отложенный повод, и роль не возвращалась
    к нему никогда.
    """
    task_id = start(engine, repo)
    engine.reconcile()
    assert len(асайды(engine)) == 1
    занятый = int(engine.db.aside_runs_open()[0]["id"])

    turn(engine, fake, task_id, "one", 1, None)      # конец захода — второй повод
    seq = engine.db.conn.execute(
        "SELECT seq FROM event WHERE kind = 'run_ended' ORDER BY seq DESC LIMIT 1"
    ).fetchone()["seq"]
    assert engine.db.cursor_of("tune", "") < seq, "курсор переступил через ждущий повод"

    # Роль освободилась — повод разобран, и ход по нему заведён.
    fake.finish_turn(асайды(engine)[0]["session_id"])
    engine.reconcile()
    engine.reconcile()
    assert engine.db.cursor_of("tune", "") >= seq
    assert [x["wake"] for x in асайды(engine)] == ["role-tune-start", "role-tune-review"]
    assert engine.db.aside_run(занятый)["ended_at"]


def test_бюджет_роли_в_деньгах_прекращает_ходы(engine, fake, repo, tune):
    (tune / "tune.yml").write_text(
        SPEC + "budget: {cost_usd: 1}\n", encoding="utf-8"
    )
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    with engine.db.tx():
        engine.db.aside_run_end(run_id, "done", 5.0)     # ход обошёлся дороже потолка

    turn(engine, fake, task_id, "one", 1, None)          # новый повод: конец захода
    engine.reconcile()
    assert len(асайды(engine)) == 1, "роль пошла на ход поверх выбранного бюджета"
    assert any(r["kind"] == "aside_budget" for r in engine.db.events(limit=30))


def test_наладчику_дают_живое_дерево_и_копию_под_коммиты(engine, fake, repo, tmp_path, monkeypatch):
    """Правит там, где прогон это увидит; коммитит там, где не заденет чужое."""
    from orch import asides as mod

    живое = tmp_path / "проект"
    живое.mkdir()
    import subprocess

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q", "."], cwd=живое, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=живое,
                   check=True, env=env)

    monkeypatch.setattr(mod, "user_dir", lambda: tmp_path / "нет")   # живую машину не читаем
    spec = mod.Aside(
        name="tune", scope="run", wakes=mod.load_by_name("tune").wakes,
        workspace=f"repo:{живое}", mirror=f"worktree:{живое}",
        rights=frozenset({"read", "patch", "pr"}), enabled=True, title="Наладчик",
    )
    monkeypatch.setattr(mod, "enabled", lambda: [spec])
    monkeypatch.setattr(engine, "aside_specs", lambda: [spec])
    with engine.db.tx():
        engine.db.cursor_set("tune", "", 0)

    start(engine, repo)
    текст = повод_текст(fake)
    assert f"Живое дерево, правки в нём действуют сразу: `{живое}`" in текст
    assert "Твоя копия под коммиты и ветку:" in текст
    assert "-orch/aside/tune" in текст, "копия под коммиты не отдельная"


def test_вес_находки_по_умолчанию_самый_тихий(engine, fake, repo, tune):
    """Без флага находка копится: в мессенджер уходит только названное."""
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])

    engine.aside_note(run_id, "непонятно-что", "Мелочь", "", [], пропуск(engine, run_id))
    assert engine.db.note(1)["severity"] == "log"
    assert engine.db.task(task_id)["status"] != WAITING


def test_умершая_сессия_роли_поднимается_ещё_раз(engine, fake, repo, tune):
    """Повод уже прошёл курсор и сам не вернётся: без повтора запись пропала бы."""
    start(engine, repo)
    engine.reconcile()
    первый = engine.db.aside_runs_open()[0]
    fake.drop(первый["session_id"])          # сессия исчезла, ход не сдан

    engine.reconcile()
    ходы = асайды(engine)
    assert len(ходы) == 2, "роль не подняли заново"
    assert ходы[0]["ended_at"] and not ходы[1]["ended_at"]
    assert ходы[1]["wake"] == ходы[0]["wake"]

    # Второй раз — не случайность: третий ход не заводим.
    fake.drop(ходы[1]["session_id"])
    engine.reconcile()
    assert len(асайды(engine)) == 2


def test_менеджеру_дают_копию_проекта_под_документы(engine, fake, repo, manager):
    """Правит документацию не в копии задачи, а в своей ветке проекта."""
    до_конца(engine, fake, repo)
    engine.reconcile()
    текст = fake.prompts[-1][1]
    assert "Твоя копия под коммиты и ветку:" in текст
    assert "-orch/aside/manager" in текст, "копия под документы не отдельная"


def test_вес_находки_по_умолчанию_самый_тихий(engine, fake, repo, tune):
    """Без флага находка копится: в мессенджер уходит только названное."""
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])

    engine.aside_note(run_id, "непонятно-что", "Мелочь", "", [], пропуск(engine, run_id))
    assert engine.db.note(1)["severity"] == "log"
    assert engine.db.task(task_id)["status"] != WAITING


def test_умершая_сессия_роли_поднимается_ещё_раз(engine, fake, repo, tune):
    """Повод уже прошёл курсор и сам не вернётся: без повтора запись пропала бы."""
    start(engine, repo)
    engine.reconcile()
    первый = engine.db.aside_runs_open()[0]
    fake.drop(первый["session_id"])          # сессия исчезла, ход не сдан

    engine.reconcile()
    ходы = асайды(engine)
    assert len(ходы) == 2, "роль не подняли заново"
    assert ходы[0]["ended_at"] and not ходы[1]["ended_at"]
    assert ходы[1]["wake"] == ходы[0]["wake"]

    # Второй раз — не случайность: третий ход не заводим.
    fake.drop(ходы[1]["session_id"])
    engine.reconcile()
    assert len(асайды(engine)) == 2




def test_сессия_роли_одна_на_задачу_и_живёт_до_владельца(engine, fake, repo, tune):
    """Отчёт роль оставляет в своей сессии, и закрывает её владелец сам."""
    task_id = start(engine, repo)
    engine.reconcile()
    первый = engine.db.aside_runs_open()[0]
    sid = первый["session_id"]

    engine.aside_done(int(первый["id"]), "clean", пропуск(engine, int(первый["id"])))
    engine.reconcile()
    assert sid not in fake.archived, "сессию с отчётом убрали без владельца"

    # Следующий повод приходит в ту же переписку, а не заводит вторую.
    # Ждём, пока переписка освободится: промпт в идущий ход оборвал бы его.
    fake.finish_turn(sid)
    turn(engine, fake, task_id, "one", 1, None)
    engine.reconcile()
    ходы = асайды(engine)
    assert len(ходы) >= 2
    assert {x["session_id"] for x in ходы} == {sid}, "роль завела вторую сессию"

def test_роль_помнит_разговор_лентой_находок(engine, fake, repo, tune):
    """Сессии не переживают ход: без ленты роль на третьем круге не помнит,
    с чего начали."""
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    engine.aside_note(run_id, "tell", "Первая находка", "…", [], пропуск(engine, run_id))
    engine.note_decision(1, "say", "Правь только промпт", who="панель")
    engine.aside_done(run_id, "done", пропуск(engine, run_id))

    fake.finish_turn(engine.db.aside_run(run_id)["session_id"])
    engine.reconcile()   # владелец ответил — роль поднимают заново
    engine.reconcile()
    текст = fake.prompts[-1][1]
    assert "Твоя находка, на которую ответил владелец" in текст
    assert "Правь только промпт" in текст
    assert "Первая находка" in текст


def test_ответ_доходит_и_после_конца_задачи(engine, fake, repo, tune):
    """Владелец мог написать, когда задача уже кончилась."""
    task_id = до_конца(engine, fake, repo)
    engine.reconcile()
    открытые = engine.db.aside_runs_open()
    run_id = int(открытые[0]["id"]) if открытые else None
    if run_id is None:                      # роль уже закрыла ход — заведём находку руками
        aside_id = engine.db.aside_open("tune", "run", task_id, task_id)
        with engine.db.tx():
            engine.db.note_add(aside_id, None, task_id, "tell", "После конца", "…", [])
        note_id = 1
    else:
        engine.aside_note(run_id, "tell", "После конца", "…", [], пропуск(engine, run_id))
        engine.aside_done(run_id, "done", пропуск(engine, run_id))
        note_id = 1

    assert engine.db.task(task_id)["status"] == "done"
    engine.note_decision(note_id, "say", "Всё равно поправь", who="панель")
    for _ in range(3):
        # Повод в общую переписку ждёт, пока та свободна: освобождаем все
        # сессии роли, а не только те, чей ход ещё открыт.
        for ход in engine.db.aside_runs_of(1):
            if ход["session_id"]:
                fake.finish_turn(ход["session_id"])
        engine.reconcile()
    assert any(
        "Всё равно поправь" in текст for _, текст in fake.prompts
    ), "слова владельца пропали после закрытия задачи"


def test_сводка_пишется_и_когда_задачу_принял_владелец(engine, fake, repo, tune):
    """Владелец принял PR — прогон кончился, и роль должна подвести итог."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "accept")
    engine.reconcile()
    turn(engine, fake, task_id, "three", 1, None)
    # Роль занята прошлым ходом — отпускаем её, иначе повод честно ждёт.
    for _ in range(4):
        for ход in engine.db.aside_runs_open():
            if ход["session_id"]:
                fake.finish_turn(ход["session_id"])
        engine.reconcile()

    assert engine.db.task(task_id)["status"] == "done"
    assert any(x["wake"] == "role-tune-summary" for x in асайды(engine)), "сводки нет"


def test_правила_шлются_один_раз_на_переписку(engine, fake, repo, tune):
    """Сессия одна на задачу: повторять общие правила каждый ход — платить
    за них заново."""
    def промпты_роли():
        sid = асайды(engine)[0]["session_id"]
        return [текст for кому, текст in fake.prompts if кому == sid]

    task_id = start(engine, repo)
    engine.reconcile()
    первый = промпты_роли()[0]
    assert "Ты побочная роль" in первый, "в первый раз правила нужны"
    assert "Наладчик: проверка входа" in первый

    # Тот же повод второй раз: правила и текст роли уже в переписке.
    for ход in engine.db.aside_runs_open():
        fake.finish_turn(ход["session_id"])
    turn(engine, fake, task_id, "one", 1, None)
    engine.reconcile()
    engine.reconcile()
    второй = промпты_роли()[-1]
    assert "Ты побочная роль" not in второй, "общие правила ушли дважды"
    assert "Наладчик: разбор хода" in второй, "новый повод — новые правила"

    # Тот же повод второй раз: правила уже в переписке, идёт короткая шапка.
    for ход in engine.db.aside_runs_open():
        fake.finish_turn(ход["session_id"])
    engine.reconcile()
    engine.reconcile()
    третий = промпты_роли()[-1]
    assert "Наладчик: проверка входа" not in третий, "текст роли ушёл дважды"
    assert "уже читала выше в этой переписке" in третий
    assert "# Что случилось" in третий
    assert len(третий) < len(первый) / 3


def test_на_шаг_идёт_короткое_сообщение(engine, fake, repo, tune):
    """Справочное роль читает один раз; на повод — что случилось и действуй."""
    def промпты_роли():
        sid = асайды(engine)[0]["session_id"]
        return [текст for кому, текст in fake.prompts if кому == sid]

    task_id = start(engine, repo)
    engine.reconcile()
    первый = промпты_роли()[0]
    assert "Как смотреть чужой ход" in первый, "справка нужна в первом сообщении"
    assert "orch digest" in первый

    for _ in range(3):
        for ход in engine.db.aside_runs_open():
            fake.finish_turn(ход["session_id"])
        engine.reconcile()
    turn(engine, fake, task_id, "one", 1, None)
    for _ in range(3):
        for ход in engine.db.aside_runs_open():
            fake.finish_turn(ход["session_id"])
        engine.reconcile()

    последний = промпты_роли()[-1]
    assert "Как смотреть чужой ход" not in последний, "справка ушла дважды"
    assert "Правила ты знаешь — действуй" in последний
    assert "Твой ход `A" in последний, "номер и пропуск нужны каждый раз"
    assert "Коротко, чтобы не сбиться" in последний, "свод правил нужен каждый раз"
    assert len(последний) < 1200, f"сообщение на повод раздуто: {len(последний)}"



СВОЯ_СЕССИЯ = SPEC.replace(
    """  - on: [run_ended]
    prompt: role-tune-review""",
    """  - on: [run_ended]
    prompt: role-tune-review
    session: fresh""",
)


def test_разбор_идёт_в_своей_сессии_и_не_трогает_переписку(
    engine, fake, repo, tune, monkeypatch
):
    """`session: fresh` разводит разбор и разговор.

    Промпт в занятую сессию AoE доставляется как `steer` и обрывает то, что в
    ней идёт: движок бил бы по разговору владельца с ролью, а реплика
    владельца — по разбору (T26).
    """
    (tune / "tune.yml").write_text(СВОЯ_СЕССИЯ, encoding="utf-8")
    task_id = start(engine, repo)
    engine.reconcile()
    общая = engine.db.aside_runs_open()[0]["session_id"]
    engine.aside_done(
        int(engine.db.aside_runs_open()[0]["id"]),
        "clean",
        пропуск(engine, int(engine.db.aside_runs_open()[0]["id"])),
    )
    engine.reconcile()

    # Разговор владельца с ролью идёт прямо сейчас — сессия занята.
    fake.rows[общая]["status"] = "Running"
    turn(engine, fake, task_id, "one", 1, None)
    engine.reconcile()

    разбор = [x for x in асайды(engine) if x["wake"] == "role-tune-review"]
    assert разбор, "повод разбора не завёл ход"
    assert разбор[0]["session_id"] != общая, "разбор влез в переписку владельца"
    # Общая переписка роли осталась той же: сессия разбора живёт один повод.
    aside = engine.db.conn.execute("SELECT session_id FROM aside").fetchone()
    assert aside["session_id"] == общая


def test_повод_в_переписку_ждёт_пока_она_освободится(engine, fake, repo, tune):
    """Пока в общей сессии идёт ход, повод не отправляется, но и не теряется."""
    task_id = start(engine, repo)
    engine.reconcile()
    первый = engine.db.aside_runs_open()[0]
    engine.aside_done(int(первый["id"]), "clean", пропуск(engine, int(первый["id"])))
    engine.reconcile()

    fake.rows[первый["session_id"]]["status"] = "Running"
    turn(engine, fake, task_id, "one", 1, None)
    engine.reconcile()
    assert len(асайды(engine)) == 1, "повод влез в занятую переписку"

    fake.finish_turn(первый["session_id"])
    engine.reconcile()
    assert len(асайды(engine)) == 2, "повод потерялся вместе с занятой сессией"


def test_снятая_из_бэклога_задача_никого_не_будит(engine, fake, repo, tune):
    """«Удалить» на карточке бэклога — не конец прогона.

    Задача ни разу не запускалась: подводить итог нечему, а сводка и записка
    стоили бы двух сессий на пустом месте (T25).
    """
    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="Долг по PR", backlog=True
    )
    engine.reconcile()
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "close")
    engine.reconcile()
    engine.reconcile()
    assert engine.db.task(task_id)["status"] == "closed"
    assert not [x for x in асайды(engine) if x["wake"] == "role-tune-summary"]


def test_вариант_вернуть_начисто_исполняется_движком(engine, fake, repo, tune):
    """Словарь вариантов и кнопки владельца — одно и то же действие.

    Вариант, который движок не умеет исполнить, — это находка, повисшая в
    воздухе: владелец нажал, а ничего не случилось.
    """
    from tests.test_engine import ws_of

    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    assert engine.db.task(task_id)["wait_reason"] == "gate"

    aside_id = engine.db.aside_open("tune", "run", task_id, task_id)
    with engine.db.tx():
        engine.db.note_add(
            aside_id, None, task_id, "hold", "План опирался на старое ревью", "…",
            [{"verb": "back_clean", "target": "one", "label": "вернуть на one начисто"}],
        )
    ответ = engine.note_decision(1, "back_clean", "one", who="panel")

    assert "начисто" in ответ
    assert engine.db.task(task_id)["step"] == "one"
    assert not (ws_of(engine, task_id).artifacts / "two.md").exists()
    assert all(r["void_at"] for r in engine.db.runs_of_step(task_id, "two"))
