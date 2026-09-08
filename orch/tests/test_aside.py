"""Побочные роли: описание, поводы, ходы, находки (`ASIDE-PLAN.md`)."""

from __future__ import annotations

import json

import pytest

from orch import asides
from orch.asides import AsideError, parse
from orch.db import WAITING

from tests.test_engine import monkey_chain, start, turn


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
    assert spec.kinds() == ("run_started", "run_ended")
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
    assert sid in fake.archived


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


def test_роль_без_права_останавливать_только_сообщает(engine, fake, repo, tune):
    (tune / "tune.yml").write_text(SPEC.replace("[read, hold]", "[read]"), encoding="utf-8")
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = engine.db.aside_runs_open()[0]["id"]
    engine.aside_note(int(run_id), "hold", "Что-то не то", "", [], пропуск(engine, run_id))
    assert engine.db.note(1)["severity"] == "fyi"
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
        memory=spec.memory, rights=spec.rights, includes=spec.includes,
        chains=(), requires=(), budget={}, enabled=True, title=spec.title,
    )
    monkeypatch.setattr(mod, "enabled", lambda: [объект])
    monkeypatch.setattr(engine, "aside_specs", lambda: [объект])

    with engine.db.tx():                       # роль уже была включена до задачи
        engine.db.cursor_set("tune", "", 0)
    task_id = start(engine, repo)
    текст = fake.prompts[-1][1]
    assert "Ты побочная роль" in текст, "общие правила не приклеились"
    assert "Наладчик: проверка входа" in текст, "промпт повода не приклеился"
    assert "Твой ход: `A1`" in текст and task_id in текст
    assert "Права, выданные тебе: hold, patch, pr, read" in текст


# ── копилка (Менеджер проекта) ───────────────────────────────────────────
MANAGER = """
name: manager
title: Менеджер проекта
scope: project
enabled: true
workspace: task
memory: project
rights: [read, memory]
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


def test_менеджеру_сказали_где_его_копилка(engine, fake, repo, manager, tmp_path):
    до_конца(engine, fake, repo)
    engine.reconcile()
    текст = fake.prompts[-1][1]
    assert "Твоя копилка:" in текст and "manager-" in текст


def test_копилка_проекта_дописывается(engine, fake, repo, manager, tmp_path):
    до_конца(engine, fake, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    assert "записано" in engine.aside_memory(
        run_id, "Отвергли вариант с очередью: нет воркера.", пропуск(engine, run_id)
    )
    файлы = list((tmp_path / "memory").glob("manager-*.md"))
    assert файлы and "нет воркера" in файлы[0].read_text(encoding="utf-8")


def test_без_права_копилки_роль_не_пишет(engine, fake, repo, manager):
    (manager / "manager.yml").write_text(
        MANAGER.replace("[read, memory]", "[read]"), encoding="utf-8"
    )
    до_конца(engine, fake, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    assert "не выдано право" in engine.aside_memory(run_id, "…", пропуск(engine, run_id))


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


def test_без_канала_роль_не_останавливает_прогон(engine, fake, repo, tune, monkeypatch):
    """`requires: notify` без бота — роль говорит, но прогон не стопорит."""
    (tune / "tune.yml").write_text(
        SPEC.replace("rights: [read, hold]", "rights: [read, hold]\nrequires: [notify]"),
        encoding="utf-8",
    )
    task_id = start(engine, repo)
    engine.reconcile()
    run_id = int(engine.db.aside_runs_open()[0]["id"])
    monkeypatch.setattr(type(engine.notify()), "live", property(lambda self: False))

    engine.aside_note(run_id, "hold", "Едет не туда", "", [], пропуск(engine, run_id))
    assert engine.db.note(1)["severity"] == "fyi"
    assert engine.db.task(task_id)["status"] != WAITING


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
    текст = fake.prompts[-1][1]
    assert f"Живое дерево, правки в нём действуют сразу: `{живое}`" in текст
    assert "Твоя копия под коммиты и ветку:" in текст
    assert "-orch/aside/tune" in текст, "копия под коммиты не отдельная"
