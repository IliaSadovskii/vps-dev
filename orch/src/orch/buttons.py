"""Кнопки владельца: единственный вход панели и `orch task move` в движок.

Кнопка несёт ревизию задачи; устаревшая отклоняется, двойной клик — одно
движение (`PLAN.md` §2, правило 4). Любой ход владельца сначала закрывает
открытый заход, если он есть: иначе движок продолжал бы следить за мёртвой
сессией."""

from __future__ import annotations

from .chain import DONE, Chain
from .db import BACKLOG, CLOSED, DONE as ST_DONE, QUEUED, RUNNING as ST_RUNNING, now


class ButtonsMixin:
    def button(
        self,
        task_id: str,
        revision: int,
        action: str,
        target: str | None = None,
        comment: str | None = None,
    ) -> str:
        """Единственный вход для панели. Устаревшая ревизия отклоняется."""
        task = self.db.task(task_id)
        if task is None:
            return "нет такой задачи"
        if int(revision) != int(task["revision"]):
            self.db.event(task_id, "stale_button", {"action": action, "revision": revision})
            return "устаревшая кнопка, панель перерисована"
        chain = self.chain_of(task)
        if chain is None:
            return "цепочка задачи не читается"
        handler = {
            "stand": self._btn_stand,
            "accept": self._btn_accept,
            "back": self._btn_back,
            "again": self._btn_again,
            "continue": self._btn_again,
            "start": self._btn_start,
            "accept_as_is": self._btn_accept,
            "close": self._btn_close,
        }.get(action)
        if handler is None:
            return f"неизвестное действие {action}"
        if action != "stand":
            self.close_open_run(task, chain, action)
        return handler(task, chain, target, comment)

    def set_notify_gates(self, task_id: str, revision: int, on: bool) -> str:
        """Кнопка «Ворота в Telegram» в панели задачи."""
        task = self.db.task(task_id)
        if task is None:
            return "нет такой задачи"
        if int(revision) != int(task["revision"]):
            return "устаревшая кнопка, панель перерисована"
        with self.db.tx():
            self.db.bump(task_id, notify_gates=1 if on else 0)
            self.db.event(task_id, "notify_gates", {"on": bool(on)})
        return "буду звать в Telegram" if on else "звать в Telegram не буду"

    def close_open_run(self, task, chain: Chain, action: str) -> None:
        """Заход, который ещё числится идущим, закрывается перед ходом владельца.

        Задача встаёт с открытым заходом, когда сессия в ошибке или её воркер
        не поднялся: конца хода не было, и `end_run` никто не звал. Если
        такой заход оставить, «Ещё заход» ничего не заводит — движок снова
        смотрит на ту же мёртвую сессию и тут же встаёт, а «Вернуть на …»
        уводит шаг, но следит за прежним заходом. Поэтому заход закрывается
        здесь, без сигнала, и следующий проход начинает новый.
        """
        run = self.db.open_run(task["id"])
        if run is None:
            return
        ws = self.workspace(task)
        end_sha = ws.head() if task["worktree_path"] else None
        if run["session_id"]:
            ws.save_history(run["step"], run["n"], run["start_sha"])
        with self.db.tx():
            self.db.end_run(run["id"], None, end_sha)
            self.db.event(
                task["id"],
                "run_closed_by_owner",
                {"run": run["id"], "step": run["step"], "action": action},
            )

    def _btn_stand(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Поднять стенд задачи — руками роли, а не движка.

        Проекты поднимаются по-разному: одному хватает `docker compose up`,
        другому нужен `.env`, миграции и сборка фронта, третий вообще не
        дописан. Движок этого не знает и знать не должен, поэтому он делает
        единственное, чего роль не может сама — берёт блок портов, — а
        дальше зовёт роль «Стенд» в отдельной сессии.
        """
        return self.raise_stand(task)


    def _btn_accept(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Принять ход владельцем.

        `target` — исход, который владелец выбрал сам («принять как есть» на
        пределе заходов или после хода без сигнала). Без него берём исход,
        которым роль закончила.
        """
        step = chain.step(task["step"])
        last = self.db.last_run_of_step(task["id"], step.id)
        outcome = target or (last["outcome"] if last else None)
        if outcome == "дальше":
            outcome = None
        to = step.target(outcome) or step.target(None)
        if to is None:
            return "не понял, каким исходом принимать: назовите исход"
        with self.db.tx():
            if to == DONE:
                revision = self.db.bump(task["id"], status=ST_DONE, step=None, closed_at=now(), wait_reason=None)
            else:
                revision = self.db.bump(task["id"], status=ST_RUNNING, step=to, wait_reason=None)
            self.db.move(task["id"], step.id, to, "human", "button", revision, comment=comment)
            self.db.event(task["id"], "button", {"action": "accept", "to": to})
            if to == DONE:
                # Задача доведена — то же событие, что пишет движок, когда
                # доводит её сам. Без него всё, что подписано на конец задачи
                # (сводка Наладчика, записка Менеджера), молча не срабатывает.
                self.db.event(task["id"], "done", {"by": "owner"})
        if to == DONE:
            self.drop_stand(self.db.task(task["id"]))
        return "принято"

    def _btn_back(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Владелец отправляет задачу на другой шаг.

        Предел заходов держит роли, а не владельца: если у шага, куда он
        посылает, заходы кончились, кнопка сама добавляет один. Иначе
        «Отправить на ревью ещё раз» приводила бы задачу на шаг, который
        движок тут же остановит по пределу.
        """
        step = chain.step(task["step"])
        if not target or target not in step.human_moves:
            return f"вернуть можно на: {', '.join(step.human_moves) or '—'}"
        target_step = chain.step(target)
        done_runs = len(self.db.runs_of_step(task["id"], target))
        grant = done_runs >= self.runs_allowed(task, target_step)
        with self.db.tx():
            revision = self.db.bump(task["id"], status=ST_RUNNING, step=target, wait_reason=None)
            self.db.move(
                task["id"], step.id, target, "human",
                "grant_run" if grant else "button", revision, comment=comment,
            )
            self.db.event(
                task["id"], "button", {"action": "back", "to": target, "grant": grant}
            )
        return f"вернул на {target}" + (" (заход добавлен)" if grant else "")

    def _btn_again(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """«Ещё заход» / «Продолжай».

        Если задача встала на пределе заходов, кнопка обязана этот предел
        поднять: иначе движок тут же остановит её снова, и владелец будет
        нажимать в пустоту.
        """
        step = chain.step(task["step"])
        grant = task["wait_reason"] == "max_runs"
        with self.db.tx():
            revision = self.db.bump(task["id"], status=ST_RUNNING, wait_reason=None)
            if grant:
                self.db.move(
                    task["id"], step.id, step.id, "human", "grant_run", revision,
                    comment=comment,
                )
            else:
                self.db.move(
                    task["id"], step.id, step.id, "human", "button", revision,
                    comment=comment,
                )
            self.db.event(
                task["id"], "button", {"action": "again", "step": step.id, "grant": grant}
            )
        return "ещё заход" + (" (предел поднят)" if grant else "")

    def _btn_close(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Закрыть задачу, не доводя до конца.

        Роли заводят заявки в бэклог сами, и часть из них никогда не поедет.
        Пока такую задачу нельзя закрыть, она держит свою ветку и мешает
        завести на ней новую.
        """
        with self.db.tx():
            revision = self.db.bump(
                task["id"], status=CLOSED, step=None, closed_at=now(), wait_reason=None
            )
            self.db.move(
                task["id"], task["step"], DONE, "human", "button", revision, comment=comment
            )
            self.db.event(task["id"], "closed", {"comment": comment})
        self.drop_stand(self.db.task(task["id"]))
        return "закрыта"

    def _btn_start(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        if task["status"] not in (BACKLOG, QUEUED):
            return "задача уже идёт"
        with self.db.tx():
            self.db.bump(task["id"], status=QUEUED)
            self.db.event(task["id"], "button", {"action": "start"})
        return "в очередь"

    # ── вспомогательное ──────────────────────────────────────────────────
