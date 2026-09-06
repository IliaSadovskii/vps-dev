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
