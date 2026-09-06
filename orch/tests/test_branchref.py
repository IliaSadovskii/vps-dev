"""Ссылка владельца → имя ветки."""

from __future__ import annotations

import pytest

from orch.branchref import BranchRefError, parse


@pytest.mark.parametrize(
    "ссылка, ветка",
    [
        ("https://github.com/o/r/tree/feature/x", "feature/x"),
        ("https://github.com/o/r/tree/main", "main"),
        ("https://github.com/o/r/tree/feature/x/", "feature/x"),
        ("  https://github.com/o/r/tree/feature/x  ", "feature/x"),
        ("<https://github.com/o/r/tree/feature/x>", "feature/x"),
        ("https://github.com/o/r/compare/main...feature/x", "feature/x"),
        ("https://github.com/o/r/tree/feature%2Fx", "feature/x"),
        ("feature/x", "feature/x"),
        ("t7-modul", "t7-modul"),
    ],
)
def test_разбирает(ссылка, ветка):
    assert parse(ссылка) == ветка


@pytest.mark.parametrize(
    "плохое, кусок",
    [
        ("", "поле ввода пустое"),
        ("   ", "поле ввода пустое"),
        ("сделай мне красиво", "не похоже на ветку"),
        ("https://github.com/o/r", "не понял, где здесь ветка"),
        ("https://example.com/что-то", "не понял, где здесь ветка"),
    ],
)
def test_объясняет_отказ(плохое, кусок):
    with pytest.raises(BranchRefError) as exc:
        parse(плохое)
    assert кусок in str(exc.value)


def test_ветку_pr_спрашивает_у_github(monkeypatch):
    """Номер PR не говорит об имени ветки ничего — знает только GitHub."""
    import subprocess

    calls = []

    class Out:
        returncode = 0
        stdout = "feature/from-pr\n"
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return Out()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert parse("https://github.com/o/r/pull/4") == "feature/from-pr"
    assert calls and calls[0][:3] == ["gh", "pr", "view"]


def test_молчание_gh_объясняется(monkeypatch):
    import subprocess

    class Out:
        returncode = 1
        stdout = ""
        stderr = "not logged in"

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: Out())
    with pytest.raises(BranchRefError) as exc:
        parse("https://github.com/o/r/pull/4")
    assert "не спросил у GitHub" in str(exc.value) and "not logged in" in str(exc.value)
