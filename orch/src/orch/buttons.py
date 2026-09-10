"""Кнопки владельца: единственный вход панели и `orch task move` в движок.

Кнопка несёт ревизию задачи; устаревшая отклоняется, двойной клик — одно
движение (`PLAN.md` §2, правило 4). Любой ход владельца сначала закрывает
открытый заход, если он есть: иначе движок продолжал бы следить за мёртвой
сессией."""

from __future__ import annotations

from .chain import DONE, Chain, ChainError
from .db import (
    BACKLOG,
    CLOSED,
    DONE as ST_DONE,
    QUEUED,
    RUNNING as ST_RUNNING,
    WAITING as ST_WAITING,
    now,
)
from .workspace import git, git_try


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
            "back_clean": self._btn_back_clean,
            "again": self._btn_again,
            "continue": self._btn_again,
            "start": self._btn_start,
            "accept_as_is": self._btn_accept,
            "close": self._btn_close,
            "pause": self._btn_pause,
            "restart_step": self._btn_restart_step,
            "rewind": self._btn_rewind,
        }.get(action)
        if handler is None:
            return f"неизвестное действие {action}"
        if action not in ("stand", "pause"):
            self.close_open_run(task, chain, action)
        return handler(task, chain, target, comment)

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

    def _btn_back_clean(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        return self._btn_back(task, chain, target, comment, clean=True)

    def _btn_back(
        self, task, chain: Chain, target: str | None, comment: str | None, clean: bool = False
    ) -> str:
        """Владелец отправляет задачу на другой шаг.

        Предел заходов держит роли, а не владельца: если у шага, куда он
        посылает, заходы кончились, кнопка сама добавляет один. Иначе
        «Отправить на ревью ещё раз» приводила бы задачу на шаг, который
        движок тут же остановит по пределу.

        `clean` — вернуть начисто: всё, что задача сделала с тех пор, как
        последний раз была на этом шаге, забывается (`forget_after`). Без
        него возврат сохраняет память: шаг с `context: own` продолжит свою
        прошлую сессию, а артефакты нижних шагов останутся на месте и уедут
        в промпты следующих заходов.
        """
        step = chain.step(task["step"])
        if not target or target not in step.human_moves:
            return f"вернуть можно на: {', '.join(step.human_moves) or '—'}"
        target_step = chain.step(target)
        forgotten: dict = {}
        if clean:
            forgotten = self.forget_after(task, chain, target)
        done_runs = len(
            [r for r in self.db.runs_of_step(task["id"], target) if not r["void_at"]]
        )
        grant = done_runs >= self.runs_allowed(task, target_step)
        with self.db.tx():
            revision = self.db.bump(task["id"], status=ST_RUNNING, step=target, wait_reason=None)
            self.db.move(
                task["id"], step.id, target, "human",
                "grant_run" if grant else "button", revision, comment=comment,
            )
            self.db.event(
                task["id"],
                "button",
                {"action": "back_clean" if clean else "back", "to": target, "grant": grant},
            )
        answer = f"вернул на {target}" + (" (заход добавлен)" if grant else "")
        if clean:
            файлы = ", ".join(forgotten.get("artifacts") or []) or "нечего"
            answer += (
                f"; начисто: забыто заходов {len(forgotten.get('runs') or [])}, "
                f"убрано в историю: {файлы}"
            )
        return answer

    def forget_after(self, task, chain: Chain, target: str) -> dict:
        """Забыть всё, что задача сделала с последнего захода в шаг `target`.

        Забываются заходы (их сессии больше не подхватит `context: own` и
        `continue`, а предел заходов считается заново) и артефакты шагов
        ниже по цепочке — они уезжают в `history/cleared-<время>`. Артефакт
        самого шага-цели остаётся: роль перепишет свой файл сама, а
        соседям он нужен как основание (T26: `solution.md` уцелел,
        `plan.md` и `plan-review.md` ушли).
        """
        runs = [r for r in self.db.runs_of_step(task["id"], target) if not r["void_at"]]
        if not runs:
            return {"runs": [], "artifacts": []}
        first = int(runs[-1]["id"])
        doomed = [
            r
            for r in self.db.conn.execute(
                "SELECT * FROM run WHERE task_id = ? AND id >= ? AND void_at IS NULL ORDER BY id",
                (task["id"], first),
            )
        ]
        names: list[str] = []
        for step_id in {r["step"] for r in doomed} - {target}:
            try:
                names += chain.step(step_id).artifact
            except ChainError:
                continue
        свои = set(chain.step(target).artifact) if target else set()
        names = sorted({n for n in names if n not in свои})
        moved: list[str] = []
        if task["worktree_path"]:
            moved = self.workspace(task).clear_artifacts(names, now().replace(":", "-"))
        with self.db.tx():
            for run in doomed:
                self.db.void_run(int(run["id"]))
            # Находки побочных ролей висели дальше возврата: карточка с
            # вопросом про план осталась в панели, когда самого плана уже не
            # было — задача поехала заново со scoping (T37, 2026-09-10).
            # Забыли ход — забыли и то, что о нём сказали.
            снято = [
                int(n["id"])
                for n in self.db.notes(task_id=task["id"])
                if n["state"] in ("open", "sent")
            ]
            for note_id in снято:
                self.db.note_state(note_id, "dropped", decided_at=now(), decision="переиграно")
            self.db.event(
                task["id"],
                "cleared",
                {
                    "to": target,
                    "runs": [int(r["id"]) for r in doomed],
                    "artifacts": moved,
                    "notes": снято,
                    "after_move": self.db.last_move_id(task["id"]),
                },
            )
        return {"runs": [int(r["id"]) for r in doomed], "artifacts": moved}

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

    def _btn_pause(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Пауза: задача стоит, пока владелец не скажет «Продолжить».

        Остановка руками в AoE паузой не была: движок видел `Idle`, считал
        ход брошенным и толкал роль дальше. Пауза — состояние задачи, и
        толкать в нём нечего.
        """
        if task["status"] == ST_WAITING and task["wait_reason"] == "paused":
            return "уже на паузе"
        self.stop(task["id"], "paused", urgent=True, interrupt=True)
        return "на паузе; «Продолжить» вернёт в работу"

    def _btn_restart_step(
        self, task, chain: Chain, target: str | None, comment: str | None
    ) -> str:
        """Начать шаг заново, начисто: как будто он сюда и не приходил.

        Не «ещё заход»: заходы, файлы и находки этого шага и всех, что были
        после него, забываются, и предел считается с нуля. Шаг может не
        значиться в своих же `human_moves` — на себя цепочка возвращать не
        обязана, а владелец вправе.
        """
        step = target or task["step"]
        if not step or not chain.has(step):
            return "нечего начинать заново: шаг не назван"
        forgotten = self.forget_after(task, chain, step)
        with self.db.tx():
            self.db.event(
                task["id"], "button", {"action": "restart_step", "to": step}
            )
            revision = self.db.bump(
                task["id"], status=ST_RUNNING, step=step, wait_reason=None
            )
            self.db.move(
                task["id"], task["step"], step, "human", "button", revision, comment=comment
            )
        файлы = ", ".join(forgotten.get("artifacts") or []) or "нечего"
        return (
            f"шаг {step} начинается заново; забыто заходов "
            f"{len(forgotten.get('runs') or [])}, убрано в историю: {файлы}"
        )

    def _btn_rewind(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Откатить задачу на любой шаг так, будто она туда пришла впервые.

        «Начать шаг заново» переигрывает последний круг: заходы шага
        забываются с последнего входа в него. Откат — сильнее: шаг и всё,
        что было после, стирается целиком, включая первый заход и файл
        самого шага. Роль приходит на чистое место, без памяти, без своего
        прошлого файла и без пути, из которого видно, что она тут уже была.

        Коммиты ветки тоже откатываются — до состояния перед первым заходом
        шага. Работа не пропадает: перед сбросом ставится ветка-запаска
        `orch/<задача>-<время>`, с неё всё поднимается.
        """
        step = target or task["step"]
        if not step or not chain.has(step):
            return f"откатить можно на: {', '.join(s.id for s in chain.steps)}"

        runs = [r for r in self.db.runs_of_step(task["id"], step) if not r["void_at"]]
        первый = runs[0] if runs else None
        doomed = list(
            self.db.conn.execute(
                "SELECT * FROM run WHERE task_id = ? AND void_at IS NULL "
                "AND id >= ? ORDER BY id",
                (task["id"], int(первый["id"]) if первый else 0),
            )
        ) if первый else []

        # Файлы: свои у шага тоже уходят — он приходит сюда впервые.
        names: list[str] = []
        for step_id in {r["step"] for r in doomed} | {step}:
            try:
                names += chain.step(step_id).artifact
            except ChainError:
                continue
        tag = now().replace(":", "-")
        moved: list[str] = []
        if task["worktree_path"]:
            moved = self.workspace(task).clear_artifacts(sorted(set(names)), tag)

        запаска = self.rewind_git(task, первый, tag)

        with self.db.tx():
            for run in doomed:
                self.db.void_run(int(run["id"]))
            for note in self.db.notes(task_id=task["id"]):
                if note["state"] in ("open", "sent"):
                    self.db.note_state(
                        int(note["id"]), "dropped", decided_at=now(), decision="откат"
                    )
            # Отметка «начисто» идёт раньше движения: по ней обрезается путь
            # задачи, и движение на целевой шаг должно остаться по эту
            # сторону границы.
            self.db.event(
                task["id"],
                "cleared",
                {
                    "to": step,
                    "runs": [int(r["id"]) for r in doomed],
                    "artifacts": moved,
                    "backup": запаска,
                    "after_move": self.db.last_move_id(task["id"]),
                },
            )
            revision = self.db.bump(
                task["id"], status=ST_RUNNING, step=step, wait_reason=None
            )
            self.db.move(
                task["id"], task["step"], step, "human", "button", revision, comment=comment
            )
        self.archive_runs([r["session_id"] for r in doomed])
        хвост = f"; ветка откачена, запаска {запаска}" if запаска else ""
        return (
            f"откат на {step}: забыто заходов {len(doomed)}, "
            f"убрано в историю: {', '.join(moved) or 'нечего'}{хвост}"
        )

    def rewind_git(self, task, первый, tag: str) -> str | None:
        """Вернуть ветку к состоянию перед первым заходом шага.

        Без этого откат врёт: файлы ролей стёрты, а код, который они успели
        написать, остался в ветке, и следующая роль строит поверх работы,
        которой по документам не было.
        """
        if not первый or not первый["start_sha"] or not task["worktree_path"]:
            return None
        root = task["worktree_path"]
        head = git(root, "rev-parse", "HEAD")
        if not head or head == первый["start_sha"]:
            return None
        запаска = f"orch/{task['id'].lower()}-{tag}"
        code, out = git_try(root, "branch", запаска, head)
        if code != 0:
            self.db.event(task["id"], "rewind_failed", {"error": out[:300]})
            return None
        code, out = git_try(root, "reset", "--hard", первый["start_sha"])
        if code != 0:
            self.db.event(task["id"], "rewind_failed", {"error": out[:300]})
            return запаска
        return запаска

    def archive_runs(self, session_ids: list) -> None:
        """Сессии забытых заходов уезжают в архив: в сайдбаре их больше нет."""
        for sid in {s for s in session_ids if s}:
            self.aoe.archive(sid)

    def _btn_start(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        if task["status"] not in (BACKLOG, QUEUED):
            return "задача уже идёт"
        with self.db.tx():
            self.db.bump(task["id"], status=QUEUED)
            self.db.event(task["id"], "button", {"action": "start"})
        return "в очередь"

    # ── вспомогательное ──────────────────────────────────────────────────
