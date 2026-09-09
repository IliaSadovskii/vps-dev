"""Вкладка «Агенты» на странице настройки (`ASIDE-PLAN.md` §12)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from orch import asides as aside_mod

SCRIPT = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "orch" / "files" / "orch-chains"


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(aside_mod, "STATE_DIR", tmp_path)
    spec = importlib.util.spec_from_loader(
        "orch_page", importlib.machinery.SourceFileLoader("orch_page", str(SCRIPT))
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["orch_page"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("orch_page", None)


def test_витрина_показывает_заводского_наладчика(page):
    view = page.asides_picture()
    tune = next(a for a in view["asides"] if a["name"] == "tune")
    assert tune["enabled"] is False and tune["custom"] is False
    assert "hold" in tune["rights"] and tune["scope"] == "run"
    assert [w["on"] for w in tune["wakes"]][0] == ["run_started"]


def test_включение_кладёт_копию_рядом_с_базой(page, tmp_path):
    factory = (aside_mod.factory_dir() / "tune.yml").read_text(encoding="utf-8")
    edits = page.aside_view("tune")
    edits["enabled"] = True
    edits["wakes"][0]["model"] = "haiku"
    edits["budget"]["runs_per_task"] = 5
    page.aside_save("tune", edits)

    saved = aside_mod.load_by_name("tune")
    assert saved.enabled and saved.limit("runs_per_task", 0) == 5
    assert saved.wake_for("run_started").model == "haiku"
    assert saved.wake_for("run_ended").model == "opus[1m]", "чужой повод не должен меняться"
    assert (aside_mod.factory_dir() / "tune.yml").read_text(encoding="utf-8") == factory
    assert aside_mod.is_custom("tune")

    page.aside_reset("tune")
    assert not aside_mod.is_custom("tune") and not aside_mod.load_by_name("tune").enabled


def test_права_со_страницы_не_меняются(page):
    edits = page.aside_view("tune")
    edits["rights"] = ["read", "move", "pr"]
    edits["enabled"] = True
    page.aside_save("tune", edits)
    assert sorted(aside_mod.load_by_name("tune").rights) == [
        "hold", "patch", "pr", "read",
    ]


def test_кривая_правка_не_ложится_на_диск(page):
    edits = page.aside_view("tune")
    edits["budget"]["runs_per_task"] = "много"
    with pytest.raises(ValueError):
        page.aside_save("tune", edits)
    assert not aside_mod.is_custom("tune")


