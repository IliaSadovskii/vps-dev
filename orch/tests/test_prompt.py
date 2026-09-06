"""Сборка промпта: снимки по сценариям `PLAN.md` §11."""

from __future__ import annotations

from pathlib import Path

import pytest

from orch.chain import parse as parse_chain
from orch.promptbuild import Context, build, came_from_phrase

CHAIN = """
name: t
steps:
  - id: one
    run: {agent: claude, model: haiku}
    artifact: [one.md]
    next: two
  - id: two
    run: {agent: claude, model: haiku}
    prompt: {reads: [one.md], instructions: "Только на русском."}
    artifact: [two.md]
    next: {ok: done, back: one}
    human: {after: [ok], ask: false, moves: [one]}
    limits: {max_runs: 2}
"""


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    chain = parse_chain(CHAIN)
    task_dir = tmp_path / ".orch" / "T1"
    (task_dir / "artifacts").mkdir(parents=True)
    return Context(
        chain=chain,
        step=chain.step("two"),
        task_id="T1",
        task_text="Добавить команду удаления заметки.",
        task_dir=task_dir,
        root=tmp_path,
        run_n=1,
        path_steps=["one", "two"],
    )


def test_первый_заход(ctx):
    text = build(ctx)
    assert "## Задача" in text
    assert "Добавить команду удаления заметки." in text
    assert "one → two → [ты: two, заход 1]" in text
    assert "Только на русском." in text
    assert "`ok`, `back`" in text
    assert "два раза" not in text


def test_отсутствующий_файл_из_reads_назван(ctx):
    text = build(ctx)
    assert "Этих файлов нет" in text and "one.md" in text


def test_чужой_артефакт_даёт_только_итог(ctx):
    (ctx.task_dir / "artifacts" / "one.md").write_text(
        "## Итог\nодна строка итога\n\n## Подробности\nсекретная простыня\n",
        encoding="utf-8",
    )
    text = build(ctx)
    assert "одна строка итога" in text
    assert "секретная простыня" not in text


def test_второй_заход_после_возврата_владельца(ctx):
    ctx.run_n = 2
    ctx.came_from = came_from_phrase("human")
    ctx.comments = ["Верни одну строку, не три."]
    text = build(ctx)
    assert "вернул владелец с комментарием" in text
    assert "> Верни одну строку, не три." in text
    assert "перепиши его, новый не заводи" in text
    assert "последний допустимый заход" in text


def test_второй_заход_после_возврата_роли(ctx):
    ctx.run_n = 2
    ctx.came_from = came_from_phrase("role", "one")
    text = build(ctx)
    assert "вернула роль one" in text


def test_ещё_заход_кнопкой(ctx):
    ctx.run_n = 2
    ctx.came_from = came_from_phrase("again")
    text = build(ctx)
    assert "ещё заход" in text


def test_вопросы_выключены(ctx):
    ctx.ask_allowed = False
    assert "задавать нельзя" in build(ctx)
    ctx.ask_allowed = True
    assert "задавать можно" in build(ctx)


def test_правка_владельцем_названа(ctx):
    ctx.owner_edited = ["one.md"]
    assert "`one.md` правил владелец после сдачи" in build(ctx)


def test_шаг_с_одним_переходом_не_требует_исхода(ctx):
    ctx.step = ctx.chain.step("one")
    text = build(ctx)
    assert "`orch done` (исход у шага один)" in text


def test_тяжёлый_промпт_вклеивает_пути_без_содержания(ctx):
    (ctx.task_dir / "artifacts" / "one.md").write_text(
        "## Итог\n" + ("длинная строка итога. " * 40_000), encoding="utf-8"
    )
    text = build(ctx)
    assert ctx.oversized is True
    assert "содержание файлов не вклеено" in text
    assert "длинная строка итога" not in text


def test_сборка_детерминирована(ctx):
    assert build(ctx) == build(ctx)


def test_первый_заход_не_врёт_про_продолжение(engine, fake, repo):
    """Кнопку «ещё заход» жмут и на задаче, которая шаг ещё не начинала."""
    from test_engine import monkey_chain, session_of

    monkey_chain(engine)
    task_id = engine.create_task(chain_name="t", project_path=str(repo), text="текст")
    engine.reconcile()
    task = engine.db.task(task_id)
    # Останавливаем до первого хода и жмём «ещё заход», как владелец руками.
    engine.stop(task_id, "no_worktree")
    task = engine.db.task(task_id)
    engine.button(task_id, task["revision"], "again")
    engine.reconcile()
    ws = engine.workspace(engine.db.task(task_id))
    text = (ws.path / "prompts" / "one-1.md").read_text(encoding="utf-8")
    assert "продолжи с места остановки" not in text
    assert "заход 1" in text


def test_общий_файл_шага_не_едет_ко_всем(engine, fake, repo):
    """Правило для двух ролей из восьми — это `includes` шага, не цепочки."""
    from orch.chain import parse
    from orch import promptbuild

    chain = parse(
        "name: c\n"
        "includes: [common-protocol]\n"
        "steps:\n"
        "  - id: one\n"
        "    includes: [common-test-ownership]\n"
        "    run: { agent: claude, model: haiku }\n"
        "    next: done\n"
        "  - id: two\n"
        "    run: { agent: claude, model: haiku }\n"
        "    next: done\n"
    )
    def text_of(step_id):
        step = chain.step(step_id)
        ctx = promptbuild.Context(
            chain=chain, step=step, task_id="T1", task_text="т",
            task_dir=repo / ".orch" / "T1", root=repo, run_n=1,
        )
        return promptbuild.build(ctx)

    assert "Кто трогал тесты" in text_of("one")
    assert "Кто трогал тесты" not in text_of("two")


def test_правило_ворот_только_шагу_с_воротами(engine, fake, repo):
    """Команда `orch gate` без ворот — способ, которым роль не вправе пользоваться."""
    from test_engine import monkey_chain

    monkey_chain(engine)
    task_id = engine.create_task(
        chain_name="t", project_path=str(repo), text="текст",
        sheet_edits={"one.after": True},
    )
    engine.reconcile()
    ws = engine.workspace(engine.db.task(task_id))
    with_gate = (ws.path / "prompts" / "one-1.md").read_text(encoding="utf-8")
    assert "orch gate accept" in with_gate

    другая = engine.create_task(
        chain_name="t", project_path=str(repo), text="вторая",
        sheet_edits={"one.after": False},
    )
    engine.reconcile()
    ws2 = engine.workspace(engine.db.task(другая))
    без = (ws2.path / "prompts" / "one-1.md").read_text(encoding="utf-8")
    assert "orch gate accept" not in без


def test_пустая_рубрика_файлов_не_выводится(engine, fake, repo):
    from orch.chain import parse
    from orch import promptbuild

    chain = parse(
        "name: c\nsteps:\n  - id: one\n    run: { agent: claude, model: haiku }\n"
        "    next: done\n"
    )
    ctx = promptbuild.Context(
        chain=chain, step=chain.step("one"), task_id="T1", task_text="т",
        task_dir=repo / ".orch" / "T1", root=repo, run_n=1,
    )
    assert "## Файлы" not in promptbuild.build(ctx)
