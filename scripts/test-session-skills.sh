#!/usr/bin/env bash
# Раскладка скиллов (roles/session/files/session-skills) на выдуманном
# доме: переезд ссылки в каталог, скиллы Paseo и Claude Code, повтор без
# изменений, удаление нашего скилла, чужое с нашим именем. И список
# session_skills в defaults роли сходится с session/skills в git.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tool="$root/ansible/roles/session/files/session-skills"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
me="$(id -un)"
bad=0

fail() { echo "  ✖ $*"; bad=1; }
expect() { # expect ОПИСАНИЕ команда…
    local what=$1; shift
    "$@" || fail "$what"
}
run() { "$tool" --owner "$me" "$@"; }

# Источник: наши записи и образец.
src="$tmp/src"
mkdir -p "$src/skills/ours-a" "$src/skills/ours-b" "$src/sample/docs"
echo a > "$src/skills/ours-a/SKILL.md"
echo b > "$src/skills/ours-b/SKILL.md"
echo f > "$src/skills/FORMAT.md"
echo s > "$src/sample/AGENTS.md"

# Клон по-старому: в нём наши скиллы (старой версии) и чужие записи.
clone="$tmp/clone/session/skills"
mkdir -p "$clone/ours-a" "$clone/paseo-x" "$clone/synced/b/pdf" "$clone/.trash/1/x" "$clone/mine"
echo old > "$clone/ours-a/SKILL.md"
echo p > "$clone/paseo-x/SKILL.md"
echo '{"version":1,"files":{}}' > "$clone/paseo-x/.paseo-managed-files.json"
echo pdf > "$clone/synced/b/pdf/SKILL.md"
echo t > "$clone/.trash/1/x/SKILL.md"
echo m > "$clone/mine/SKILL.md"

home="$tmp/home"
mkdir -p "$home/.claude" "$home/.agents"
ln -s "$clone" "$home/.claude/skills"
ln -s "$clone" "$home/.agents/skills"

out="$(run --dry-run --carry all "$src" "$home/.claude/skills")"
expect "проверка: ссылка осталась ссылкой" test -L "$home/.claude/skills"
expect "проверка: обещан переезд" grep -q '^будет: .*была ссылка' <<<"$out"

run --carry all "$src" "$home/.claude/skills" >/dev/null
run --carry paseo "$src" "$home/.agents/skills" >/dev/null

c="$home/.claude/skills" a="$home/.agents/skills"
for d in "$c" "$a"; do
    expect "$d: каталог, не ссылка" test -d "$d" -a ! -L "$d"
    expect "$d: наш скилл новой версии" grep -qx a "$d/ours-a/SKILL.md"
    expect "$d: наш файл" test -f "$d/FORMAT.md"
    expect "$d: скилл Paseo перенесён" test -f "$d/paseo-x/.paseo-managed-files.json"
    expect "$d: образец рядом" test -f "$d/../sample/AGENTS.md"
    expect "$d: список наших" grep -qx '../sample' "$d/.vps-dev-skills"
done
expect "claude: synced перенесён" test -f "$c/synced/b/pdf/SKILL.md"
expect "claude: .trash перенесён" test -d "$c/.trash/1"
expect "claude: своё перенесено" test -f "$c/mine/SKILL.md"
expect "agents: synced не перенесён" test ! -e "$a/synced"
expect "agents: своё не перенесено (только Paseo)" test ! -e "$a/mine"
expect "клон не тронут" grep -qx old "$clone/ours-a/SKILL.md"
expect "клон: Paseo на месте" test -d "$clone/paseo-x"

# Повтор — без изменений.
out="$(run --carry all "$src" "$c")"
if grep -q '^изменено:' <<<"$out"; then fail "повтор что-то изменил: $out"; fi

# Paseo обновил свой скилл, Claude Code — synced: повтор их не трогает.
echo p2 > "$c/paseo-x/SKILL.md"
out="$(run --carry all "$src" "$c")"
expect "Paseo: правка цела" grep -qx p2 "$c/paseo-x/SKILL.md"
if grep -q '^изменено:' <<<"$out"; then fail "чужая правка засчитана изменением: $out"; fi

# Файл в нашем скилле правили на машине — выкатка возвращает репозиторий.
echo local >> "$c/ours-a/SKILL.md"
echo extra > "$c/ours-a/stale.md"
run --carry all "$src" "$c" >/dev/null
expect "наш скилл — как в репозитории" grep -qx a "$c/ours-a/SKILL.md"
expect "лишний файл в нашем скилле убран" test ! -e "$c/ours-a/stale.md"

# Скилл убрали из репозитория — выкатка убирает его с машины.
rm -rf "$src/skills/ours-b"
out="$(run --carry all "$src" "$c")"
expect "убранный скилл удалён" test ! -e "$c/ours-b"
expect "об удалении сказано" grep -q '^изменено: .*ours-b — удалён' <<<"$out"
expect "Paseo после удаления цел" test -d "$c/paseo-x"
if grep -qx ours-b "$c/.vps-dev-skills"; then fail "убранный остался в списке"; fi

# Чужая запись с именем нашего нового скилла — откладывается, не стирается.
mkdir -p "$src/skills/ours-c" "$c/ours-c"
echo c > "$src/skills/ours-c/SKILL.md"
echo foreign > "$c/ours-c/SKILL.md"
run --carry all "$src" "$c" >/dev/null
expect "наш ours-c разложен" grep -qx c "$c/ours-c/SKILL.md"
expect "чужой ours-c отложен" grep -qx foreign "$c.before-session/ours-c/SKILL.md"

# Список подделан — чужое по нему не удаляется.
printf '%s\n' '../../etc' 'a/b' 'paseo-x/..' >> "$c/.vps-dev-skills"
run --carry all "$src" "$c" >/dev/null
expect "подделанный список: Paseo цел" test -d "$c/paseo-x"

# Свежая машина: каталога нет.
fresh="$tmp/fresh/.claude/skills"
mkdir -p "$(dirname "$fresh")"
run --carry all "$src" "$fresh" >/dev/null
expect "свежая: скилл разложен" test -f "$fresh/ours-a/SKILL.md"

# Список в defaults роли = верхний уровень session/skills в git.
want="$(git -C "$root" ls-files session/skills | cut -d/ -f3 | sort -u)"
have="$(sed -n '/^session_skills:/,/^[^ ]/p' "$root/ansible/roles/session/defaults/main.yml" \
    | sed -n 's/^  - //p' | sort -u)"
if [ "$want" != "$have" ]; then
    fail "session_skills в defaults роли не совпадает с session/skills в git:"
    diff <(echo "$want") <(echo "$have") | sed 's/^/      /' || true
fi

[ "$bad" = 0 ] && echo "  ✔ раскладка скиллов: примеры сходятся"
exit "$bad"
