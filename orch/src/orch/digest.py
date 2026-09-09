"""Скелет хода: сжатый обзор транскрипта агента.

Побочные роли (`ASIDE-PLAN.md` §8) разбирают чужой ход. Сырой транскрипт для
этого не годится: у шага реализации это сотни тысяч токенов, и половина из
них — вывод инструментов, который роли не нужен. Модуль читает `jsonl`,
который агент пишет сам, и отдаёт короткий обзор: что вызывалось, что
упало, какие файлы тронуты, о чём спрашивали владельца, чем ход кончился.

Зависимостей от движка нет намеренно: это чистая функция от файла, её
удобно проверять на образцах и звать откуда угодно.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Куда Claude Code пишет транскрипты: каталог на рабочую копию, файл на
# сессию. Через API AoE переписку не прочесть (`research/AOE-CAPABILITIES.md`),
# поэтому берём с диска.
TRANSCRIPTS = Path.home() / ".claude" / "projects"

# Сколько вызовов инструментов оставляем в обзоре. Ход, где их больше,
# читается не поштучно, а по счётчикам и ошибкам.
MAX_TOOLS = 120
MAX_TEXT = 400

# Из чего складывается «цель» вызова: первый ключ, который нашёлся.
TARGET_KEYS = ("command", "file_path", "path", "pattern", "url", "prompt", "query")
# Инструменты, меняющие файлы: по ним собирается список тронутого.
WRITERS = ("Edit", "Write", "NotebookEdit", "MultiEdit")


def project_slug(worktree: Path | str) -> str:
    """Имя каталога транскриптов для рабочей копии: `/home/dev/x` → `-home-dev-x`."""
    return str(Path(worktree).resolve()).replace("/", "-")


def transcripts_of(worktree: Path | str) -> list[Path]:
    """Файлы транскриптов этой рабочей копии, свежие первыми."""
    folder = TRANSCRIPTS / project_slug(worktree)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def digest(
    worktree: Path | str,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    session: str | None = None,
    max_tools: int = MAX_TOOLS,
) -> dict:
    """Обзор хода в рабочей копии за окно `since … until`.

    `session` — uuid сессии агента, он же имя файла (`run.acp_session_id`,
    движок берёт его у AoE событием `AcpSessionAssigned`). Названа сессия —
    читается только её файл: в одной рабочей копии одновременно живут
    сессия шага и разговор владельца с прошлой ролью, и склейка выдавала
    чужие вызовы за вызовы разбираемого хода (T26, прогон 125). Файла нет —
    обзор пустой, а не «всё, что нашлось».
    """
    lo = since if isinstance(since, datetime) else parse_time(since)
    hi = until if isinstance(until, datetime) else parse_time(until)

    files = transcripts_of(worktree)
    if session:
        files = [p for p in files if p.stem == session]

    rows: list[dict] = []
    for path in files:
        for row in _read(path):
            at = parse_time(row.get("timestamp"))
            if lo and (at is None or at < lo):
                continue
            if hi and at is not None and at > hi:
                continue
            rows.append(row)
    rows.sort(key=lambda r: r.get("timestamp") or "")
    return _fold(rows, max_tools)


def _read(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Последняя строка живого файла бывает недописанной: ход идёт.
            continue
    return out


def _fold(rows: list[dict], max_tools: int) -> dict:
    calls: dict[str, dict] = {}          # tool_use_id → вызов
    order: list[str] = []
    counts: dict[str, int] = {}
    files: set[str] = set()
    errors: list[dict] = []
    questions: list[str] = []
    final = ""
    turns = 0
    tokens = {"in": 0, "out": 0, "cache_read": 0}
    model = ""
    started = ended = None

    for row in rows:
        kind = row.get("type")
        at = row.get("timestamp")
        if at:
            started = started or at
            ended = at
        message = row.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        content = content if isinstance(content, list) else []

        if kind == "assistant":
            turns += 1
            model = message.get("model") or model
            usage = message.get("usage") or {}
            tokens["in"] += int(usage.get("input_tokens") or 0)
            tokens["out"] += int(usage.get("output_tokens") or 0)
            tokens["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
            for block in content:
                if block.get("type") == "text" and block.get("text", "").strip():
                    final = block["text"].strip()
                elif block.get("type") == "tool_use":
                    name = block.get("name") or "?"
                    counts[name] = counts.get(name, 0) + 1
                    call = {
                        "name": name,
                        "target": _target(block.get("input") or {}),
                        "ok": None,
                        "at": at,
                    }
                    calls[str(block.get("id"))] = call
                    order.append(str(block.get("id")))
                    if name in WRITERS:
                        target = (block.get("input") or {}).get("file_path")
                        if target:
                            files.add(str(target))
                    if name == "AskUserQuestion":
                        questions.extend(_questions(block.get("input") or {}))
        elif kind == "user":
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                call = calls.get(str(block.get("tool_use_id")))
                bad = bool(block.get("is_error"))
                if call is not None:
                    call["ok"] = not bad
                if bad:
                    errors.append(
                        {
                            "tool": call["name"] if call else "?",
                            "target": call["target"] if call else "",
                            "text": _flat(block.get("content"))[:MAX_TEXT],
                        }
                    )

    tools = [calls[i] for i in order if i in calls]
    cut = max(0, len(tools) - max_tools)
    return {
        "turns": turns,
        "model": model,
        "started_at": started,
        "ended_at": ended,
        "tokens": tokens,
        "counts": counts,
        "tools": tools[-max_tools:] if max_tools else [],
        "tools_dropped": cut,
        "files": sorted(files),
        "errors": errors,
        "questions": questions,
        "final": final[:2000],
    }


def _target(payload: dict) -> str:
    for key in TARGET_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")[:160]
    return ""


def _questions(payload: dict) -> list[str]:
    out = []
    for item in payload.get("questions") or []:
        if isinstance(item, dict) and item.get("question"):
            out.append(str(item["question"])[:MAX_TEXT])
    return out


def _flat(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict)]
        return " ".join(p for p in parts if p)
    return ""


def render(data: dict) -> str:
    """Обзор в виде markdown — то, что кладётся в промпт побочной роли."""
    lines = ["## Скелет хода", ""]
    counts = ", ".join(f"{k} × {v}" for k, v in sorted(data["counts"].items()))
    lines.append(f"**Ходов модели.** {data['turns']}, модель `{data['model'] or '?'}`.")
    lines.append(f"**Инструменты.** {counts or 'не вызывались'}.")
    if data["files"]:
        lines.append("**Тронутые файлы.** " + ", ".join(f"`{f}`" for f in data["files"]))
    if data["errors"]:
        lines.append("")
        lines.append("**Ошибки инструментов**")
        for item in data["errors"][:20]:
            lines.append(f"- `{item['tool']}` {item['target']}: {item['text'][:200]}")
    if data["questions"]:
        lines.append("")
        lines.append("**Спрашивал владельца**")
        lines.extend(f"- {q}" for q in data["questions"])
    if data["tools"]:
        lines.append("")
        lines.append("**Вызовы по порядку**")
        if data["tools_dropped"]:
            lines.append(f"_(первые {data['tools_dropped']} опущены)_")
        for call in data["tools"]:
            mark = {True: "ok", False: "ошибка", None: "—"}[call["ok"]]
            lines.append(f"- `{call['name']}` {call['target']} → {mark}")
    if data["final"]:
        lines.append("")
        lines.append("**Чем кончил**")
        lines.append("")
        lines.append(data["final"])
    return "\n".join(lines)
