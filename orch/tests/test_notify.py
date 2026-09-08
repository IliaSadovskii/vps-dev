"""Канал наружу: находки, ворота, решения владельца (`ASIDE-PLAN.md` §9)."""

from __future__ import annotations

import json

import pytest

from orch import secrets
from orch.db import WAITING
from orch.notify import Notifier

from tests.test_aside import SPEC, асайды
from tests.test_engine import start, turn


class FakeTelegram:
    """Тот же интерфейс, что у `orch.telegram.Telegram`, но без сети."""

    def __init__(self, token: str = "тест:токен-подлиннее-двадцати") -> None:
        self.token = token
        self.sent: list[dict] = []
        self.queue: list[dict] = []
        self.answers: list[str] = []
        self.edits: list[str] = []
        self.next_id = 100

    @property
    def ready(self) -> bool:
        return bool(self.token)

    def whoami(self) -> str:
        return "orch_bot"

    def send(self, chat, text, buttons=None) -> str:
        self.next_id += 1
        self.sent.append({"chat": chat, "text": text, "buttons": buttons or []})
        return str(self.next_id)

    def edit(self, chat, message_id, text) -> None:
        self.edits.append(text)

    def updates(self, offset: int, timeout: int = 0) -> list[dict]:
        out = [u for u in self.queue if u["update_id"] >= offset]
        return out

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.answers.append(text)


@pytest.fixture
def bot(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "PATH", tmp_path / "secrets.json")
    fake = FakeTelegram()
    engine.notifier = Notifier(engine, fake)
    secrets.set_telegram(token=fake.token, chats=[42], offset=0, awaiting_chat=False)
    return fake


def зови(engine, task_id):
    """Владелец попросил звать его в Telegram по этой задаче."""
    task = engine.db.task(task_id)
    engine.set_notify_gates(task_id, task["revision"], True)


def находка(engine, задача, severity="hold", options=None):
    aside_id = engine.db.aside_open("tune", "run", задача, задача)
    with engine.db.tx():
        return engine.db.note_add(
            aside_id, None, задача, severity, "Ревью читало не тот файл", "Подробности.",
            options if options is not None else [
                {"verb": "restart", "target": None, "label": "перезапустить шаг"}
            ],
        )


def test_находка_уходит_с_кнопками_и_отказом_первым(engine, fake, repo, bot):
    task_id = start(engine, repo)
    находка(engine, task_id)
    engine.notify().pump()

    assert len(bot.sent) >= 1
    письмо = bot.sent[0]
    подписи = [b["label"] for b in письмо["buttons"]]
    assert подписи[0] == "Ничего не делать", "кнопка отказа должна стоять первой"
    assert "перезапустить шаг" in подписи
    assert "Ревью читало не тот файл" in письмо["text"]
    assert engine.db.note(1)["state"] == "sent"

    engine.notify().pump()
    assert len([s for s in bot.sent if "Ревью" in s["text"]]) == 1, "находка ушла дважды"


def test_нажатие_исполняет_решение(engine, fake, repo, bot):
    task_id = start(engine, repo)
    note_id = находка(engine, task_id)
    engine.stop(task_id, "aside_hold")
    engine.notify().pump()

    bot.queue = [{
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "data": f"n:{note_id}:continue:",
            "message": {"message_id": 101, "chat": {"id": 42}, "text": "…"},
        },
    }]
    engine.notify().pump()

    note = engine.db.note(note_id)
    assert note["state"] == "answered" and note["decision"].startswith("continue")
    assert engine.db.task(task_id)["status"] != WAITING, "задача осталась стоять"
    assert any(k["kind"] == "note_decided" for k in [
        {"kind": r["kind"]} for r in engine.db.events(task_id, limit=50)
    ])


def test_чужой_чат_ничего_не_двигает(engine, fake, repo, bot):
    task_id = start(engine, repo)
    note_id = находка(engine, task_id)
    engine.notify().pump()
    bot.queue = [{
        "update_id": 5,
        "callback_query": {
            "id": "cb2",
            "data": f"n:{note_id}:restart:",
            "message": {"message_id": 1, "chat": {"id": 999}, "text": "…"},
        },
    }]
    engine.notify().pump()
    assert engine.db.note(note_id)["state"] == "sent"
    assert "не привязан" in bot.answers[-1]


def test_ворота_уходят_один_раз_на_ревизию(engine, fake, repo, bot):
    task_id = start(engine, repo)
    зови(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")        # ворота
    engine.notify().pump()
    engine.notify().pump()
    ворота = [s for s in bot.sent if s["text"].startswith("⏸")]
    assert len(ворота) == 1
    подписи = [b["label"] for b in ворота[0]["buttons"]]
    assert подписи[:2] == ["Принять", "Ещё заход"]
    # Возвраты, которые цепочка разрешает шагу, — человеческими именами.
    assert подписи[2:] == ["Вернуть на «one»"]
    assert "Шаг:" in ворота[0]["text"]


def test_вопрос_роли_в_мессенджер_не_тащим(engine, fake, repo, bot):
    task_id = start(engine, repo)
    зови(engine, task_id)
    engine.stop(task_id, "ask")
    engine.notify().pump()
    assert not [s for s in bot.sent if s["text"].startswith("⏸")]


def test_первое_сообщение_привязывает_чат(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "PATH", tmp_path / "secrets.json")
    fake = FakeTelegram()
    notifier = Notifier(engine, fake)
    assert "привязан" in notifier.bind_token(fake.token)
    assert secrets.telegram()["awaiting_chat"] is True

    fake.queue = [{
        "update_id": 1,
        "message": {"chat": {"id": 77, "title": "Владелец"}, "text": "/start"},
    }]
    # Чужое сообщение до `/start` чат не привязывает.
    notifier.pump()
    notifier.pump()
    assert secrets.telegram()["chats"] == [77]
    assert secrets.telegram()["awaiting_chat"] is False
    assert notifier.live


def test_кривой_токен_не_записывается(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "PATH", tmp_path / "secrets.json")
    notifier = Notifier(engine, FakeTelegram(token=""))
    assert "не похоже на токен" in notifier.bind_token("123")
    assert secrets.telegram() == {}


def test_под_тестами_канал_молчит_даже_с_настоящим_токеном(monkeypatch, tmp_path):
    """Единственная защита, которую нельзя забыть включить в новом тесте."""
    from orch.telegram import Telegram, TelegramError

    monkeypatch.setattr(secrets, "PATH", tmp_path / "secrets.json")
    secrets.set_telegram(token="1234567890:настоящий-токен-длиннее-двадцати", chats=[42])
    bot = Telegram()
    assert bot.ready is False, "канал считает себя рабочим под тестами"
    with pytest.raises(TelegramError):
        bot.send(42, "это не должно уйти")


def test_в_воротах_приходит_слово_роли_а_не_причина(engine, fake, repo, bot, monkeypatch):
    """Владелец решает по тому, что сказала роль, а не по «ждёт решения»."""
    from orch import notify as mod

    monkeypatch.setattr(
        mod.Notifier, "role_said",
        lambda self, task: "## Для владельца\n\nПлан готов, спорных мест два: …",
    )
    task_id = start(engine, repo)
    зови(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    engine.notify().pump()

    письмо = next(s for s in bot.sent if s["text"].startswith("⏸"))
    assert "План готов, спорных мест два" in письмо["text"]
    assert "ждёт вашего решения" not in письмо["text"]


def test_длинное_слово_роли_режется_по_абзацу(engine, fake, repo, bot, monkeypatch):
    """Telegram обрежет сам и посреди слова — лучше обрежем мы по абзацу."""
    from orch import notify as mod

    длинно = ("абзац из нескольких слов.\n\n" * 200) + "последний абзац"
    monkeypatch.setattr(mod.Notifier, "role_said", lambda self, task: длинно)
    task_id = start(engine, repo)
    зови(engine, task_id)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    engine.notify().pump()

    письмо = next(s for s in bot.sent if s["text"].startswith("⏸"))
    assert len(письмо["text"]) < mod.Notifier.SAY_LIMIT + 400
    assert "дальше в чате задачи" in письмо["text"]
    assert "последний абзац" not in письмо["text"]


def test_ворота_в_телеграм_по_умолчанию_не_ходят(engine, fake, repo, bot):
    """Звать или не звать — свойство задачи, и по умолчанию не звать."""
    task_id = start(engine, repo)
    turn(engine, fake, task_id, "one", 1, None)
    turn(engine, fake, task_id, "two", 1, "ok")
    engine.notify().pump()
    assert not [s for s in bot.sent if s["text"].startswith("⏸")]

    # Находка роли уходит и без этой настройки: ради неё канал и заводился.
    aside_id = engine.db.aside_open("tune", "run", task_id, task_id)
    with engine.db.tx():
        engine.db.note_add(aside_id, None, task_id, "fyi", "Нашлось", "…", [])
    engine.notify().pump()
    assert [s for s in bot.sent if "Нашлось" in s["text"]]
