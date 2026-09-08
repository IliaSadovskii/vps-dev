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
    # Вопросы ходят парой с воротами: на PR они остаются вместе с ним.
    assert [s for s, v in sheet.items() if v["ask"]] == ["pr"]

    # `hands-off` больше нет: имя обещало автономию, а снимало одни ворота
    # плана — на нём владелец и обжёгся (прогон T24).
    sheet = c.sheet_with_preset("default")
    assert sheet["review-fixes"]["after"] == ["ready"] and sheet["solution"]["after"] is True


def test_пресета_нет():
    c = load(chains_dir() / "deep.yml")
    with pytest.raises(ChainError) as exc:
        c.sheet_with_preset("нету")
    assert "нет пресета" in str(exc.value)


def test_три_формы_ворот():
    """`false` — никогда, `true` — после любого хода, список — после исхода."""
    from orch.chain import gates_on

    assert not gates_on(False, "ok")
    assert gates_on(True, None)
    assert gates_on(["ready"], "ready")
    assert not gates_on(["ready"], "review")


def test_ревью_возвращает_автору_и_автор_прыгает_дальше():
    """Граф, а не список: у автора два выхода, у ревью один — назад."""
    from orch.chain import chains_dir, load

    deep = load(chains_dir() / "deep.yml")
    plan = deep.step("plan")
    assert plan.next == {"review": "plan-review", "ready": "implementation"}
    assert plan.gates_on("ready") and not plan.gates_on("review")
    assert deep.step("plan-review").single_next == "plan"


def test_пресеты_deep_покрывают_обе_стороны_автономии():
    """Пресет меняет и ворота, и вопросы: «не трогай меня» — это и то, и другое."""
    from orch.chain import load_by_name

    chain = load_by_name("deep")
    # Пресеты различаются одним: сколько раз останавливают владельца.
    # Частные наборы («план со мной», «тихо») собираются руками — держать
    # под них имена значит заставлять выбирать из похожего.
    assert set(chain.presets) == {"default", "auto", "step-by-step"}
    # `default` — именованное «как записано в шагах»: пустой набор ручек,
    # чтобы он не мог разойтись с самой цепочкой.
    assert chain.sheet_with_preset("default") == chain.default_sheet()
    assert all(chain.preset_notes.get(name) for name in chain.presets), "пресет без пояснения"

    # Ворота и вопросы ходят парой: шаг либо с обоими, либо без обоих. У
    # самих шагов причины свои (вопрос на Реализации — признак плохого
    # плана), поэтому правило проверяется на пресетах, а не на цепочке.
    for name in set(chain.presets) - {"default"}:
        sheet = chain.sheet_with_preset(name)
        for step, knobs in sheet.items():
            assert bool(knobs["after"]) == bool(knobs["ask"]), f"{name}: {step} врозь"

    до_pr = chain.sheet_with_preset("auto")
    assert [s for s, v in до_pr.items() if v["after"]] == ["pr"]

    под_присмотром = chain.sheet_with_preset("step-by-step")
    assert all(v["after"] and v["ask"] for v in под_присмотром.values())

    под_присмотром = chain.sheet_with_preset("step-by-step")
    assert all(v["after"] and v["ask"] for v in под_присмотром.values())


def test_пресет_можно_писать_плоско_и_с_пояснением():
    """Старый формат (плоский словарь) читается как прежде."""
    from orch.chain import parse

    chain = parse(
        "name: t\n"
        "presets:\n"
        "  старый: { '*.ask': false }\n"
        "  новый: { when: «зачем», set: { '*.after': false } }\n"
        "steps:\n"
        "  - id: one\n    run: {agent: claude, model: haiku}\n    next: done\n"
    )
    assert chain.sheet_with_preset("старый")["one"]["ask"] is False
    assert chain.sheet_with_preset("новый")["one"]["after"] is False
    assert chain.preset_notes["новый"] == "«зачем»"
