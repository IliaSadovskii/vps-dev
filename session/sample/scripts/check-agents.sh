#!/usr/bin/env bash
#
# Сторож AGENTS.md: размер и образцы каркаса.
#
# Ловит: файл длиннее предела; путь в колонке «Образец» таблицы «## Каркас»,
# которого нет в репозитории; путь, спрятанный в колонке «Правило»;
# отсутствующую или пустую таблицу.
# Не ловит: устаревший смысл строки, дубли, пути в других разделах,
# «—» при уже существующем коде — это видит владелец в диффе.
#
# Запуск из корня репозитория: scripts/check-agents.sh [AGENTS.md]
# Предел строк: переменная AGENTS_LIMIT, по умолчанию 200.

set -euo pipefail

FILE="${1:-AGENTS.md}"
LIMIT="${AGENTS_LIMIT:-200}"
status=0

[ -f "$FILE" ] || { echo "✖ нет файла $FILE" >&2; exit 1; }

lines=$(wc -l < "$FILE")
if [ "$lines" -gt "$LIMIT" ]; then
    echo "✖ $FILE: $lines строк, предел $LIMIT" >&2
    status=1
fi

# Строки таблицы под «## Каркас» до следующего заголовка, без шапки и разделителя.
rows=$(awk '
    /^## /            { in_section = ($0 ~ /^## Каркас/); next }
    in_section && /^\|/ { print }
' "$FILE" | tail -n +3)

if [ -z "$rows" ]; then
    echo "✖ $FILE: таблица «## Каркас» не найдена или пуста" >&2
    exit 1
fi

while IFS= read -r row; do
    concern=$(printf '%s' "$row" | awk -F'|' '{ gsub(/^ +| +$/, "", $2); print $2 }')
    sample=$(printf '%s' "$row"  | awk -F'|' '{ gsub(/^ +| +$/, "", $3); gsub(/`/, "", $3); print $3 }')
    case "$sample" in
        ""|"—"|"-") continue ;;
    esac
    if [ ! -e "$sample" ]; then
        echo "✖ каркас «$concern»: образца нет — $sample" >&2
        status=1
    fi
done <<< "$rows"

# Путь в колонке «Правило» — спрятанный образец: сторож его не проверяет,
# значит он дрейфует молча. Второй образец — отдельная строка заботы.
while IFS= read -r row; do
    concern=$(printf '%s' "$row" | awk -F'|' '{ gsub(/^ +| +$/, "", $2); print $2 }')
    hidden=$(printf '%s' "$row" | awk -F'|' '{ print $4 }' | grep -oE '`[^`]*/[^`]*\.(php|vue|ts|js|sh|md)`' | head -1)
    if [ -n "$hidden" ]; then
        echo "✖ каркас «$concern»: путь в колонке «Правило» — $hidden; второй образец — отдельная строка" >&2
        status=1
    fi
done <<< "$rows"

[ "$status" -eq 0 ] && echo "✔ $FILE: $lines строк, образцы каркаса на месте"
exit "$status"
