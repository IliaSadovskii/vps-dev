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


ШАГИ_КОРОТКИХ = {
    "quick": ["implementation", "code-review", "review-fixes", "pr"],
    "standard": [
        "scoping",
        "plan",
        "plan-review",
        "implementation",
        "code-review",
        "review-fixes",
        "pr",
    ],
}

КОРОТКИЕ = tuple(ШАГИ_КОРОТКИХ)
# Пресеты — общий инвариант всех дорожек разработки, а не свойство коротких.
ДОРОЖКИ_РАЗРАБОТКИ = ("deep", *КОРОТКИЕ)


@pytest.mark.parametrize("имя, шаги", sorted(ШАГИ_КОРОТКИХ.items()))
def test_короткие_цепочки_состоят_из_обещанных_шагов(имя, шаги):
    """Дорожка короче deep, но развилка ревью кода в ней та же самая.

    Достижимость `done` из каждого шага здесь не проверяется руками: её
    проверяет сам линтер при `load` (`orch/src/orch/chain.py:264-268`), и
    написанная второй раз, эта проверка была бы зелёной ещё до появления
    цепочек.
    """
    c = load(chains_dir() / f"{имя}.yml")
    assert [s.id for s in c.steps] == шаги
    # Эталон развилки читаем из deep, а не пишем литералом: иначе короткая
    # дорожка тихо сохранит маршрут, который у deep уже снят (так и вышло с
    # исходом `tests`, снятым коммитом `ba7a919`).
    assert c.step("code-review").next == load(
        chains_dir() / "deep.yml"
    ).step("code-review").next
    assert c.step("review-fixes").next == {"review": "code-review", "ready": "pr"}
    if имя == "standard":
        assert c.step("plan").next == {"review": "plan-review", "ready": "implementation"}
        # Назад из плана — только в разведку: шага `solution` в этой цепочке нет.
        assert c.step("plan").human_moves == ["plan-review", "scoping"]


def test_ворота_коротких_цепочек_стоят_где_обещано():
    """Quick останавливает владельца один раз, standard — три."""
    quick = load(chains_dir() / "quick.yml").default_sheet()
    assert [s for s, v in quick.items() if v["after"]] == ["pr"]
    assert quick["pr"]["after"] is True

    standard = load(chains_dir() / "standard.yml").default_sheet()
    assert standard["plan"]["after"] == ["ready"]
    assert standard["review-fixes"]["after"] == ["ready"]
    # У `pr` один безымянный переход, и `after: [ready]` линтер отвергнет
    # (`orch/src/orch/chain.py:256-262`); на таком шаге `true` — то же самое.
    assert standard["pr"]["after"] is True
    assert [s for s, v in standard.items() if not v["after"]] == [
        "scoping",
        "plan-review",
        "implementation",
        "code-review",
    ]


@pytest.mark.parametrize("имя", ДОРОЖКИ_РАЗРАБОТКИ)
def test_пресеты_покрывают_обе_стороны_автономии(имя):
    """Пресет меняет и ворота, и вопросы: «не трогай меня» — это и то, и другое.

    Инвариант один на все дорожки разработки, поэтому и тест один: короткие
    цепочки отвечают на «где владелец участвует» теми же тремя ответами, что
    и deep.
    """
    chain = load(chains_dir() / f"{имя}.yml")
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


def test_цепочки_читают_только_то_что_сами_производят():
    """`reads` без имени, которого цепочка не пишет: обещание файла, которого не будет.

    Исключение одно — `remarks.md`: заметки владельца с ворот пишутся после
    `orch done`, и в `artifact` его нет намеренно (`orch/chains/deep.yml:167-169`).
    """
    for path in sorted(chains_dir().glob("*.yml")):
        c = load(path)
        производит = {a for s in c.steps for a in s.artifact} | {"remarks.md"}
        лишние = sorted(
            f"{s.id}: {name}" for s in c.steps for name in s.reads if name not in производит
        )
        assert not лишние, f"{c.name} читает то, чего не производит: {лишние}"


@pytest.mark.parametrize("имя", КОРОТКИЕ)
def test_у_коротких_цепочек_есть_описание_для_мастера(имя):
    """Мастер различает цепочки только по шапке файла — пустая шапка его слепит."""
    from orch.chain import catalog

    записи = {c["name"]: c for c in catalog()}
    assert имя in записи, f"цепочки {имя} нет в каталоге: {sorted(записи)}"
    запись = записи[имя]
    assert "error" not in запись, запись.get("error")
    assert запись["description"].strip()


@pytest.mark.parametrize("имя", КОРОТКИЕ)
def test_владение_тестами_подключено_тем_же_шагам_что_в_deep(имя):
    """Короткая цепочка экономит на замысле, а не на проверке.

    Скрипт владения тестами — единственное, что ловит правку теста чужим
    шагом, и в `quick` до ворот PR владелец не смотрит ничего.
    """
    def с_владением(имя_цепочки):
        return {
            s.id
            for s in load(chains_dir() / f"{имя_цепочки}.yml").steps
            if "common-test-ownership" in s.includes
        }

    эталон = с_владением("deep")
    assert эталон, "в deep владение тестами не подключено ни одному шагу"
    assert с_владением(имя) == эталон


def test_у_каждой_цепочки_есть_файлы_ролей_и_общих_правил():
    """Роль без файла получает вместо задания строку «файл не найден»
    (`promptbuild._role`), ход идёт впустую, и линтер этого не видит."""
    from orch.chain import missing_files

    for path in sorted(chains_dir().glob("*.yml")):
        assert missing_files(load(path)) == [], path.name


def test_проверка_файлов_видит_пропажу():
    from orch.chain import missing_files

    chain = parse(
        "name: t\nincludes: [common-nope]\nsteps:\n  - id: a\n"
        "    includes: [common-tоже-нет]\n    run: {agent: claude, model: s}\n    next: done\n"
    )
    gaps = missing_files(chain)
    assert any("common-nope" in g for g in gaps)
    assert any("role-a" in g for g in gaps)
    assert any("common-tоже-нет" in g for g in gaps)
