"""Канал в Telegram: сообщения владельцу и его решения обратно.

Наружу порт не открывается — бот опрашивается сам (`getUpdates`). Писать
может только тот чат, который владелец привязал: токен даёт право двигать
задачи, и утёкший токен не должен давать чужие руки на кнопках.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import secrets

API = "https://api.telegram.org"


class TelegramError(Exception):
    pass


class Telegram:
    """Тонкая обёртка над HTTP-API бота."""

    def __init__(self, token: str = "", timeout: float = 10.0) -> None:
        self.token = token or (secrets.telegram().get("token") or "")
        self.timeout = timeout

    @property
    def ready(self) -> bool:
        # Под pytest канал молчит всегда, чем бы его ни настроили. Забыть
        # подменить секреты в новом тесте можно, а цена забывчивости —
        # сообщения живому владельцу о выдуманных задачах.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return False
        return bool(self.token)

    def call(self, method: str, body: dict | None = None) -> dict:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            raise TelegramError("под pytest в сеть не ходим")
        data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{API}/bot{self.token}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                answer = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TelegramError(f"{method}: {exc.code} {exc.read()[:200]!r}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TelegramError(f"{method}: {exc}") from exc
        if not answer.get("ok"):
            raise TelegramError(f"{method}: {answer.get('description')}")
        return answer.get("result") or {}

    # ── что умеет канал ──────────────────────────────────────────────────
    def whoami(self) -> str:
        return str(self.call("getMe").get("username") or "")

    def send(self, chat: int | str, text: str, buttons: list[dict] | None = None) -> str:
        body = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
        if buttons:
            body["reply_markup"] = {
                "inline_keyboard": [[{"text": b["label"], "callback_data": b["data"]}]
                                    for b in buttons]
            }
        result = self.call("sendMessage", body)
        return str(result.get("message_id") or "")

    def edit(self, chat: int | str, message_id: str, text: str) -> None:
        try:
            self.call(
                "editMessageText",
                {"chat_id": chat, "message_id": int(message_id), "text": text,
                 "parse_mode": "HTML"},
            )
        except TelegramError:
            # Сообщение могли удалить руками: решение важнее оформления.
            pass

    def updates(self, offset: int, timeout: int = 0) -> list[dict]:
        return list(
            self.call(
                "getUpdates",
                {"offset": offset, "timeout": timeout,
                 "allowed_updates": ["message", "callback_query"]},
            )
        )

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except TelegramError:
            pass
