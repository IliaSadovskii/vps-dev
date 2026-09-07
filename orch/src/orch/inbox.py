"""Заявки из `inbox/`: единственный путь снаружи в базу.

Команда `orch` в сессиях и в терминале базу не пишет (`PLAN.md` §2, правило
1): она кладёт файл-заявку, а движок превращает её в действие на ближайшем
проходе. Заявка бывает: новая задача, кнопка из терминала, слово роли
«Стенд», новое ТЗ, вызов мастера."""

from __future__ import annotations

import json

from .db import BACKLOG, INBOX
from .naming import title_from


class InboxMixin:
    def take_inbox(self) -> None:
        """Заявки из `inbox/`: новая задача, кнопка из терминала, сессия Inbox.

        Так `orch` в сессии и в терминале не пишет в базу: писатель один.
        """
        if not INBOX.is_dir():
            return
        for path in sorted(INBOX.glob("*.json")):
            try:
                request = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
                continue
            kind = request.get("kind", "new")
            try:
                if kind == "button":
                    answer = self.button(
                        request["task"],
                        request["revision"],
                        request["action"],
                        request.get("target"),
                        request.get("comment"),
                    )
                    self.db.event(request["task"], "button_from_cli", {"answer": answer})
                elif kind == "stand":
                    if request.get("gone"):
                        row = self.db.task(request["task"])
                        if row is not None:
                            # Слово уборщика проверяем: блок должен быть отдан.
                            self.watch_teardown()
                    else:
                        self.stand_result(
                            request["task"], request.get("port"), request.get("error")
                        )
                elif kind == "edit_text":
                    self.edit_text(request["task"], request["text"])
                elif kind == "wizard":
                    self.open_wizard(
                        request["project_path"],
                        request.get("task"),
                        request.get("mode") or "start",
                    )
                else:
                    task_id = self.create_task(
                        chain_name=request.get("chain") or self.settings.default_chain,
                        project_path=request["project_path"],
                        text=request["text"],
                        preset=request.get("preset"),
                        sheet_edits=request.get("sheet_edits") or {},
                        backlog=bool(request.get("backlog")),
                        branch=request.get("branch"),
                        base=request.get("base"),
                        author=request.get("author"),
                        from_backlog=request.get("from_backlog"),
                        stand=bool(request.get("stand")),
                    )
                    self.db.event(task_id, "task_created", {"from": "inbox", "file": path.name})
            except Exception as exc:  # noqa: BLE001 — одна кривая заявка не останавливает движок
                # Ловим всё: `take_inbox` идёт первым в проходе, и заявка, на
                # которой он падает, останавливала бы каждый проход, пока
                # файл лежит в `inbox/`. Файл убирается в любом случае.
                self.db.event(
                    None, "inbox_rejected", {"file": path.name, "error": repr(exc)[:400]}
                )
            path.unlink(missing_ok=True)

    def edit_text(self, task_id: str, text: str) -> str:
        """Переписать ТЗ заявки. Только пока она в бэклоге: у поехавшей задачи
        текст уже разошёлся по промптам прошлых шагов, и молча менять его —
        врать ролям."""
        task = self.db.task(task_id)
        if task is None:
            return "нет такой задачи"
        if task["status"] != BACKLOG:
            return f"{task_id} уже не в бэклоге: текст правится только у заявки"
        with self.db.tx():
            self.db.bump(task_id, text=text, title=title_from(text))
            self.db.event(task_id, "text_edited", {"len": len(text)})
        # Мастер, переписавший ТЗ, свою работу сделал — в архив, как и тот,
        # что заводил задачу.
        self.move_wizard_to(task_id, task["project_path"])
        return f"{task_id}: ТЗ переписано"
