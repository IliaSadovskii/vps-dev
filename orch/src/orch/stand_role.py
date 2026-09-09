"""Стенд задачи со стороны движка: роль «Стенд» и роль «Уборка стенда».

Движок делает единственное, чего роль не может, — берёт блок портов
(`stand.py`), — а поднимает и гасит окружение роль в своей сессии. За
уборкой движок следит и добивает сам, если роль не справилась за
`TEARDOWN_GRACE_MIN` (`UX-PLAN.md`, «Стенд задачи»)."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from . import stand as stands
from .aoe import AoeError
from .chain import prompts_dir
from .db import WAITING as ST_WAITING, epoch, now
from .naming import group_of

# Знак служебной сессии в сайдбаре: строки стенда стоят вперемешку со
# строками шагов, и по знаку видно, что это обслуга задачи, а не её работа.
# У побочных ролей знак берётся из их описания (`icon`), у стенда он один.
# Кит, а не пробирка: зелёная пробирка сливалась с зелёными кружками шагов.
STAND_ICON = "🐳"

# Сколько ждём уборщика стенда, прежде чем убрать самим. Пятнадцати минут
# хватает на `docker compose down` даже с тяжёлыми томами; дольше ждать —
# значит держать порты и контейнеры за закрытой задачей.
TEARDOWN_GRACE_MIN = 15


class StandMixin:
    # Стенд — побочная роль (`ASIDE-PLAN.md` §11): его сессии живут в
    # `aside`/`aside_run`, а на задаче остаётся только то, что про задачу:
    # нужен ли стенд, чей блок портов, какой порт открывать.
    def stand_session(self, task_id: str) -> str | None:
        """Сессия, в которой роль «Стенд» поднимает окружение, или None."""
        return self._aside_session(task_id, "stand")

    def teardown_session(self, task_id: str) -> str | None:
        return self._aside_session(task_id, "stand-down")

    def teardown_started_at(self, task_id: str) -> str | None:
        row = self._aside_run(task_id, "stand-down")
        return row["started_at"] if row else None

    def _aside_session(self, task_id: str, name: str) -> str | None:
        row = self._aside_run(task_id, name)
        return row["session_id"] if row else None

    def _aside_run(self, task_id: str, name: str):
        aside = self.db.aside_live(name, task_id)
        if aside is None:
            return None
        return self.db.aside_run_open(int(aside["id"]))

    def _aside_finish(self, task_id: str, name: str) -> None:
        """Закрыть побочную роль задачи вместе с её незакрытым ходом."""
        aside = self.db.aside_live(name, task_id)
        if aside is None:
            return
        run = self.db.aside_run_open(int(aside["id"]))
        if run is not None:
            self.db.aside_run_end(int(run["id"]), None)
        self.db.aside_close(int(aside["id"]))

    def stand_if_wanted(self, task) -> None:
        """Задача впервые встала и ждёт владельца — поднять стенд, если заказан.

        Привязка именно к остановке, а не к воротам: у задачи с выключенными
        воротами ворот не будет вовсе, а посмотреть работу владелец придёт всё
        равно — на вопросе роли, на «нет сигнала» или на приёмке.
        """
        if task is None or not task["stand_wanted"]:
            return
        if self.stand_session(task["id"]) or self.teardown_session(task["id"]):
            return
        if task["status"] not in (ST_WAITING,):
            return
        self.raise_stand(task)

    def raise_stand(self, task) -> str:
        """Занять блок портов и посадить роль «Стенд» поднимать окружение."""
        if not task["worktree_path"]:
            return "рабочей копии ещё нет"
        if self.stand_session(task["id"]):
            return "стенд уже поднимает роль в своей сессии"
        if not self.capacity(task["id"], "стенд"):
            return "нет места под сессию: машина занята"
        aside_id = self.db.aside_open("stand", "task", task["id"], task["id"])
        name, error = stands.claim(task)
        if error:
            self.db.event(task["id"], "stand_failed", {"stage": "claim", "error": error})
            return f"не смог занять порты: {error[:200]}"
        try:
            session = self.aoe.create(
                path=task["worktree_path"],
                agent="claude",
                model="sonnet",
                effort=None,
                title=f"{STAND_ICON} {task['id']} · стенд",
                group=task["group_path"] or group_of(
                    task["project_path"], task["id"], task["title"]
                ),
                # Ключ детерминированный: падение между созданием сессии и
                # записью в базу не должно оставлять вторую сессию. Номер
                # попытки в ключе — стенд можно поднимать заново после отказа.
                # Ключ детерминированный: падение между созданием сессии и
                # записью в базу не должно оставлять вторую сессию. Номер
                # записи роли делает ключ разным у попыток: после отказа
                # стенд поднимают заново, и это должна быть новая сессия.
                idempotency_key=f"{task['id']}@{task['created_at']}/stand/{aside_id}",
            )
        except AoeError as exc:
            self.db.event(task["id"], "stand_failed", {"stage": "session", "error": str(exc)})
            return f"сессия стенда не создалась: {exc}"
        self.aoe.apply_model(session.id, "sonnet")
        prompt = prompts_dir() / "role-stand.md"
        text = prompt.read_text(encoding="utf-8") if prompt.exists() else ""
        text += "\n\n" + self.stand_context(task, name)
        try:
            self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(task["id"], "stand_failed", {"stage": "prompt", "error": str(exc)})
        with self.db.tx():
            run_id = self.db.aside_run_start(aside_id, "raise", None)
            self.db.aside_run_sent(run_id, session.id)
            self.db.bump(task["id"], stand=name, stand_wanted=1)
            self.db.event(
                task["id"], "stand_started", {"name": name, "session": session.id}
            )
        return "роль «Стенд» поднимает окружение"

    def stand_context(self, task, name: str) -> str:
        """Блок задачи для роли «Стенд»: где, чем и под каким именем."""
        ports = stands.ports_of(name)
        lines = [
            "# Блок задачи",
            "",
            f"Задача {task['id']}: {task['title']}",
            f"Проект: `{task['project_path']}`",
            f"Рабочая копия, в ней и работай: `{task['worktree_path']}`",
            f"Ветка задачи: `{task['branch']}`",
            "",
            f"Имя твоего блока портов: `{name}`",
        ]
        if ports:
            lines.append("Выданные порты:")
            for key, value in sorted(ports.items(), key=lambda kv: kv[1]):
                lines.append(f"- `{key}` = {value}")
        lines += [
            "",
            f"Записку положи в `{Path(task['worktree_path']) / '.orch' / task['id'] / 'artifacts' / 'stand.md'}`.",
            "Закончи ход `orch stand ready <порт>` — или `orch stand failed \"причина\"`,",
            "если поднять не вышло.",
        ]
        return "\n".join(lines)

    def stand_result(self, task_id: str, port: int | None, error: str | None) -> None:
        """Что роль «Стенд» сообщила: адрес или причину, почему не вышло."""
        task = self.db.task(task_id)
        if task is None:
            return
        with self.db.tx():
            if error:
                # Сессия роли отпускается: иначе кнопка «Поднять стенд» не
                # вернётся, и после «нет .env.example» стенд не поднять уже
                # никак. Блок портов остаётся за задачей — `ports claim`
                # на занятое имя отвечает тем же блоком.
                self.db.bump(task_id, stand_port=None)
                self._aside_finish(task_id, "stand")
                self.db.event(task_id, "stand_failed", {"stage": "role", "error": error[:400]})
            else:
                self.db.bump(task_id, stand_port=int(port) if port else None)
                self.db.event(task_id, "stand_ready", {"port": port})

    def drop_stand(self, task) -> None:
        """Позвать роль убрать стенд. Ждать её движок не будет вечно.

        Гасит не движок: стенд мог подняться не только докером, и что именно
        поднялось, знает тот, кто поднимал (записка `stand.md`). Но уборка
        обязана случиться, поэтому за ролью следит `watch_teardown`: не
        справилась за `TEARDOWN_GRACE_MIN` — движок добивает сам.
        """
        name = task["stand"] if "stand" in task.keys() else None
        if not name or self.teardown_session(task["id"]):
            return
        prompt = prompts_dir() / "role-stand-down.md"
        text = prompt.read_text(encoding="utf-8") if prompt.exists() else ""
        text += "\n\n" + self.teardown_context(task, name)
        session = None
        try:
            session = self.aoe.create(
                path=task["worktree_path"] or task["project_path"],
                agent="claude",
                model=self.settings.cheap_model,
                effort=None,
                title=f"{STAND_ICON} {task['id']} · уборка стенда",
                group=task["group_path"] or group_of(
                    task["project_path"], task["id"], task["title"]
                ),
                idempotency_key=f"{task['id']}@{task['created_at']}/teardown",
            )
            self.aoe.apply_model(session.id, self.settings.cheap_model)
            self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(task["id"], "teardown_failed", {"stage": "session", "error": str(exc)})
            # Сессии нет — убираем сами, тянуть нечего.
            self.force_drop_stand(task, name, "сессия уборщика не создалась")
            return
        with self.db.tx():
            self._aside_finish(task["id"], "stand")
            aside_id = self.db.aside_open("stand-down", "task", task["id"], task["id"])
            run_id = self.db.aside_run_start(aside_id, "teardown", None)
            self.db.aside_run_sent(run_id, session.id)
            self.db.bump(task["id"], stand_port=None)
            self.db.event(
                task["id"], "teardown_started", {"name": name, "session": session.id}
            )

    def teardown_context(self, task, name: str) -> str:
        """Что уборщику нужно знать: блок, копия, где записка стенда."""
        ports = stands.ports_of(name)
        root = task["worktree_path"] or task["project_path"]
        note = Path(root) / ".orch" / task["id"] / "artifacts" / "stand.md"
        lines = [
            "# Блок задачи",
            "",
            f"Задача {task['id']}: {task['title']} — закрыта, убираем за ней.",
            f"Имя блока портов: `{name}`",
            f"Рабочая копия: `{root}`",
            f"Записка стенда, если она есть: `{note}`",
        ]
        if ports:
            # Один порт бывает под двумя именами переменных: в списке он не
            # должен двоиться.
            lines.append(
                "Порты блока: " + ", ".join(str(v) for v in sorted(set(ports.values())))
            )
        return "\n".join(lines)

    def watch_teardown(self) -> None:
        """Проверить за уборщиком и добить, если он не справился."""
        for aside in self.db.asides_live("stand-down"):
            task = self.db.task(aside["scope_key"])
            if task is None:
                self.db.aside_close(int(aside["id"]))
                continue
            name = task["stand"]
            if not name or stands.gone(name):
                self.finish_teardown(task, "убрано")
                continue
            started = epoch(self.teardown_started_at(task["id"]))
            if started is None or (time.time() - started) / 60 < TEARDOWN_GRACE_MIN:
                continue
            self.force_drop_stand(task, name, "уборщик не успел")

    def force_drop_stand(self, task, name: str, why: str) -> None:
        """Добить уборку самим: команды `ports`, без агента."""
        error = stands.down(task, name)
        self.db.event(
            task["id"], "teardown_forced", {"name": name, "why": why, "error": error[:300]}
        )
        self.finish_teardown(task, "добито движком")

    def finish_teardown(self, task, how: str) -> None:
        """Уборка закончена: сессию в архив, поля стенда очищены."""
        session = self.teardown_session(task["id"])
        if session:
            self.aoe.archive(session)
        with self.db.tx():
            self._aside_finish(task["id"], "stand")
            self._aside_finish(task["id"], "stand-down")
            self.db.bump(task["id"], stand=None, stand_port=None)
            self.db.event(task["id"], "teardown_done", {"how": how})

