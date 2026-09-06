"""Линтер цепочек: все файлы `chains/` и по отрицательному случаю на ошибку."""

from __future__ import annotations

import pytest

from orch.chain import ChainError, chains_dir, load, parse

GOOD = """
name: t
steps:
  - id: a
    run: {agent: claude, model: sonnet}
    next: done
"""


def test_все_цепочки_репозитория_проходят_линтер():
    files = sorted(chains_dir().glob("*.yml"))
    assert files, "в chains/ нет ни одной цепочки"
    for path in files:
        load(path)


def test_минимальная_цепочка():
    c = parse(GOOD)
    assert c.step("a").single_next == "done"
    assert c.step("a").max_runs == 3
    assert c.step("a").context == "fresh"


@pytest.mark.parametrize(
    "yaml_text, ожидаемое",
    [
        ("name: t\nsteps: []\n", "непустым списком"),
        ("name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n", "next"),
        ("name: t\nsteps:\n  - id: a\n    run: {model: s}\n    next: done\n", "run.agent"),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n    next: b\n",
            "нет шага 'b'",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n    next: a\n",
            "не добраться до конца",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s, mode: plan}\n"
            "    next: done\n",
            "только full",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: gpt, model: s}\n    next: done\n",
            "агент",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n    next: done\n"
            "    limits: {max_runs: 0}\n",
            "max_runs",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n    next: done\n"
            "    human: {moves: [a]}\n",
            "moves без human.after",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n"
            "    next: {ok: done}\n    human: {after: [nope], moves: [a]}\n",
            "которых нет в next",
        ),
        (
            "name: t\nsteps:\n  - id: a\n    run: {agent: claude, model: s}\n    next: done\n"
            "  - id: a\n    run: {agent: claude, model: s}\n    next: done\n",
            "одинаковым id",
        ),
        (
            "name: t\nsteps:\n  - id: done\n    run: {agent: claude, model: s}\n    next: done\n",
            "конец цепочки",
        ),
        (
            "name: t\npresets: {p: {nope.after: false}}\nsteps:\n  - id: a\n"
            "    run: {agent: claude, model: s}\n    next: done\n",
            "нет шага 'nope'",
        ),
        (
            "name: t\npresets: {p: {a.what: false}}\nsteps:\n  - id: a\n"
            "    run: {agent: claude, model: s}\n    next: done\n",
            "ожидались .after или .ask",
        ),
    ],
)
def test_линтер_ловит_ошибку(yaml_text, ожидаемое):
    with pytest.raises(ChainError) as exc:
        parse(yaml_text)
    assert ожидаемое in str(exc.value)


def test_пресеты_deep_накладываются():
    c = load(chains_dir() / "deep.yml")
    sheet = c.sheet_with_preset("auto")
    assert sheet["pr"]["after"] is True
    assert sheet["plan-review"]["after"] is False
    assert all(v["ask"] is False for v in sheet.values())

    sheet = c.sheet_with_preset("hands-off")
    assert sheet["plan-review"]["after"] is False
    assert sheet["pr"]["after"] is True  # как записано в шаге


def test_пресета_нет():
    c = load(chains_dir() / "deep.yml")
    with pytest.raises(ChainError) as exc:
        c.sheet_with_preset("нету")
    assert "нет пресета" in str(exc.value)
