"""Сборка промпта шага: чистая функция (цепочка, шаг, состояние, файлы) → текст.

Порядок блоков — `PLAN.md` §7. Собранный текст сохраняется в
`.orch/<task>/prompts/<step>-<n>.md` до отправки, хеш — в `run.prompt_sha`.
Из чужих артефактов сюда попадают только пути и раздел `## Итог`, никогда
произвольный текст (`PLAN.md` §13, вопрос 19).
"""

from __future__ import annotations

import re
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
    stand_name: str = ""
    # Копилка проекта: что прошлые задачи решили и что отвергли. Без неё
    # каждый шаг начинает с чистой памятью и переоткрывает те же грабли.
    branch: str = ""
    base_branch: str = ""
    start_sha: str = ""
    # Общие файлы сверх цепочки: движок добавляет их по состоянию задачи.
    extra_includes: list[str] = field(default_factory=list)
    # Ворота листа автономии: True — встаёт на любом исходе, список — только
    # на этих, False — не встаёт.
    gate_after: bool | list[str] = False
    oversized: bool = False


def build(ctx: Context) -> str:
    head = [
        _includes(ctx),
        _role(ctx),
        _instructions(ctx),
        _task(ctx),
        _where(ctx),
    ]
    files_at = len(head)          # индекс блока файлов: он один пересобирается
    parts = [*head, _files(ctx, inline=True), _comments(ctx), _questions(ctx), _finish(ctx)]
    parts = [_drop_empty_files(p) for p in parts]
    text = "\n\n".join(p for p in parts if p).strip() + "\n"
    if len(text) / CHARS_PER_TOKEN <= TOKEN_LIMIT:
        return text
    # Слишком тяжёлый промпт: файлы остаются путями, содержание роль читает сама.
    ctx.oversized = True
    parts[files_at] = _files(ctx, inline=False)
    return "\n\n".join(p for p in parts if p).strip() + "\n"


def _drop_empty_files(part: str) -> str:
    """Рубрика «Файлы», в которой не оказалось ни строки, не нужна вовсе."""
    return "" if part.strip() == "## Файлы" else part


# ── блоки ────────────────────────────────────────────────────────────────
def _includes(ctx: Context) -> str:
    """Общие правила: цепочки, шага и добавленные движком по состоянию.

    Порядок постоянный, повторов нет: один и тот же файл, названный дважды,
    вклеивается один раз.
    """
    texts = []
    seen: set[str] = set()
    names = [*ctx.chain.includes, *ctx.step.includes, *ctx.extra_includes]
    for name in names:
        if name in seen:
            continue
        seen.add(name)
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
    if ctx.branch:
        base = f", база `{ctx.base_branch}`" if ctx.base_branch else ""
        lines.append(f"Ветка задачи `{ctx.branch}`{base}.")
    if ctx.start_sha:
        # Границу работы задачи роли иначе не узнать: в ветке лежит и то, что
        # было до задачи. Ревью кода, скрипт владения тестами и PR считают
        # дифф именно отсюда.
        lines.append(
            f"Работа задачи начинается с коммита `{ctx.start_sha}` — это стартовый "
            "коммит задачи: всё, что после него, сделано в этой задаче, всё, что "
            "до, существовало раньше."
        )
    lines.append(
        f"Логи команд — `{ctx.task_dir / 'logs'}`, свой файл пиши в "
        f"`{ctx.task_dir / 'artifacts'}`."
    )
    if ctx.stand_name:
        # Порты стенда задачи выдаёт `ports`, а не роль: номера проекта заняты
        # постоянным стендом владельца, и брать их на глаз нельзя.
        lines.append(
            f"Стенд задачи поднимается так: `ports run {ctx.stand_name} -- docker compose up -d`; "
            f"порты покажет `ports which {ctx.stand_name}`. Гасит его движок при закрытии задачи."
        )
    if ctx.run_n >= ctx.step.max_runs:
        lines.append(
            f"Это последний допустимый заход в этот шаг (предел {ctx.step.max_runs}). "
            "Дальше задача встанет и будет ждать владельца."
        )
    return "\n".join(lines)


def _files(ctx: Context, inline: bool) -> str:
    """Файлы шага. Пустую рубрику не выводим: заголовок без содержания
    читается как «что-то потеряли» (наблюдение прогона T16)."""
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
            # Вклеивается только `## Итог`: чужой файл целиком — это ещё и
            # инъекция через артефакт (`PLAN.md` §13, вопрос 19). Но молчать
            # об этом нельзя: роль Плана на T37 прочла 24 строки из 337 и не
            # знала, что «Правила проекта» и «Тесты и проверки» остались в
            # файле. Поэтому здесь сказано, что вклеено и что осталось.
            summary = _summary(path)
            rest = _other_headings(path)
            if summary:
                lines.append("")
                lines.append(_indent(summary))
                lines.append("")
                if rest:
                    lines.append(
                        "  Выше — только первый раздел файла. Остальное в нём: "
                        + ", ".join(f"`{h}`" for h in rest)
                        + " — открой файл и читай нужные разделы, по памяти о "
                        "вклейке их не восстановить."
                    )
                    lines.append("")
            else:
                lines.append(
                    "  Содержание не вклеено: у файла нет раздела `## Итог`. "
                    "Открой его сама."
                )
                lines.append("")
    if missing:
        lines.append("")
        lines.append(
            "Этих файлов нет: роль, которая их пишет, ещё не ходила, шаг "
            "пропущен или задача начата с середины. Строку об этом в "
            "`## Допущения`, работай от кода и текста задачи: "
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
            same = (
                "Это тот же разговор, что и в прошлый заход: что ты решала и почему, "
                "ты помнишь. "
                if ctx.step.context == "own"
                else ""
            )
            lines.append(
                same + "Твой файл с прошлого захода — перепиши его, новый не заводи: "
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
        lines.append(
            f"Файл `{name}` изменился после того, как его роль сдала ход: "
            "правил владелец или сама роль в разговоре на воротах. Читай его "
            "заново, а не по памяти о прошлом заходе."
        )
    # Путь к навыкам называем только когда навыки есть: иначе роль получает
    # дорогу в репозиторий самого оркестратора и ходит туда без нужды
    # (наблюдение прогона Conventions, `PROMPT-NOTES.md`).
    skills = [p for p in sorted(prompts_dir().glob("skill-*.md")) if _reads_skill(p, ctx.step.id)]
    if skills:
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
    gate = ctx.gate_after
    if gate is True:
        lines.append("После твоего хода задача встанет и будет ждать владельца.")
    elif not gate:
        # Молчание тут читалось ролью как «ворота на месте»: промпты писаны от
        # заводской цепочки, где они стоят, а пресет `auto` их гасит. Решение
        # кончило ход разделом «что решаем мы» — и он уехал в План непрочитанным
        # (прогон T35).
        lines.append(
            "После твоего хода задача не встанет: следующий шаг начнётся сразу, "
            "и твой файл владелец увидит не раньше конца прогона. Всё, что ты "
            "оставила бы ему на воротах, реши в этом ходе сама и запиши в файл."
        )
    else:
        named = ", ".join(f"`{o}`" for o in gate)
        rest = [o for o in step.outcomes if o not in set(gate)]
        tail = (
            " Остальные исходы (" + ", ".join(f"`{o}`" for o in rest) + ") владельца "
            "не останавливают."
            if rest
            else ""
        )
        lines.append(f"Задача встанет и будет ждать владельца на исходе {named}.{tail}")
    if gate:
        # Строка про правки после остановки — только тем, у кого остановка
        # есть: после «задача не встанет» она читалась как противоречие, и
        # роль без ворот ждала разговора, которого не будет.
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


def _other_headings(path: Path) -> list[str]:
    """Заголовки `## …` файла, кроме вклеенного: что роль ещё не видела."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        line.strip()
        for line in text.splitlines()
        if line.startswith("## ") and line.strip() not in SUMMARY_HEADINGS
    ]


def _reads_skill(path: Path, step_id: str) -> bool:
    """Навык называет своих читателей первой строкой: `Читают шаги: a, b`.

    Раздавать навыки всем подряд нельзя: путь к ним ведёт в репозиторий
    оркестратора, и роль, которой навык не нужен, уходит туда читать
    (`PROMPT-NOTES.md`, прогон Conventions).
    """
    try:
        head = path.read_text(encoding="utf-8")[:400]
    except OSError:
        return False
    m = re.search(r"Читают шаги:([^.\n]*)", head)
    if not m:
        return False
    return step_id in re.findall(r"[a-z][a-z0-9-]*", m.group(1))


def _indent(text: str) -> str:
    return "\n".join("  " + line if line else "" for line in text.splitlines())


def came_from_phrase(
    kind: str, detail: str = "", has_comment: bool = True, detail_files: str = ""
) -> str:
    """Одна из трёх фраз, откуда роль сюда попала (`PLAN.md` §7 п. 5).

    Кнопка панели комментария не несёт: поля ввода у панели нет, комментарий
    доезжает только через `orch gate --comment` или `orch task move`. Обещать
    комментарий, которого нет, нельзя — роль пойдёт его искать.
    """
    if kind == "human":
        if not has_comment:
            return (
                "Сюда тебя вернул владелец кнопкой, без комментария: он читал "
                "файлы и решил, что работа у тебя. Что не так — ищи в файле "
                "шага, с которого он вернул, и в своём прошлом файле; не "
                "уверена — спроси его."
            )
        return "Сюда тебя вернул владелец с комментарием — он ниже."
    if kind == "role":
        where = f" ({detail_files})" if detail_files else ""
        return (
            f"Сюда задачу вернула роль {detail} — её файл{where} и есть твоя "
            "работа, читай его первым."
        )
    if kind == "again":
        return (
            "Владелец нажал «ещё заход» / «продолжай»: продолжи с места "
            "остановки, что мешало — в `## Не решено`."
        )
    return ""
