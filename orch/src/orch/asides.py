"""Описания побочных ролей: `asides/<имя>.yml` (`ASIDE-PLAN.md` §1).

Роль задаётся файлом, а не кодом движка: движок знает про «побочную роль
вообще», а новая роль появляется вместе с yml и промптами. Правки владельца
живут рядом с базой, заводской файл не трогается — как у цепочек.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .chain import ChainError, _repo_dir
from .db import STATE_DIR

# Что роль вправе делать. Проверяет движок на входе `orch aside`, а не
# промпт: промпт можно уговорить (`ASIDE-PLAN.md` §5).
# `answer` (ответить роли вместо владельца) убрано вместе с Тимлидом:
# ворота стоят там, где владелец боится чужого решения, и подставлять туда
# ещё одного агента на той же модели незачем.
RIGHTS = {"read", "hold", "move", "patch", "pr"}
SCOPES = {"run", "task", "project", "machine"}


class AsideError(ChainError):
    """Кривое описание побочной роли."""


@dataclass(frozen=True)
class Wake:
    """Повод проснуться: события, промпт и чем их разбирать."""

    on: tuple[str, ...]
    prompt: str
    # Имя повода словами: ключи событий (`run_ended`) владельцу ничего не
    # говорят, а держать их перевод в странице значит держать второй список.
    title: str = ""
    agent: str = "claude"
    model: str = "sonnet"
    effort: str | None = None
    # Где идёт ход: `shared` — общая переписка роли (там же владелец с ней
    # разговаривает), `fresh` — своя сессия на один повод. Разбор хода стоит
    # держать отдельно: промпт в занятую сессию AoE отдаёт мосту как `steer`
    # и обрывает то, что там идёт, — движок бил бы по разговору владельца, а
    # реплика владельца по разбору.
    session: str = "shared"
    # Позвать владельца, когда ход этого повода закончится: AoE пришлёт пуш
    # по `Idle`. Для сводки конца прогона — единственного хода, который
    # владелец должен прочитать обязательно.
    attention: bool = False
    # Сколько находок роли по прошлым задачам вклеить в задание. Ставится
    # только там, где роль подводит итог: разбору одного хода чужие прогоны
    # не нужны, а контекст стоят денег каждый ход.
    history: int = 0


@dataclass(frozen=True)
class Aside:
    name: str
    scope: str
    wakes: tuple[Wake, ...]
    # Где роль работает: `task` — копия задачи (только чтение), `none` —
    # всё равно где, `repo:<путь>` — готовый каталог, `worktree:<проект>` —
    # своя рабочая копия проекта, которую движок заведёт сам.
    workspace: str = "task"
    # Вторая копия того же проекта под коммиты: роль правит живое дерево,
    # чтобы правка подействовала на текущий прогон, а коммиты кладёт в свою
    # ветку — в живом дереве лежит незакоммиченная работа владельца, и
    # коммитить там нельзя (`ASIDE-PLAN.md` §7).
    mirror: str = ""
    rights: frozenset[str] = field(default_factory=lambda: frozenset({"read"}))
    includes: tuple[str, ...] = ("common-aside",)   # общие правила побочных ролей
    chains: tuple[str, ...] = ()          # пусто — на всех цепочках
    budget: dict = field(default_factory=dict)
    enabled: bool = False
    title: str = ""
    # Знак роли в титуле сессии: её строка стоит в сайдбаре вперемешку со
    # строками шагов задачи, и глазу нужно за что-то зацепиться.
    icon: str = ""
    source: str = ""

    def kinds(self) -> tuple[str, ...]:
        out: list[str] = []
        for wake in self.wakes:
            out.extend(k for k in wake.on if k not in out)
        return tuple(out)

    def wake_for(self, kind: str) -> Wake | None:
        for wake in self.wakes:
            if kind in wake.on:
                return wake
        return None

    def wake_by_prompt(self, prompt: str) -> Wake | None:
        """Повод по имени промпта: именно его движок пишет в `aside_run.wake`."""
        for wake in self.wakes:
            if wake.prompt == prompt:
                return wake
        return None

    def may(self, right: str) -> bool:
        return right in self.rights

    def fits_chain(self, chain: str | None) -> bool:
        return not self.chains or (chain or "") in self.chains

    def limit(self, key: str, default: int) -> int:
        try:
            return int(self.budget.get(key, default))
        except (TypeError, ValueError):
            return default


def factory_dir() -> Path:
    return _repo_dir() / "asides"


def user_dir() -> Path:
    """Правки владельца: рядом с базой, вне репозитория (как у цепочек)."""
    return STATE_DIR / "asides"


def path_of(name: str) -> Path:
    user = user_dir() / f"{name}.yml"
    return user if user.exists() else factory_dir() / f"{name}.yml"


def is_custom(name: str) -> bool:
    return (user_dir() / f"{name}.yml").exists()


def names() -> list[str]:
    found = {p.stem for p in factory_dir().glob("*.yml")} if factory_dir().is_dir() else set()
    if user_dir().is_dir():
        found |= {p.stem for p in user_dir().glob("*.yml")}
    return sorted(found)


def load(path: Path) -> Aside:
    return parse(path.read_text(encoding="utf-8"), source=str(path))


def load_by_name(name: str) -> Aside:
    return load(path_of(name))


def all_asides() -> list[Aside]:
    out = []
    for name in names():
        try:
            out.append(load_by_name(name))
        except (AsideError, OSError):
            continue
    return out


def enabled() -> list[Aside]:
    return [a for a in all_asides() if a.enabled]


def parse(text: str, source: str = "?") -> Aside:
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise AsideError(f"{source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AsideError(f"{source}: ожидался словарь")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise AsideError(f"{source}: нет имени роли")
    scope = str(raw.get("scope") or "task")
    if scope not in SCOPES:
        raise AsideError(f"{source}: неизвестная область {scope!r}")

    rights = set(raw.get("rights") or ["read"])
    unknown = rights - RIGHTS
    if unknown:
        raise AsideError(f"{source}: неизвестные права {sorted(unknown)}")

    wakes = []
    for item in raw.get("wakes") or []:
        if not isinstance(item, dict):
            raise AsideError(f"{source}: повод должен быть словарём")
        # `on` в YAML 1.1 — это булево `True`, а не строка: `on: [x]`
        # приезжает ключом `True`. Ловим оба написания и разрешаем `when`
        # тем, кому эта ловушка не нравится.
        on = item.get("on", item.get(True, item.get("when")))
        on = [on] if isinstance(on, str) else list(on or [])
        if not on:
            raise AsideError(f"{source}: у повода нет события `on`")
        prompt = str(item.get("prompt") or "")
        if not prompt:
            raise AsideError(f"{source}: у повода {on} нет промпта")
        run = item.get("run") or {}
        session = str(item.get("session") or run.get("session") or "shared")
        if session not in ("shared", "fresh"):
            raise AsideError(f"{source}: повод {on}: непонятная сессия {session!r}")
        wakes.append(
            Wake(
                on=tuple(str(k) for k in on),
                prompt=prompt,
                title=str(item.get("title") or ""),
                agent=str(run.get("agent") or "claude"),
                model=str(run.get("model") or "sonnet"),
                effort=(str(run["effort"]) if run.get("effort") else None),
                session=session,
                attention=bool(item.get("attention")),
                history=int(item.get("history") or 0),
            )
        )
    if not wakes:
        raise AsideError(f"{source}: у роли нет ни одного повода проснуться")

    seen: set[str] = set()
    for wake in wakes:
        for kind in wake.on:
            if kind in seen:
                raise AsideError(f"{source}: событие {kind!r} названо в двух поводах")
            seen.add(kind)

    workspace = str(raw.get("workspace") or "task")
    if workspace not in ("task", "none") and not workspace.startswith(("repo:", "worktree:")):
        raise AsideError(f"{source}: непонятная рабочая копия {workspace!r}")

    return Aside(
        name=name,
        scope=scope,
        wakes=tuple(wakes),
        workspace=workspace,
        mirror=str(raw.get("mirror") or ""),
        rights=frozenset(rights),
        includes=tuple(str(c) for c in (raw.get("includes") or ["common-aside"])),
        chains=tuple(str(c) for c in (raw.get("chains") or [])),
        budget=dict(raw.get("budget") or {}),
        enabled=bool(raw.get("enabled", False)),
        title=str(raw.get("title") or ""),
        icon=str(raw.get("icon") or ""),
        source=source,
    )
