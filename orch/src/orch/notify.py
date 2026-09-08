"""Ворота задачи в Telegram: сообщение владельцу и его решение обратно.

Канал возит ровно одно — задачу, вставшую на владельце, — и только если
владелец сам попросил об этом флажком на задаче. Побочные роли в мессенджер
не пишут: их находки видны в панели, а отчёт они кладут в свою сессию, которая
живёт до конца прогона и ждёт владельца (решение 2026-09-08).
"""

from __future__ import annotations

import json

import time

from . import secrets
from .db import WAIT_REASONS
from .telegram import Telegram, TelegramError

# Сколько ждём `/start` после ввода токена. Окно короткое намеренно: пока
# оно открыто, привязаться может любой, кто знает имя бота.
BIND_WINDOW_S = 15 * 60

# Кнопки, которые движок предлагает сам, когда задача встала на владельце.
GATE_BUTTONS = {
    "gate": [("accept", "Принять"), ("again", "Ещё заход")],
    "aside_hold": [("accept", "Продолжать"), ("again", "Ещё заход")],
    "no_signal": [("accept", "Принять как есть"), ("again", "Ещё заход")],
    "max_runs": [("accept", "Принять как есть"), ("again", "Ещё заход")],
    "error": [("again", "Ещё заход")],
}


class Notifier:
    """Доставка наружу и приём решений. Живёт внутри движка."""

    def __init__(self, engine, telegram: Telegram | None = None) -> None:
        self.engine = engine
        self.db = engine.db
        self.telegram = telegram if telegram is not None else Telegram()

    # ── настройка канала ─────────────────────────────────────────────────
    @property
    def chats(self) -> list[int]:
        return [int(c) for c in (secrets.telegram().get("chats") or [])]

    @property
    def live(self) -> bool:
        """Канал работает: токен есть и хотя бы один чат привязан."""
        return bool(self.telegram.ready and self.chats)

    def bind_token(self, token: str) -> str:
        clean = (token or "").strip()
        if ":" not in clean or len(clean) < 20:
            return "это не похоже на токен бота"
        self.telegram.token = clean
        try:
            name = self.telegram.whoami()
        except TelegramError as exc:
            self.telegram.token = secrets.telegram().get("token") or ""
            return f"бот не отозвался: {exc}"
        secrets.set_telegram(
            token=clean, chats=[], offset=0, awaiting_chat=True,
            awaiting_until=time.time() + BIND_WINDOW_S, bot=name,
        )
        return f"бот @{name} привязан; напишите ему /start с телефона"

    def bind_chat(self, chat_id: int, title: str = "") -> str:
        block = secrets.telegram()
        chats = [int(c) for c in (block.get("chats") or [])]
        if int(chat_id) in chats:
            return "этот чат уже привязан"
        chats.append(int(chat_id))
        names = dict(block.get("names") or {})
        names[str(chat_id)] = title[:80] or str(chat_id)
        secrets.set_telegram(chats=chats, names=names, awaiting_chat=False)
        self.db.event(None, "notify_chat_bound", {"chat": chat_id, "title": title[:80]})
        return f"чат {title or chat_id} привязан"

    def forget(self) -> str:
        secrets.forget_telegram()
        self.telegram.token = ""
        return "бот отвязан, токен стёрт"

    def test(self) -> str:
        if not self.live:
            return "канала нет: привяжите бота и чат"
        try:
            for chat in self.chats:
                self.telegram.send(chat, "orch на связи.")
        except TelegramError as exc:
            return f"не дошло: {exc}"
        return "проверочное сообщение ушло"

    # ── проход ───────────────────────────────────────────────────────────
    def pump(self) -> None:
        """Отправить новое, забрать решения. Ошибка канала не роняет проход."""
        try:
            self.take_updates()
        except TelegramError as exc:
            self.engine.note_once(None, "notify_offline", {"error": str(exc)[:200]})
        if not self.live:
            return
        try:
            self.send_gates()
        except TelegramError as exc:
            self.engine.note_once(None, "notify_failed", {"error": str(exc)[:200]})

    # ── исходящее ────────────────────────────────────────────────────────
    def send_gates(self) -> None:
        """Задача встала на владельце — сказать об этом там, где он есть.

        Спрашивает не машина, а сама задача: одну владелец ведёт с телефона
        и хочет знать сразу, другая едет фоном и звать не должна. Флажок
        ставится мастером при заведении и кнопкой в панели задачи.
        """
        for task in self.db.tasks(("waiting",)):
            if not task["notify_gates"]:
                continue
            reason = task["wait_reason"] or "gate"
            if reason == "ask":
                # Вопрос роли владелец видит в самой сессии, там и отвечает:
                # тащить разговор в мессенджер значит разорвать его надвое.
                continue
            mark = f"{task['id']}@{task['revision']}"
            if self.already("notify_gate", mark):
                continue
            buttons = [
                {"label": label, "data": f"b:{task['id']}:{task['revision']}:{action}:"}
                for action, label in GATE_BUTTONS.get(reason, GATE_BUTTONS["gate"])
            ]
            buttons += self.back_buttons(task)
            text = self.gate_text(task, reason)
            for chat in self.chats:
                self.telegram.send(chat, text, buttons)
            with self.db.tx():
                self.db.event(task["id"], "notify_gate", {"mark": mark})

    def gate_text(self, task, reason: str) -> str:
        """Сообщение о воротах: то, что сказала роль, а не служебная причина.

        Владелец решает по этому тексту, с телефона. «Ворота: ждёт вашего
        решения» ему не говорит ничего — решать надо по последнему слову
        роли, а оно лежит в её ходе.
        """
        from . import panels

        step = panels.step_title(task["step"]) if task["step"] else "—"
        head = f"⏸ <b>{escape(task['title'])}</b> · {task['id']}\nШаг: {escape(step)}"
        said = self.trim(self.role_said(task))
        if said:
            return f"{head}\n\n{escape(said)}"
        return (
            f"{head}\n\n{escape(WAIT_REASONS.get(reason, reason))}\n"
            f"{escape(panels._what_to_decide(self.db, task))}"
        )

    # Сколько слов роли уносим в мессенджер: длинное сообщение Telegram
    # обрежет сам, и лучше это сделаем мы — по границе абзаца.
    SAY_LIMIT = 1500

    def role_said(self, task) -> str:
        """Последнее, что роль сказала владельцу, — из её же хода."""
        from . import digest as dg

        run = self.db.last_run_of_step(task["id"], task["step"] or "")
        if run is None or not task["worktree_path"]:
            return ""
        try:
            data = dg.digest(
                task["worktree_path"], since=run["started_at"], until=run["ended_at"]
            )
        except OSError:
            return ""
        return (data.get("final") or "").strip()

    def trim(self, said: str) -> str:
        """Обрезка по границе абзаца: Telegram обрежет сам и посреди слова."""
        said = (said or "").strip()
        if len(said) <= self.SAY_LIMIT:
            return said
        cut = said[: self.SAY_LIMIT].rsplit("\n\n", 1)[0].rstrip()
        return f"{cut}\n\n… дальше в чате задачи."

    def back_buttons(self, task) -> list[dict]:
        """Возвраты, которые цепочка разрешает этому шагу, — человеческими именами."""
        from . import panels

        chain = panels._chain(task)
        if chain is None or not task["step"]:
            return []
        try:
            step = chain.step(task["step"])
        except Exception:  # noqa: BLE001 — сломанная цепочка не должна ронять канал
            return []
        return [
            {
                "label": f"Вернуть на «{panels.step_title(target)}»",
                "data": f"b:{task['id']}:{task['revision']}:back:{target}",
            }
            for target in step.human_moves[:3]
        ]

    def gate_text(self, task, reason: str) -> str:
        """Сообщение о воротах: то, что сказала роль, а не служебная причина.

        Владелец решает по этому тексту, с телефона. «Ворота: ждёт вашего
        решения» ему не говорит ничего.
        """
        from . import panels

        step = panels.step_title(task["step"]) if task["step"] else "—"
        head = f"⏸ <b>{escape(task['title'])}</b> · {task['id']}\nШаг: {escape(step)}"
        said = self.trim(self.role_said(task))
        if said:
            return f"{head}\n\n{escape(said)}"
        return (
            f"{head}\n\n{escape(WAIT_REASONS.get(reason, reason))}\n"
            f"{escape(panels._what_to_decide(self.db, task))}"
        )

    # Сколько слов роли уносим в мессенджер: длинное сообщение Telegram
    # обрежет сам, и лучше это сделаем мы — по границе абзаца.
    SAY_LIMIT = 1500

    def role_said(self, task) -> str:
        """Последнее, что роль сказала владельцу, — из её же хода."""
        from . import digest as dg

        run = self.db.last_run_of_step(task["id"], task["step"] or "")
        if run is None or not task["worktree_path"]:
            return ""
        try:
            data = dg.digest(
                task["worktree_path"], since=run["started_at"], until=run["ended_at"]
            )
        except OSError:
            return ""
        return (data.get("final") or "").strip()

    def trim(self, said: str) -> str:
        """Обрезка по границе абзаца: Telegram обрежет сам и посреди слова."""
        said = (said or "").strip()
        if len(said) <= self.SAY_LIMIT:
            return said
        cut = said[: self.SAY_LIMIT].rsplit("\n\n", 1)[0].rstrip()
        return f"{cut}\n\n… дальше в чате задачи."

    def back_buttons(self, task) -> list[dict]:
        """Возвраты, которые цепочка разрешает шагу, — человеческими именами."""
        from . import panels

        chain = panels._chain(task)
        if chain is None or not task["step"]:
            return []
        try:
            step = chain.step(task["step"])
        except Exception:  # noqa: BLE001 — сломанная цепочка не роняет канал
            return []
        return [
            {
                "label": f"Вернуть на «{panels.step_title(target)}»",
                "data": f"b:{task['id']}:{task['revision']}:back:{target}",
            }
            for target in step.human_moves[:3]
        ]

    def already(self, kind: str, mark: str) -> bool:
        row = self.db.conn.execute(
            "SELECT 1 FROM event WHERE kind = ? AND payload LIKE ? LIMIT 1",
            (kind, f'%"{mark}"%'),
        ).fetchone()
        return row is not None

    # ── входящее ─────────────────────────────────────────────────────────
    def take_updates(self) -> None:
        if not self.telegram.ready:
            return
        block = secrets.telegram()
        offset = int(block.get("offset") or 0)
        updates = self.telegram.updates(offset)
        if not updates:
            return
        last = offset
        for update in updates:
            last = max(last, int(update.get("update_id", 0)) + 1)
            self.handle(update, block)
        secrets.set_telegram(offset=last)

    def handle(self, update: dict, block: dict) -> None:
        message = update.get("message") or {}
        chat = (message.get("chat") or {}).get("id")
        if message and chat is not None:
            # Привязываем только по слову `/start` и только в окне, которое
            # владелец сам открыл на странице: бот виден по имени, и чат
            # первого написавшего — не то же самое, что чат владельца.
            text = str(message.get("text") or "").strip().lower()
            in_window = float(block.get("awaiting_until") or 0) > time.time()
            if (
                block.get("awaiting_chat")
                and in_window
                and text.startswith("/start")
                and int(chat) not in self.chats
            ):
                title = (message.get("chat") or {}).get("title") or (
                    (message.get("from") or {}).get("first_name") or ""
                )
                self.bind_chat(int(chat), str(title))
                self.telegram.send(int(chat), "Чат привязан. Сюда будут приходить решения.")
            return

        query = update.get("callback_query") or {}
        if not query:
            return
        chat = ((query.get("message") or {}).get("chat") or {}).get("id")
        if chat is None or int(chat) not in self.chats:
            # Чужой чат: у него нет права двигать задачи, даже если он как-то
            # получил кнопку.
            self.telegram.answer_callback(query.get("id", ""), "этот чат не привязан")
            return
        answer = self.decide(str(query.get("data") or ""))
        self.telegram.answer_callback(query.get("id", ""), answer[:190])
        message_id = str((query.get("message") or {}).get("message_id") or "")
        if message_id:
            old = (query.get("message") or {}).get("text") or ""
            self.telegram.edit(int(chat), message_id, f"{escape(old)}\n\n✅ {escape(answer)}")

    def decide(self, data: str) -> str:
        """Нажатие: находка или кнопка задачи. Разбирает движок, не канал."""
        kind, _, rest = data.partition(":")
        parts = rest.split(":")
        if kind == "b" and len(parts) >= 3:
            task_id, revision, action = parts[0], int(parts[1]), parts[2]
            target = parts[3] or None if len(parts) > 3 else None
            return self.engine.button(task_id, revision, action, target)
        return "не понял кнопку"


def escape(text: str) -> str:
    return (
        str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
