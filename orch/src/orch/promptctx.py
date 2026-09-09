"""Что движок знает о задаче к старту шага: контекст для `promptbuild`.

Сборка текста — чистая функция в `promptbuild.py`; здесь собирается её вход
из базы и папки задачи: путь по шагам, откуда пришла роль, комментарии
владельца, что изменилось с прошлого захода, правки владельца в чужих
файлах, роли подагентов."""

from __future__ import annotations

import hashlib
import os
import re

from . import artifacts as art
from . import promptbuild
from . import stand as stands
from .chain import Chain, ChainError, Step, prompts_dir
from .db import epoch
from .workspace import Workspace


class PromptContextMixin:
    def gate_after(self, task, step: Step) -> bool | list[str]:
        """Ворота шага по листу автономии задачи, а не по цепочке.

        Лист переключают в панели по ходу, поэтому спрашивать надо его.
        """
        return (self.sheet(task).get(step.id) or {}).get("after", step.human_after)

    def extra_includes(self, task, step: Step) -> list[str]:
        """Общие файлы, которые движок добавляет по состоянию, а не по цепочке.

        Правила про ворота и про отчёт владельцу нужны только роли, после
        которой задача встанет: остальным это сто строк не по адресу — команда,
        которой им не воспользоваться, и форма сообщения, которого они не
        пишут (`PROMPT-NOTES.md`, прогон T16).
        """
        return ["common-report", "common-gate"] if self.gate_after(task, step) else []

    def assemble(self, task, chain: Chain, step: Step, run, ws: Workspace):
        """Собрать промпт и вернуть (текст, sha, id доставленных комментариев)."""
        comments = self.db.undelivered_comments(task["id"], step.id)
        prev = self.db.last_run_of_step(task["id"], step.id)
        prev_end = None
        if run["n"] > 1:
            rows = self.db.runs_of_step(task["id"], step.id)
            done = [r for r in rows if r["n"] == run["n"] - 1]
            prev_end = done[0]["end_sha"] if done else None

        ctx = promptbuild.Context(
            chain=chain,
            step=step,
            task_id=task["id"],
            task_text=task["text"],
            task_dir=ws.path,
            root=ws.root,
            run_n=run["n"],
            path_steps=self.db.path_steps(task["id"]),
            came_from=self.came_from(task, step, run, has_comment=bool(comments)),
            comments=[c["comment"] for c in comments],
            ask_allowed=self.ask_allowed(task, step),
            changed_since=ws.diff_stat(prev_end),
            later_artifacts=self.later_artifacts(ws, step, prev),
            owner_edited=self.owner_edited(task, ws, chain, step),
            sub_prompts=self.sub_prompts(step),
            extra_includes=self.extra_includes(task, step),
            gate_after=self.gate_after(task, step),
            stand_name=stands.name_of(task) if task["worktree_path"] else "",
            branch=task["branch"] or "",
            base_branch=task["base_branch"] or "",
            start_sha=self.task_start_sha(task),
        )
        text = promptbuild.build(ctx)
        if ctx.oversized:
            self.db.event(task["id"], "prompt_oversized", {"step": step.id, "run": run["n"]})
        return text, hashlib.sha256(text.encode()).hexdigest(), [c["id"] for c in comments]

    def task_start_sha(self, task) -> str:
        """Коммит, с которого началась работа задачи.

        Стартовый снимок первого захода: от него считают дифф Ревью кода,
        скрипт владения тестами и PR. Не путать с началом текущего захода —
        тот показывает только последний кусок работы.
        """
        row = self.db.conn.execute(
            "SELECT start_sha FROM run WHERE task_id = ? AND start_sha IS NOT NULL "
            "ORDER BY id LIMIT 1",
            (task["id"],),
        ).fetchone()
        return (row["start_sha"] or "")[:12] if row else ""

    def came_from(self, task, step: Step, run, has_comment: bool = True) -> str:
        if run["n"] == 1 and not self.db.moves(task["id"], limit=2):
            return ""
        # Первый заход шага: продолжать нечего, даже если сюда привела кнопка
        # «ещё заход» (её жмут и на вставшей задаче, которая шаг не начинала).
        # Фраза «продолжи с места остановки» отправила бы роль искать свой
        # прошлый файл, которого нет.
        if run["n"] == 1:
            past = self.db.conn.execute(
                "SELECT COUNT(*) c FROM run WHERE task_id = ? AND step = ? AND id <> ?",
                (task["id"], step.id, run["id"]),
            ).fetchone()["c"]
            if not past:
                return ""
        last = next(
            (m for m in self.db.moves(task["id"], limit=10) if m["to_step"] == step.id), None
        )
        if last is None:
            return ""
        if last["actor"] == "human":
            if last["from_step"] == step.id:
                return promptbuild.came_from_phrase("again")
            return promptbuild.came_from_phrase("human", has_comment=has_comment)
        if last["actor"] == "agent" and last["from_step"] != step.id:
            files = ""
            try:
                sender = self.chain_of(task).step(last["from_step"])
                ws = self.workspace(task)
                files = ", ".join(f"`{ws.artifacts / a}`" for a in sender.artifact)
            except (ChainError, KeyError, TypeError):
                pass
            return promptbuild.came_from_phrase(
                "role", last["from_step"], detail_files=files
            )
        return ""

    def later_artifacts(self, ws: Workspace, step: Step, prev) -> list[str]:
        """Файлы из `reads`, обновлённые после прошлого захода этого шага."""
        if not prev or not prev["ended_at"]:
            return []
        cutoff = epoch(prev["ended_at"])
        if cutoff is None:
            return []
        out = []
        for name in step.reads:
            path = ws.artifacts / name
            try:
                if os.path.getmtime(path) > cutoff:
                    out.append(name)
            except OSError:
                continue
        return out

    def owner_edited(self, task, ws: Workspace, chain: Chain, step: Step) -> list[str]:
        """Файлы, отпечаток которых изменился после сдачи роли (`PLAN.md` §5).

        Смотрим последнюю сдачу каждого шага: владелец мог поправить руками
        файл любой из пройденных ролей, не только предыдущей.
        """
        seen: set[str] = set()
        out: list[str] = []
        for move in self.db.moves(task["id"], limit=40):
            if move["actor"] != "agent" or not move["artifact_sha"] or not move["from_step"]:
                continue
            if move["from_step"] in seen:
                continue
            seen.add(move["from_step"])
            try:
                prev_step = chain.step(move["from_step"])
            except ChainError:
                continue
            current = artifact_sha(ws, prev_step)
            if current and current != move["artifact_sha"]:
                # Только про файлы, которые этот шаг читает или пишет сам:
                # про чужие ему знать незачем, а строка выглядит как поручение.
                mine = set(step.reads) | set(step.artifact)
                out.extend(a for a in prev_step.artifact if a in mine)
        return out

    def sub_prompts(self, step: Step) -> list[str]:
        """Пути к ролям подагентов, которые называет сама роль шага.

        Угадывать по имени шага нельзя: шаг `code-review` пользуется файлами
        `sub-review-defects.md` и `sub-review-security.md`, и никакая маска по
        имени шага их не находит. Роль называет их прямо в своём тексте —
        оттуда и берём, тогда список не разъедется с промптом.
        """
        role = prompts_dir() / f"{step.prompt_file}.md"
        try:
            text = role.read_text(encoding="utf-8")
        except OSError:
            return []
        names = sorted(set(re.findall(r"\bsub-[a-z0-9-]+\.md\b", text)))
        return [str(prompts_dir() / n) for n in names if (prompts_dir() / n).exists()]



def artifact_sha(ws: Workspace, step: Step) -> str | None:
    """Общий отпечаток артефактов шага: изменился — файл правили после сдачи."""
    parts = [art.sha(ws.artifacts / name) or "" for name in step.artifact]
    if not any(parts):
        return None
    return hashlib.sha256("".join(parts).encode()).hexdigest()
