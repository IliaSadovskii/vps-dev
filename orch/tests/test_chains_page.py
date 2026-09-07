"""Страница настройки цепочек (`ansible/roles/orch/files/orch-chains`).

Скрипт лежит в роли Ansible, а не в пакете: на машине его запускает
systemd из венва orch. Тест грузит его по пути — иначе логика сохранения
и сброса осталась бы без проверки, а ошибка в ней стоит цепочки.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from orch import chain as chain_mod
from orch.chain import ChainError

SCRIPT = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "orch" / "files" / "orch-chains"


@pytest.fixture
def page(tmp_path, monkeypatch):
    """Страница с пользовательским каталогом во временной папке."""
    monkeypatch.setattr(chain_mod, "STATE_DIR", tmp_path)
    spec = importlib.util.spec_from_loader(
        "orch_chains_page", importlib.machinery.SourceFileLoader("orch_chains_page", str(SCRIPT))
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["orch_chains_page"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("orch_chains_page", None)


def edits_of(page, name):
    """Шаги цепочки в том виде, в каком их шлёт страница."""
    view = page.chain_view(name)
    assert not view.get("error"), view.get("error")
    return view["steps"]


def test_витрина_показывает_заводские_цепочки(page):
    view = page.picture()
    names = [c["name"] for c in view["chains"]]
    assert {"deep", "blueprint", "conventions"} <= set(names)
    deep = next(c for c in view["chains"] if c["name"] == "deep")
    assert deep["custom"] is False
    assert deep["steps"][0]["id"] == "scoping"
    assert deep["description"].startswith("Deep")
    assert "opus[1m]" in view["options"]["models"]["claude"]


def test_сохранение_кладёт_копию_рядом_с_базой_и_не_трогает_заводскую(page, tmp_path):
    factory = (chain_mod.chains_dir() / "deep.yml").read_text(encoding="utf-8")
    edits = edits_of(page, "deep")
    edits[0]["model"] = "sonnet"
    edits[0]["max_runs"] = 2
    page.save("deep", edits)

    user = tmp_path / "chains" / "deep.yml"
    assert user.exists()
    assert (chain_mod.chains_dir() / "deep.yml").read_text(encoding="utf-8") == factory
    assert chain_mod.is_custom("deep")
    # Правленая версия — та, по которой поедет новая задача.
    assert chain_mod.path_of("deep") == user
    step = chain_mod.load_by_name("deep").step("scoping")
    assert step.model == "sonnet" and step.max_runs == 2


def test_порядок_шагов_меняется_и_меняет_первый_шаг(page):
    edits = edits_of(page, "deep")
    edits[0], edits[1] = edits[1], edits[0]
    page.save("deep", edits)
    assert chain_mod.load_by_name("deep").first.id == "solution"


def test_ворота_убирают_и_кнопки_возврата(page):
    """Линтер запрещает `moves` без ворот — значит убираем их вместе."""
    edits = edits_of(page, "deep")
    gated = next(e for e in edits if e["moves"])
    gated["after"] = False
    page.save("deep", edits)
    step = chain_mod.load_by_name("deep").step(gated["id"])
    assert step.human_after is False and step.human_moves == []


def test_ворота_на_исходе(page):
    """Ворота на одном исходе из нескольких: развилка едет дальше сама."""
    edits = edits_of(page, "deep")
    forked = next(e for e in edits if len(e["outcomes"]) > 1)
    first, second = forked["outcomes"][0], forked["outcomes"][1]
    forked["after"] = [first]
    page.save("deep", edits)
    step = chain_mod.load_by_name("deep").step(forked["id"])
    assert step.gates_on(first) and not step.gates_on(second)


def test_битую_цепочку_не_сохраняем(page, tmp_path):
    edits = edits_of(page, "deep")
    edits[0]["context"] = "телепатия"
    with pytest.raises(ChainError):
        page.save("deep", edits)
    assert not (tmp_path / "chains" / "deep.yml").exists()


def test_ворота_на_исходе_которого_нет(page):
    edits = edits_of(page, "deep")
    edits[0]["after"] = ["нет-такого"]
    with pytest.raises(ChainError):
        page.save("deep", edits)


def test_список_шагов_разошёлся_с_заводским(page):
    """Репозиторий обновился, а страница открыта со старым списком."""
    edits = edits_of(page, "deep")[:3]
    with pytest.raises(ChainError) as exc:
        page.save("deep", edits)
    assert "перезагрузите страницу" in str(exc.value)


def test_сброс_удаляет_копию(page, tmp_path):
    page.save("deep", edits_of(page, "deep"))
    assert chain_mod.is_custom("deep")
    page.reset("deep")
    assert not chain_mod.is_custom("deep")
    assert chain_mod.path_of("deep") == chain_mod.chains_dir() / "deep.yml"
    page.reset("deep")  # второй раз — молча, кнопку могли нажать дважды


def test_сохранение_собирается_из_заводской_а_не_из_прошлой_копии(page):
    """Правки не накапливаются: страница всегда кладёт заводскую плюс поля."""
    factory = chain_mod.load(chain_mod.chains_dir() / "deep.yml")
    first = factory.first.id

    edits = edits_of(page, "deep")
    edits[0]["max_runs"] = 7
    page.save("deep", edits)
    again = edits_of(page, "deep")
    again[0]["max_runs"] = 5
    again[0]["context"] = "fresh"
    page.save("deep", again)

    saved = chain_mod.load_by_name("deep")
    assert saved.step(first).max_runs == 5      # прошлая правка не осталась
    # Всё, чего страница не правит, осталось из репозитория.
    for step in factory.steps:
        mine = saved.step(step.id)
        assert mine.artifact == step.artifact and mine.next == step.next
        assert mine.reads == step.reads and mine.prompt_file == step.prompt_file
