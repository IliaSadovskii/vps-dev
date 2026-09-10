"""Клиент AoE: транспорт, повторы, тихие отказы. Живой демон не трогается.

Здесь проверяется то, чего поддельный AoE из `conftest` показать не может:
как клиент переживает обрыв, чем отличает «подожди» от «нет», и что отказ
на оформлении сессии не пропадает без следа.
"""

from __future__ import annotations

import urllib.request

import pytest

from orch import aoe as mod
from orch.aoe import Aoe, AoeError, route_of


def клиент(monkeypatch, **kw) -> Aoe:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return Aoe("http://127.0.0.1:1", **kw)


class _Ответ:
    def __init__(self, body=b"{}", error: Exception | None = None) -> None:
        self.body, self.error = body, error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if self.error:
            raise self.error
        return self.body


def test_обрыв_на_чтении_ответа_тоже_AoeError(monkeypatch):
    """`urlopen` заворачивает в `URLError` только ошибки соединения; таймаут
    на чтении вылетал голым `TimeoutError` мимо всех `except AoeError` и
    ронял проход целиком."""
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _Ответ(error=TimeoutError("timed out")),
    )
    with pytest.raises(AoeError) as exc:
        клиент(monkeypatch).call("GET", "/api/sessions")
    assert exc.value.status == 0 and "TimeoutError" in str(exc.value)


def test_ответ_не_json_тоже_AoeError(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _Ответ(body=b"<html>502 Bad Gateway</html>"),
    )
    with pytest.raises(AoeError) as exc:
        клиент(monkeypatch).call("GET", "/api/sessions")
    assert "не JSON" in str(exc.value)


def test_промпт_повторяется_пока_воркер_поднимается(monkeypatch):
    """У `/acp/prompt` транзиентный отказ — 503 с текстом `worker_not_ready`,
    а не JSON `session_transient` (тот у терминального `/send`). По старому
    признаку повтор не срабатывал никогда."""
    aoe = клиент(monkeypatch)
    calls: list[str] = []

    def call(method, path, body=None, timeout=None):
        calls.append(path)
        if len(calls) == 1:
            raise AoeError(503, "worker_not_ready: session/load in flight", path)
        return {"disposition": "sent"}

    aoe.call = call
    assert aoe.prompt("s1", "привет") == {"disposition": "sent"}
    assert len(calls) == 2


def test_промпт_не_повторяется_на_обычной_ошибке(monkeypatch):
    aoe = клиент(monkeypatch)
    calls: list[str] = []

    def call(method, path, body=None, timeout=None):
        calls.append(path)
        raise AoeError(404, "session not found", path)

    aoe.call = call
    with pytest.raises(AoeError):
        aoe.prompt("s1", "привет")
    assert len(calls) == 1


def test_session_не_глотает_отказ_aoe(monkeypatch):
    """`None` для движка значит «сессии нет»: задача уходит в `abandoned`, а
    её рабочая копия — под нож. Один таймаут не должен стоить задачи."""
    aoe = клиент(monkeypatch)

    def call(method, path, body=None, timeout=None):
        raise AoeError(0, "timed out", path)

    aoe.call = call
    with pytest.raises(AoeError):
        aoe.session("s1")


def test_архив_идёт_PATCH_с_телом(monkeypatch):
    """`POST` на этот маршрут отвечает 405 и ничего не архивирует."""
    aoe = клиент(monkeypatch)
    seen = []
    aoe.call = lambda method, path, body=None, timeout=None: seen.append((method, path, body)) or {}
    aoe.archive("s1")
    assert seen == [("PATCH", "/api/sessions/s1/archive", {"archived": True})]


def test_тихий_отказ_запоминается_и_доходит_до_хука_раз_на_маршрут(monkeypatch):
    """`POST /archive` отвечал 405 сутками, и по журналу это было не видно."""
    seen: list[AoeError] = []
    aoe = клиент(monkeypatch, on_quiet_error=seen.append)

    def call(method, path, body=None, timeout=None):
        raise AoeError(405, "Method Not Allowed", path)

    aoe.call = call
    aoe.archive("s1")
    aoe.archive("s2")            # тот же маршрут — хук молчит
    aoe.set_color("s1", "red")   # другой маршрут — зовётся снова
    assert [route_of(e.path) for e in seen] == [
        "/api/sessions/{id}/archive",
        "/api/sessions/{id}/color",
    ]
    assert set(aoe.quiet_failures) == {
        "PATCH /api/sessions/{id}/archive",
        "PATCH /api/sessions/{id}/color",
    }


def test_сломанный_хук_не_роняет_оформление(monkeypatch):
    def хук(exc):
        raise RuntimeError("хук сломан")

    aoe = клиент(monkeypatch, on_quiet_error=хук)

    def call(method, path, body=None, timeout=None):
        raise AoeError(500, "x", path)

    aoe.call = call
    aoe.set_title("s1", "т")     # не бросает


def test_висящий_вопрос_читается_из_frames(monkeypatch):
    """Ключ ленты — `frames`; по выдуманному `events` вопрос не находился никогда."""
    aoe = клиент(monkeypatch)
    aoe.call = lambda *a, **kw: {"frames": [
        {"event": {"ElicitationRequested": {"elicitation": {"nonce": "n1", "title": "Цвет?"}}}},
        {"event": {"ElicitationResolved": {"nonce": "n1", "outcome": "accepted"}}},
        {"event": {"ElicitationRequested": {"elicitation": {"nonce": "n2", "title": "Размер?"}}}},
    ]}
    assert aoe.pending_question("s1")["nonce"] == "n2"
    aoe.call = lambda *a, **kw: {"frames": [
        {"event": {"ElicitationRequested": {"elicitation": {"nonce": "n1"}}}},
        {"event": {"ElicitationResolved": {"nonce": "n1"}}},
    ]}
    assert aoe.pending_question("s1") is None


def test_маршрут_без_id_сессии():
    assert route_of("/api/sessions/abc123/archive") == "/api/sessions/{id}/archive"
    assert route_of("/api/sessions/abc123") == "/api/sessions/{id}"
    assert route_of("/api/sessions?state=live") == "/api/sessions"
