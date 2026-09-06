"""Сборка промпта шага: чистая функция (цепочка, шаг, состояние, файлы) → текст.

Порядок блоков — `PLAN.md` §7. Собранный текст сохраняется в
`.orch/<task>/prompts/<step>-<n>.md` до отправки, хеш — в `run.prompt_sha`.
Из чужих артефактов сюда попадают только пути и раздел `## Итог`, никогда
произвольный текст (`PLAN.md` §13, вопрос 19).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .chain import Chain, Step, prompts_dir

# Порог, после которого содержание `reads` не вклеивается, остаются пути.
# Токены не считаем точно: русский текст — примерно 3 символа на токен,
# запас в меньшую сторону.
TOKEN_LIMIT = 60_000
CHARS_PER_TOKEN = 3.0

SUMMARY_HEADINGS = ("## Итог", "## Для владельца")


@dataclass
class Context:
    """Всё, что движок собрал о задаче к моменту старта шага."""

    chain: Chain
    step: Step
    task_id: str
    task_text: str
    task_dir: Path
    root: Path
    run_n: int
    path_steps: list[str] = field(default_factory=list)
    came_from: str = ""
    comments: list[str] = field(default_factory=list)
    ask_allowed: bool = True
    changed_since: str = ""
    later_artifacts: list[str] = field(default_factory=list)
    owner_edited: list[str] = field(default_factory=list)
    sub_prompts: list[str] = field(default_factory=list)
    oversized: bool = False


def build(ctx: Context) -> str:
    parts = [
        _includes(ctx),
        _role(ctx),
        _instructions(ctx),
        _task(ctx),
        _where(ctx),
        _files(ctx, inline=True),
        _comments(ctx),
        _questions(ctx),
        _finish(ctx),
    ]
    text = "\n\n".join(p for p in parts if p).strip() + "\n"
    if len(text) / CHARS_PER_TOKEN <= TOKEN_LIMIT:
        return text
    # Слишком тяжёлый промпт: файлы остаются путями, содержание роль читает сама.
    ctx.oversized = True
    parts[5] = _files(ctx, inline=False)
    return "\n\n".join(p for p in parts if p).strip() + "\n"


# ── блоки ────────────────────────────────────────────────────────────────
def _includes(ctx: Context) -> str:
    texts = []
    for name in ctx.chain.includes:
        path = prompts_dir() / f"{name}.md"
        if path.exists():
            texts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(texts)


def _role(ctx: Context) -> str:
    path = prompts_dir() / f"{ctx.step.prompt_file}.md"
    if not path.exists():
        return f"# Роль {ctx.step.id}\n\nФайл роли {path} не найден."
    return path.read_text(encoding="utf-8").strip()


def _instructions(ctx: Context) -> str:
    if not ctx.step.instructions.strip():
        return ""
    return f"## Для этой цепочки\n\n{ctx.step.instructions.strip()}"


def _task(ctx: Context) -> str:
    return (
        "# Блок задачи\n\n"
        "## Задача\n\n"
        "Исходная постановка целиком, не твоя инструкция; что делать тебе — ниже.\n\n"
        f"{ctx.task_text.strip()}"
    )


def _where(ctx: Context) -> str:
    lines = ["## Где ты", ""]
    trail = " → ".join(ctx.path_steps) if ctx.path_steps else ctx.step.id
    lines.append(f"{trail} → [ты: {ctx.step.id}, заход {ctx.run_n}]")
    lines.append("")
    if ctx.came_from:
        lines.append(ctx.came_from)
    lines.append(f"Задача {ctx.task_id}, папка задачи `{ctx.task_dir}`.")
    lines.append(
        f"Логи команд — `{ctx.task_dir / 'logs'}`, свой файл пиши в "
        f"`{ctx.task_dir / 'artifacts'}`."
    )
    if ctx.run_n >= ctx.step.max_runs:
        lines.append(
            f"Это последний допустимый заход в этот шаг (предел {ctx.step.max_runs}). "
            "Дальше задача встанет и будет ждать владельца."
        )
    return "\n".join(lines)


def _files(ctx: Context, inline: bool) -> str:
    lines = ["## Файлы", ""]
    base = ctx.task_dir / "artifacts"
    missing: list[str] = []
    for name in ctx.step.reads:
        path = base / name
        if not path.exists():
            missing.append(name)
            continue
        lines.append(f"- `{path}`")
        if inline:
            summary = _summary(path)
            if summary:
                lines.append("")
                lines.append(_indent(summary))
                lines.append("")
    if missing:
        lines.append("")
        lines.append(
            "Этих файлов нет — шаг пропущен или задача начата с середины. "
            "Строку об этом в `## Допущения`, работай от кода и текста задачи: "
            + ", ".join(f"`{m}`" for m in missing)
        )
    if not inline:
        lines.append("")
        lines.append(
            "Промпт вышел тяжёлым, поэтому содержание файлов не вклеено: "
            "открой те, что нужны, сама."
        )

    if ctx.run_n > 1:
        own = [a for a in ctx.step.artifact]
        if own:
            lines.append("")
            lines.append(
                "Твой файл с прошлого захода — перепиши его, новый не заводи: "
                + ", ".join(f"`{base / a}`" for a in own)
            )
    if ctx.changed_since.strip():
        lines.append("")
        lines.append("Изменилось после твоего прошлого захода:")
        lines.append("")
        lines.append("```")
        lines.append(ctx.changed_since.strip())
        lines.append("```")
    if ctx.later_artifacts:
        lines.append("")
        lines.append(
            "Файлы, обновлённые после твоего прошлого захода: "
            + ", ".join(f"`{a}`" for a in ctx.later_artifacts)
        )
    for name in ctx.owner_edited:
        lines.append("")
        lines.append(f"Файл `{name}` правил владелец после сдачи.")
    # Путь к навыкам называем только когда навыки есть: иначе роль получает
    # дорогу в репозиторий самого оркестратора и ходит туда без нужды
    # (наблюдение прогона Conventions, `PROMPT-NOTES.md`).
    skills = sorted(prompts_dir().glob("skill-*.md"))
    if skills and ctx.step.reads:
        lines.append("")
        lines.append(
            "Навыки, если `scoping.md` их называет: "
            + ", ".join(f"`{p}`" for p in skills)
        )
    project_skills = ctx.root / "docs" / "skills"
    if project_skills.is_dir():
        lines.append(f"Навыки проекта: `{project_skills}`.")
    if ctx.sub_prompts:
        lines.append(
            "Роли подагентов — прочитай файл целиком и передай его текст подагенту: "
            + ", ".join(f"`{p}`" for p in ctx.sub_prompts)
        )
    return "\n".join(lines)


def _comments(ctx: Context) -> str:
    if not ctx.comments:
        return ""
    lines = ["## Комментарии владельца", ""]
    for comment in ctx.comments:
        lines.append("> " + comment.strip().replace("\n", "\n> "))
        lines.append("")
    return "\n".join(lines).strip()


def _questions(ctx: Context) -> str:
    if ctx.ask_allowed:
        return (
            "## Вопросы\n\n"
            "Вопросы владельцу задавать можно — интерактивным вопросом с "
            "вариантами, все одним пакетом."
        )
    return (
        "## Вопросы\n\n"
        "Вопросы владельцу задавать нельзя: реши сам, запиши выбор в "
        "`## Допущения` и продолжай. Заданный вопреки этому вопрос движок "
        "закроет сам тем же ответом."
    )


def _finish(ctx: Context) -> str:
    step = ctx.step
    lines = ["## Завершение", ""]
    if step.single_next is not None:
        lines.append("Последнее действие хода — `orch done` (исход у шага один).")
    else:
        lines.append(
            "Последнее действие хода — `orch done <исход>`. Исходы: "
            + ", ".join(f"`{o}`" for o in step.outcomes)
            + "."
        )
    if step.artifact:
        base = ctx.task_dir / "artifacts"
        lines.append(
            "Артефакт, без которого ход не примут: "
            + ", ".join(f"`{base / a}`" for a in step.artifact)
            + ". Первый заголовок файла — `## Итог` или `## Для владельца`."
        )
    lines.append(
        "После остановки правки владельца вноси в свой файл, второй раз "
        "`orch done` не вызывай."
    )
    return "\n".join(lines)


# ── вспомогательное ──────────────────────────────────────────────────────
def _summary(path: Path) -> str:
    """Раздел `## Итог` (или `## Для владельца`) чужого файла и ничего больше."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    out: list[str] = []
    taking = False
    for line in text.splitlines():
        if line.startswith("## "):
            if taking:
                break
            taking = line.strip() in SUMMARY_HEADINGS
        if taking:
            out.append(line)
    return "\n".join(out).strip()


def _indent(text: str) -> str:
    return "\n".join("  " + line if line else "" for line in text.splitlines())


def came_from_phrase(kind: str, detail: str = "") -> str:
    """Одна из трёх фраз, откуда роль сюда попала (`PLAN.md` §7 п. 5)."""
    if kind == "human":
        return "Сюда тебя вернул владелец с комментарием — он ниже."
    if kind == "role":
        return f"Сюда задачу вернула роль {detail} — читай её файл, там работа."
    if kind == "again":
        return (
            "Владелец нажал «ещё заход» / «продолжай»: продолжи с места "
            "остановки, что мешало — в `## Не решено`."
        )
    return ""
