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
                      branch: str | None = None, reads: list[str] | None = None,
                      gate_after: bool | list[str] = False, ask: bool = True) -> None:
        """Состояние захода для команды `orch`.

        `gate_after` и `ask` — из листа автономии задачи, а не из цепочки:
        по ним роль в промпте узнаёт, встанет ли задача после её хода.
        """
        payload = {
            "task": self.task_id,
            "step": step,
            "run": run,
            "session_id": session_id,
            "state": state,
            "branch": branch,
            "reads": reads or [],
            "gate_after": gate_after,
            "ask": ask,
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
            # Только файлы ролей: снимки экрана и прочее тяжёлое, что роль
            # положила рядом, копировать в историю каждого захода незачем.
            shutil.copytree(
                self.artifacts, dest / "artifacts", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.png", "*.jpg", "*.jpeg", "*.webp", "*.pdf"),
            )
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


def git_try(root: Path | str, *args: str, timeout: float = 300.0) -> tuple[int, str]:
    """Тот же git, но с кодом возврата и текстом ошибки: для действий, где
    молчаливый провал недопустим (создание и удаление рабочей копии)."""
    out = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout
    )
    return out.returncode, (out.stdout + out.stderr).strip()


def worktree_path(project: Path | str, branch: str) -> Path:
    """Где лежит рабочая копия задачи: `../<repo>-orch/<branch>`.

    Нарочно не `<repo>-worktrees`: там держит свои копии сам AoE, и его
    `aoe worktree cleanup` считает чужие каталоги в этой папке брошенными.
    Копии задач лежат отдельно, и убирает их движок — `aoe worktree cleanup`
    orch не зовёт никогда.
    """
    project = Path(project).resolve()
    return project.parent / f"{project.name}-orch" / branch


# Служебные каталоги, которые роли и инструменты оставляют в рабочей копии.
# Их наличие не делает копию «занятой работой»: это не то, что человек
# побоится потерять.
JUNK = (".orch/", ".playwright-mcp/", ".pytest_cache/", "__pycache__/")


def worktree_holder(project: Path | str, branch: str) -> Path | None:
    """Каталог, в котором ветка уже вычекана, или None.

    Git не даёт вычекать одну ветку в двух копиях, поэтому знать держателя
    надо до `worktree add`: иначе задача встаёт с невнятной ошибкой git.
    """
    out = git(project, "worktree", "list", "--porcelain")
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):].strip())
        elif line.startswith("branch ") and path is not None:
            ref = line[len("branch "):].strip()
            if ref in (f"refs/heads/{branch}", branch):
                return path
    return None


def touched_files(path: Path | str, base: str = "") -> set[str]:
    """Файлы, которых задача коснулась в своей копии: коммиты и несохранённое.

    Считается от точки расхождения с базовой веткой, а не от её головы:
    иначе в список попало бы всё, что база успела уехать вперёд.
    """
    root = Path(path)
    if not root.is_dir():
        return set()
    base = base or default_branch(root)
    files: set[str] = set()
    code, out = git_try(root, "merge-base", base, "HEAD")
    point = out.strip() if code == 0 else ""
    if point:
        # `core.quotepath=false` — иначе кириллические пути приезжают
        # экранированными восьмеричными кодами и не совпадают ни с чем.
        code, out = git_try(
            root, "-c", "core.quotepath=false", "diff", "--name-only", f"{point}..HEAD"
        )
        if code == 0:
            files |= {line.strip() for line in out.splitlines() if line.strip()}
    code, out = git_try(root, "-c", "core.quotepath=false", "status", "--porcelain")
    if code == 0:
        for line in out.splitlines():
            name = line[3:].strip()
            if " -> " in name:            # переименование: интересен новый путь
                name = name.split(" -> ", 1)[1]
            if name:
                files.add(name)
    # Папка задачи в git не попадает, но в `status` видна: это не работа.
    return {f for f in files if not f.startswith(".orch/")}


def has_work(path: Path | str) -> bool:
    """Есть ли в копии работа, которую страшно потерять.

    Изменения отслеживаемых файлов — да. Неотслеживаемый служебный сор —
    нет: `.orch/` роли пишут сами, и он восстановим.
    """
    out = git(path, "status", "--porcelain")
    for line in out.splitlines():
        name = line[3:].strip().strip('"')
        if line.startswith("??") and name.startswith(JUNK):
            continue
        if line.strip():
            return True
    return False


def create_worktree(project: Path | str, branch: str, base: str = "") -> tuple[Path, str]:
    """Создать рабочую копию задачи. Возвращает (путь, ошибка или '').

    Идемпотентно: готовый каталог с нужной веткой принимается как есть,
    поэтому повтор после падения движка ничего не ломает.
    """
    project = Path(project).resolve()
    path = worktree_path(project, branch)
    if path.is_dir() and (path / ".git").exists():
        return path, ""
    path.parent.mkdir(parents=True, exist_ok=True)
    base = base or default_branch(project)
    if branch_exists(project, branch):
        code, out = git_try(project, "worktree", "add", str(path), branch)
        if code != 0 and "already used by worktree" in out or (
            code != 0 and "already checked out" in out
        ):
            # Ветку держит копия, которую не удалось снять (случается, когда
            # каталог проекта доступен под двумя путями: git сверяет строки и
            # отказывается её убирать). Работы там нет — движок проверил до
            # вызова, — поэтому берём ветку второй копией.
            code, out = git_try(project, "worktree", "add", "--force", str(path), branch)
    else:
        # Ответвляемся от свежей базовой ветки, а не от того, что лежало на
        # диске с прошлой недели: иначе задача начинается в устаревшем коде.
        # Нет сети или нет ремоута — не беда, работаем от локальной.
        if has_remote(project):
            git_try(project, "fetch", "origin", base)
            start = f"origin/{base}" if ref_exists(project, f"refs/remotes/origin/{base}") else base
        else:
            start = base
        code, out = git_try(project, "worktree", "add", str(path), "-b", branch, start)
    if code != 0:
        return path, out
    if (Path(project) / ".gitmodules").exists():
        sub_code, sub_out = git_try(path, "submodule", "update", "--init", "--recursive")
        if sub_code != 0:
            return path, f"подмодули не поднялись: {sub_out}"
    return path, ""


def is_project_root(path: str | Path) -> bool:
    """Корень проекта, а не рабочая копия задачи.

    У копии, сделанной `git worktree add`, `.git` — файл со ссылкой на общий
    каталог, у настоящего корня — каталог. Без этой проверки список проектов
    зарастает копиями прошлых задач: они тоже сессии со своим `project_path`.
    """
    return (Path(path) / ".git").is_dir()


def projects_on_disk(projects_dir: str | Path) -> list[str]:
    """Репозитории первого уровня в каталоге проектов.

    Нужен и мастеру (когда проект ещё не выбран), и панели (строки «завести»).
    Рабочие копии задач (`<repo>-orch`, `<repo>-worktrees`) отсеиваются сами:
    у них `.git` — файл, а не каталог.
    """
    base = Path(str(projects_dir or "")).expanduser()
    if not base.is_dir():
        return []
    try:
        items = sorted(base.iterdir())
    except OSError:
        return []
    return [str(p) for p in items if p.is_dir() and is_project_root(p)]


def has_remote(project: Path | str) -> bool:
    return bool(git(project, "remote"))


def ref_exists(project: Path | str, ref: str) -> bool:
    code, _ = git_try(project, "rev-parse", "--verify", "--quiet", ref)
    return code == 0


def main_worktree(project: Path | str) -> Path:
    """Путь главной копии так, как его записал сам git.

    Один каталог бывает доступен под двумя путями (`/projects/x` и
    `~/projects/x` — это один и тот же каталог), а git сверяет их строкой.
    Команды об удалении копий надо звать оттуда, где путь совпадает с
    записанным, иначе git отвечает «does not point back».
    """
    out = git(project, "worktree", "list", "--porcelain")
    for line in out.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    return Path(project)


def remove_worktree(project: Path | str, path: Path | str) -> str:
    """Убрать рабочую копию задачи. Ветку не трогаем: в ней вся работа."""
    project = Path(project).resolve()
    git_try(project, "worktree", "unlock", str(path))
    code, out = git_try(project, "worktree", "remove", "--force", str(path))
    if code != 0 and "does not point back" in out:
        # Тот же репозиторий, но под путём, который записан у git.
        home = main_worktree(project)
        git_try(home, "worktree", "unlock", str(path))
        code, out = git_try(home, "worktree", "remove", "--force", str(path))
        git_try(home, "worktree", "prune")
        return "" if code == 0 else out
    git_try(project, "worktree", "prune")
    return "" if code == 0 else out


def branch_exists(project: Path | str, branch: str) -> bool:
    code, _ = git_try(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return code == 0


def default_branch(project: Path | str) -> str:
    """Ветка, от которой ответвляются задачи: origin/HEAD, иначе main/master."""
    head = git(project, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[-1]
    for name in ("main", "master"):
        if branch_exists(project, name):
            return name
    return git(project, "rev-parse", "--abbrev-ref", "HEAD") or "main"
