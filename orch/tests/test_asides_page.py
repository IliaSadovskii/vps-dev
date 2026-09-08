"""Вкладка «Агенты» на странице настройки (`ASIDE-PLAN.md` §12)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from orch import asides as aside_mod
from orch import secrets

SCRIPT = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "orch" / "files" / "orch-chains"


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(aside_mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(secrets, "PATH", tmp_path / "secrets.json")
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
    assert view["notify"] == {"token": False, "bot": "", "chats": [], "awaiting": False}


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
    assert sorted(aside_mod.load_by_name("tune").rights) == ["hold", "patch", "pr", "read"]


def test_кривая_правка_не_ложится_на_диск(page):
    edits = page.aside_view("tune")
    edits["budget"]["runs_per_task"] = "много"
    with pytest.raises(ValueError):
        page.aside_save("tune", edits)
    assert not aside_mod.is_custom("tune")


def test_токен_бота_ложится_в_секреты_с_правами_0600(page, tmp_path, monkeypatch):
    monkeypatch.setattr(page, "Telegram", lambda token: type("T", (), {"whoami": lambda s: "orch_bot"})())
    with pytest.raises(ValueError):
        page.notify_token("123")
    page.notify_token("1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
    state = page.notify_state()
    assert state["token"] is True and state["awaiting"] is True and state["chats"] == []
    assert state["bot"] == "orch_bot"
    assert oct((tmp_path / "secrets.json").stat().st_mode)[-3:] == "600"
    assert "AAHdqTcv" not in str(state), "токен не должен уезжать на страницу"


def test_проверка_связи_шлёт_сообщение_в_привязанные_чаты(page, monkeypatch):
    """«Должно работать» — не проверка: между токеном, чатом и телефоном
    три места, где всё встанет молча."""
    ушло = []

    class ФейкБот:
        def __init__(self, token):
            self.token = token

        def send(self, chat, text, buttons=None):
            ушло.append((chat, text))
            return "1"

    monkeypatch.setattr(page, "Telegram", ФейкБот)
    with pytest.raises(ValueError):
        page.notify_test()                       # ни бота, ни чата

    secrets.set_telegram(token="1234567890:AAH", chats=[42, 77], names={"42": "Владелец"})
    assert page.notify_test() == ["42", "77"]
    assert [c for c, _ in ушло] == [42, 77]
    assert "проверка канала" in ушло[0][1]

    state = page.notify_state()
    assert state["chats"] == [{"id": "42", "name": "Владелец"}, {"id": "77", "name": "77"}]


def test_не_дошло_говорится_прямо(page, monkeypatch):
    from orch.telegram import TelegramError

    class Молчун:
        def __init__(self, token):
            pass

        def send(self, chat, text, buttons=None):
            raise TelegramError("sendMessage: 403 bot was blocked by the user")

    monkeypatch.setattr(page, "Telegram", Молчун)
    secrets.set_telegram(token="1234567890:AAH", chats=[42])
    with pytest.raises(ValueError) as exc:
        page.notify_test()
    assert "не дошло" in str(exc.value)
