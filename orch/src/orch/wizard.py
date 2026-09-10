"""Мастер задачи: сессия, в которой владелец заводит задачу разговором.

Панель не умеет ни поля ввода, ни дропдауна (`UX-PLAN.md`), поэтому
цепочку, ветку и автономию спрашивает роль `role-wizard.md` в чате, а потом
сама зовёт `orch task new`. Три входа: строка проекта в панели, сессия с
группой `orch` из штатной модалки, палитра. Заведя задачу, мастер уходит в
архив; ссылка на разговор остаётся в панели задачи."""

from __future__ import annotations

import uuid
from pathlib import Path

from .aoe import AoeError, Session
from .chain import catalog, prompts_dir
from .naming import group_for, wizard_group
from .workspace import projects_on_disk


class WizardMixin:
    # Слово, которым владелец в штатной модалке «New session» помечает, что
    # сессия заводится под оркестратор: поле Group = `orch`.
    WIZARD_MARK = "orch"

    def marked_for_orch(self, session: Session) -> bool:
        """Владелец пометил сессию как заявку на задачу.

        Метка — слово `orch` в поле Group штатной модалки «New session» или
        в титуле сессии. Поле «дополнительные аргументы» для метки не годится:
        `GET /api/sessions` его не отдаёт вовсе, плагин его не увидит.
        """
        if session.group.strip().lower() == self.WIZARD_MARK:
            return True
        title = session.title.strip().lower()
        return title == self.WIZARD_MARK or title.startswith(f"{self.WIZARD_MARK} ")

    def adopt_wizards(self, sessions: dict[str, Session]) -> list[str]:
        """Сессия с группой `orch` становится мастером задачи.

        Кнопка в панели знает проект, но не знает всех проектов машины, а
        владелец и так заводит сессии штатной модалкой, где проект
        выбирается привычно. Поэтому второй вход: в поле Group написать
        `orch` — и движок сам пошлёт в эту сессию промпт мастера. Группа
        сразу меняется на `orch/мастер`, поэтому дважды одну сессию не
        усыновим.
        """
        adopted = []
        for session in sessions.values():
            if not self.marked_for_orch(session):
                continue
            if not session.project_path:
                continue
            self.aoe.set_group(session.id, wizard_group(session.project_path))
            self.aoe.set_title(session.id, f"Мастер · {Path(session.project_path).name}")
            # Модель ставится вызовом: `agent_model` до адаптера не доезжает,
            # и мастер молча уходил бы на Opus.
            self.aoe.apply_model(session.id, "sonnet")
            self.db.event(
                None,
                "wizard_adopted",
                {"session": session.id, "project": session.project_path},
            )
            self.send_wizard_prompt(session.id, session.project_path, None, "start")
            adopted.append(session.id)
        return adopted

    def send_wizard_prompt(self, sid: str, project: str, task, mode: str) -> None:
        """Промпт мастера с каталогом цепочек и контекстом заявки."""
        prompt_file = prompts_dir() / "role-wizard.md"
        text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        text += "\n\n" + self.wizard_context(project, catalog(), task, mode)
        try:
            self.aoe.prompt(sid, text)
        except AoeError as exc:
            self.db.event(None, "wizard_prompt_failed", {"session": sid, "error": str(exc)})

    def open_wizard(
        self,
        project_path: str,
        task_id: str | None = None,
        mode: str = "start",
    ) -> str | None:
        """Мастер задачи: сессия, в которой владелец заводит задачу разговором.

        Панель не умеет ни поля ввода, ни дропдауна (`UX-PLAN.md`), поэтому
        цепочку, ветку и автономию спрашивает роль в чате вариантами, а потом
        сама зовёт `orch task new`. Сессия одна на проект: мастер дешёвый, и
        плодить их на каждую заявку незачем.
        """
        project = str(Path(project_path).resolve())
        task = self.db.task(task_id) if task_id else None
        # Свободный мастер этого проекта, если он есть. По ключу
        # идемпотентности его не найти: ключ живёт вечно и вернул бы сессию,
        # которая уже уехала в группу заведённой задачи.
        free = self.free_wizard(project)
        if free is not None:
            self.send_wizard_prompt(free, project, task, mode)
            self.db.event(
                task_id, "wizard_reused", {"project": project, "session": free, "mode": mode}
            )
            return free
        try:
            session = self.aoe.create(
                path=project,
                agent="claude",
                model="sonnet",
                effort=None,
                title=f"Мастер · {Path(project).name}",
                group=wizard_group(project),
                # Ключ уникален на вызов: повтор мастера не страшен, а вот
                # вернуть по вечному ключу сессию, уехавшую в группу задачи,
                # — страшно. От лишних сессий бережёт поиск свободного выше.
                idempotency_key=f"wizard/{project}/{uuid.uuid4().hex[:8]}",
            )
        except AoeError as exc:
            self.db.event(None, "wizard_failed", {"project": project, "error": str(exc)})
            return None
        # Группу ставим отдельным вызовом: при создании AoE её не применяет,
        # и мастер оказывался вне группы, вперемешку с сессиями шагов.
        self.aoe.set_group(session.id, wizard_group(project))
        # Модель ставится вызовом, а не полем при создании: `agent_model` до
        # адаптера Claude не доезжает, и сессия молча уходит на Opus (см.
        # `apply_model`). Мастер — дешёвая роль, платить за него Opus незачем.
        if not self.aoe.apply_model(session.id, "sonnet"):
            self.db.event(
                None,
                "wizard_model_not_applied",
                {"session": session.id, "got": self.aoe.model_now(session.id)},
            )
        self.send_wizard_prompt(session.id, project, task, mode)
        self.db.event(
            task_id,
            "wizard_opened",
            {"project": project, "session": session.id, "mode": mode},
        )
        return session.id

    def projects_on_disk(self) -> list[str]:
        """Репозитории каталога проектов — мастеру, когда проект ещё не выбран."""
        return projects_on_disk(self.settings.projects_dir or "/projects")

    def wizard_context(self, project: str, chains: list[dict], task, mode: str) -> str:
        """Блок «чем располагаешь» для мастера: цепочки, проект, заявка."""
        lines = ["## Чем располагаешь", "", f"Проект: `{project}`", "", "Цепочки:"]
        for item in chains:
            if item.get("error"):
                lines.append(f"- `{item['name']}` — не читается: {item['error']}")
                continue
            gates = ", ".join(item["gates"]) or "нет"
            lines.append(
                f"- `{item['name']}` — {item['description'] or 'без описания'}\n"
                f"  шаги: {' → '.join(item['steps'])}\n"
                f"  ворота по умолчанию: {gates}\n"
                "  пресеты автономии:\n"
                + (
                    "\n".join(
                        f"    - `{name}` — "
                        f"{(item.get('preset_notes') or {}).get(name) or 'без пояснения'}"
                        for name in item["presets"]
                    )
                    or "    - нет"
                )
            )
        if task is not None:
            lines += [
                "",
                f"## Заявка {task['id']} из бэклога",
                "",
                "Текст, который владелец уже записал:",
                "",
                "```",
                (task["text"] or "").strip(),
                "```",
                "",
                f"Ветка заявки: {task['branch'] or 'не выбрана'}.",
            ]
            if mode == "text":
                lines.append(
                    "Владелец нажал «Править ТЗ»: перепиши текст в разговоре и, "
                    f"когда он одобрит, вызови `orch task edit {task['id']} --text -`. "
                    "Задачу не запускай."
                )
            else:
                lines.append(
                    "Владелец нажал «В работу»: уточни, что нужно, спроси цепочку, "
                    "ветку и автономию и отпусти заявку вызовом "
                    f"`orch task start {task['id']} --chain … --preset …`. Поедет "
                    f"она сама: номер {task['id']} останется за задачей до конца, "
                    "новую заводить не надо. Названное тобой заменит записанное в "
                    "заявке, остальное останется как есть; переписанное ТЗ — "
                    "флагом `--text -`."
                )
        elif mode == "pick":
            names = ", ".join(f"`{p}`" for p in self.projects_on_disk()) or "не нашёл"
            lines += [
                "",
                "## Новая задача в другом проекте",
                "",
                "Владелец нажал «другой проект»: он ещё не сказал, в каком "
                "проекте работать. Спроси вариантами. Проекты машины: " + names + ".",
                "",
                "Путь, который он назовёт, передай команде флагом `--project`. "
                "Каталог этой сессии к делу не относится: она заведена, чтобы "
                "было где разговаривать.",
            ]
        else:
            lines += [
                "",
                "## Новая задача",
                "",
                "Владелец нажал «Новая задача»: начни с вопроса, что он хочет.",
            ]
        return "\n".join(lines)

    def free_wizard(self, project: str) -> str | None:
        """Живая сессия мастера этого проекта, ещё не занятая задачей."""
        try:
            sessions = self.aoe.sessions()
        except AoeError:
            return None
        for session in sessions.values():
            if not (session.group or "").endswith("/мастер"):
                continue
            if str(Path(session.project_path).resolve()) == project:
                return session.id
        return None

    def move_wizard_to(self, task_id: str, project: str) -> None:
        """Мастер, заведший задачу, уходит в архив.

        Рядом с ходами задачи его строку не поставить: сайдбар группирует по
        каталогу сессии, а мастер живёт в проекте, тогда как шаги — в рабочей
        копии. Держать вечную строку в стороне незачем: разговор о постановке
        никуда не девается, ссылка на него — в панели задачи. Номер задачи
        остаётся в титуле, чтобы сессия находилась поиском.
        """
        task = self.db.task(task_id)
        if task is None:
            return
        try:
            sessions = self.aoe.sessions()
        except AoeError:
            return
        for session in sessions.values():
            if not (session.group or "").endswith("/мастер"):
                continue
            if str(Path(session.project_path).resolve()) != project:
                continue
            self.aoe.set_group(
                session.id,
                group_for(task),
            )
            self.aoe.set_title(session.id, f"{task_id} · постановка")
            self.aoe.archive(session.id)
            with self.db.tx():
                self.db.bump(task_id, wizard_session=session.id)
                self.db.event(task_id, "wizard_archived", {"session": session.id})
            return
