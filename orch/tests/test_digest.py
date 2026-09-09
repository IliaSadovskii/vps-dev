"""Скелет хода: разбор транскрипта агента (`ASIDE-PLAN.md` §8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch import digest as dg


def write(folder: Path, session: str, rows: list[dict]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def assistant(at: str, blocks: list[dict], usage: dict | None = None) -> dict:
    return {
        "type": "assistant",
        "timestamp": at,
        "message": {
            "role": "assistant",
            "model": "claude-opus-5",
            "content": blocks,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5},
        },
    }


def result(at: str, tool_id: str, text: str, bad: bool = False) -> dict:
    return {
        "type": "user",
        "timestamp": at,
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": bad}
            ],
        },
    }


@pytest.fixture
def transcripts(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "transcripts"
    monkeypatch.setattr(dg, "TRANSCRIPTS", root)
    return root


def test_слаг_каталога_из_пути_копии():
    assert dg.project_slug("/home/dev/projects/x") == "-home-dev-projects-x"


def test_обзор_собирает_вызовы_ошибки_и_финал(transcripts, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    write(
        transcripts / dg.project_slug(wt),
        "s1",
        [
            assistant(
                "2026-09-07T10:00:00Z",
                [
                    {"type": "tool_use", "id": "t1", "name": "Bash",
                     "input": {"command": "pytest -q"}},
                    {"type": "tool_use", "id": "t2", "name": "Edit",
                     "input": {"file_path": "/wt/a.py"}},
                ],
            ),
            result("2026-09-07T10:00:05Z", "t1", "2 failed", bad=True),
            result("2026-09-07T10:00:06Z", "t2", "ok"),
            assistant("2026-09-07T10:01:00Z", [{"type": "text", "text": "Готово, тесты зелёные."}]),
        ],
    )

    d = dg.digest(wt)
    assert d["counts"] == {"Bash": 1, "Edit": 1}
    assert d["files"] == ["/wt/a.py"]
    assert d["errors"][0]["tool"] == "Bash" and "2 failed" in d["errors"][0]["text"]
    assert [c["ok"] for c in d["tools"]] == [False, True]
    assert d["final"] == "Готово, тесты зелёные."
    assert d["turns"] == 2 and d["model"] == "claude-opus-5"

    text = dg.render(d)
    assert "Bash × 1" in text and "Готово, тесты зелёные." in text


def test_окно_отсекает_чужие_заходы(transcripts, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    write(
        transcripts / dg.project_slug(wt),
        "s1",
        [
            assistant("2026-09-07T09:00:00Z",
                      [{"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/x"}}]),
            assistant("2026-09-07T12:00:00Z",
                      [{"type": "tool_use", "id": "b", "name": "Write", "input": {"file_path": "/y"}}]),
        ],
    )
    d = dg.digest(wt, since="2026-09-07T11:00:00Z")
    assert d["counts"] == {"Write": 1} and d["files"] == ["/y"]


def test_вопрос_владельцу_попадает_в_обзор(transcripts, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    write(
        transcripts / dg.project_slug(wt),
        "s1",
        [
            assistant(
                "2026-09-07T10:00:00Z",
                [{"type": "tool_use", "id": "q", "name": "AskUserQuestion",
                  "input": {"questions": [{"question": "Какую базу берём?"}]}}],
            )
        ],
    )
    assert dg.digest(wt)["questions"] == ["Какую базу берём?"]


def test_недописанная_строка_живого_файла_не_ломает_разбор(transcripts, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    folder = transcripts / dg.project_slug(wt)
    path = write(folder, "s1", [assistant("2026-09-07T10:00:00Z", [{"type": "text", "text": "жив"}])])
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"type": "assis')
    assert dg.digest(wt)["final"] == "жив"


def test_нет_транскриптов_обзор_пустой(transcripts, tmp_path):
    wt = tmp_path / "нет"
    d = dg.digest(wt)
    assert d["turns"] == 0 and d["tools"] == [] and d["final"] == ""


def test_названная_сессия_читается_одна(transcripts, tmp_path):
    """В одной копии живут сессия шага и разговор владельца с прошлой ролью.

    Пока `session` не сужал выборку, чужие вызовы приезжали в скелет хода и
    роль выглядела нарушителем чужих правил (T26, прогон 125).
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    папка = transcripts / dg.project_slug(wt)
    write(папка, "своя", [
        assistant("2026-09-07T10:00:00Z",
                  [{"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/своё"}}]),
    ])
    write(папка, "чужая", [
        assistant("2026-09-07T10:00:30Z",
                  [{"type": "tool_use", "id": "b", "name": "Edit", "input": {"file_path": "/чужое"}}]),
    ])

    свой = dg.digest(wt, session="своя")
    цели = [t.get("target") for t in свой["tools"]]
    assert "/своё" in цели and "/чужое" not in цели

    # Без имени сессии берётся всё, что попало в окно, — как раньше.
    оба = dg.digest(wt)
    assert len(оба["tools"]) == 2

    # Файла с таким именем нет — обзор пустой, а не «всё, что нашлось».
    пусто = dg.digest(wt, session="потерялась")
    assert not пусто["tools"] and not пусто["turns"]
