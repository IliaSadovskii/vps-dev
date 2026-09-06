"""Папка задачи в рабочей копии: `.orch/<task>/`.

База — истина о потоке, папка — о содержании; между ними только пути и
отпечатки (`research/DB-NOTES.md`). Порядок записи важен: файлы задачи
пишутся **до** создания сессии, чтобы роль не увидела полузаписанного
состояния (`PLAN.md` §2, правило 7).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SUBDIRS = ("artifacts", "signals", "prompts", "history", "logs")


class Workspace:
    def __init__(self, root: Path | str, task_id: str) -> None:
        self.root = Path(root)
        self.task_id = task_id
        self.path = self.root / ".orch" / task_id

    # ── структура ────────────────────────────────────────────────────────
    @property
    def artifacts(self) -> Path:
        return self.path / "artifacts"

    @property
    def signals(self) -> Path:
        return self.path / "signals"

    @property
    def prompts(self) -> Path:
        return self.path / "prompts"

    @property
    def history(self) -> Path:
        return self.path / "history"

    @property
    def logs(self) -> Path:
        return self.path / "logs"

    def ensure(self, task_text: str, chain_yaml: str) -> None:
        for name in SUBDIRS:
            (self.path / name).mkdir(parents=True, exist_ok=True)
        (self.path / "task.md").write_text(task_text, encoding="utf-8")
        (self.path / "chain.yml").write_text(chain_yaml, encoding="utf-8")
        self.exclude_from_git()

    def exclude_from_git(self) -> None:
        """`.orch/` не попадает в git — локально, без правки `.gitignore` проекта."""
        exclude = self.root / ".git" / "info" / "exclude"
        if not exclude.parent.is_dir():
            # В worktree `.git` — файл; настоящий каталог у основного репозитория.
            gitfile = self.root / ".git"
            if gitfile.is_file():
                try:
                    line = gitfile.read_text(encoding="utf-8").strip()
                    common = Path(line.split(": ", 1)[1])
                    exclude = common / "info" / "exclude"
                    exclude.parent.mkdir(parents=True, exist_ok=True)
                except (OSError, IndexError):
                    return
            else:
                return
        try:
            text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            if ".orch/" not in text:
                exclude.write_text(text.rstrip("\n") + "\n.orch/\n", encoding="utf-8")
        except OSError:
            pass

    # ── текущее состояние для команды `orch` ─────────────────────────────
    def write_current(self, step: str, run: int, session_id: str | None, state: str,
                      branch: str | None = None, reads: list[str] | None = None) -> None:
        payload = {
            "task": self.task_id,
            "step": step,
            "run": run,
            "session_id": session_id,
            "state": state,
            "branch": branch,
            "reads": reads or [],
        }
        tmp = self.path / ".current.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path / "current.json")

    # ── история захода ───────────────────────────────────────────────────
    def save_history(self, step: str, run: int, start_sha: str | None) -> Path:
        """Копия артефактов, дифф захода и логи — на случай возврата."""
        dest = self.history / f"{step}-{run}"
        dest.mkdir(parents=True, exist_ok=True)
        if self.artifacts.is_dir():
            shutil.copytree(self.artifacts, dest / "artifacts", dirs_exist_ok=True)
        if self.logs.is_dir():
            shutil.copytree(self.logs, dest / "logs", dirs_exist_ok=True)
        if start_sha:
            diff = git(self.root, "diff", f"{start_sha}..HEAD")
            (dest / "diff.patch").write_text(diff, encoding="utf-8")
        return dest

    # ── git ──────────────────────────────────────────────────────────────
    def head(self) -> str | None:
        sha = git(self.root, "rev-parse", "HEAD")
        return sha or None

    def diff_stat(self, since: str | None) -> str:
        if not since:
            return ""
        return git(self.root, "diff", "--stat", f"{since}..HEAD")


def git(root: Path | str, *args: str, timeout: float = 60.0) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout
    )
    return out.stdout.strip() if out.returncode == 0 else ""
