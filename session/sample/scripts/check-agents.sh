#!/usr/bin/env bash
#
# Сторож AGENTS.md: два бюджета и образцы каркаса.
#
# Ловит: файл без строк таблицы каркаса длиннее предела (150); таблица
# каркаса длиннее своего предела (40 строк); путь в колонке «Образец» таблицы «## Каркас»,
# которого нет в репозитории; путь, спрятанный в колонке «Правило»;
# отсутствующую или пустую таблицу.
# Не ловит: устаревший смысл строки, дубли, пути в других разделах,
# «—» при уже существующем коде — это видит владелец в диффе.
#
# Запуск из корня репозитория: scripts/check-agents.sh [AGENTS.md]
# Пределы: AGENTS_LIMIT (всё, кроме строк таблицы каркаса), по умолчанию
# 150; AGENTS_SKELETON_LIMIT (строки таблицы каркаса), по умолчанию 40.

set -euo pipefail

FILE="${1:-AGENTS.md}"
LIMIT="${AGENTS_LIMIT:-150}"
SKELETON_LIMIT="${AGENTS_SKELETON_LIMIT:-40}"
status=0

[ -f "$FILE" ] || { echo "✖ нет файла $FILE" >&2; exit 1; }

lines=$(wc -l < "$FILE")

# Строки таблицы под «## Каркас» до следующего заголовка, без шапки и разделителя.
rows=$(awk '
    /^## /            { in_section = ($0 ~ /^## Каркас/); next }
    in_section && /^\|/ { print }
' "$FILE" | tail -n +3)

if [ -z "$rows" ]; then
    echo "✖ $FILE: таблица «## Каркас» не найдена или пуста" >&2
    exit 1
fi

# Два бюджета: таблица каркаса — справочник, к которому агент обращается
# в момент предложения; остальное — инструкции на каждый ход. Считаются
# отдельно, чтобы строки каркаса не выталкивали правила и наоборот.
skeleton_rows=$(printf '%s\n' "$rows" | wc -l)
rest=$((lines - skeleton_rows))
if [ "$rest" -gt "$LIMIT" ]; then
    echo "✖ $FILE: $rest строк без таблицы каркаса, предел $LIMIT" >&2
    status=1
fi
if [ "$skeleton_rows" -gt "$SKELETON_LIMIT" ]; then
    echo "✖ $FILE: $skeleton_rows строк в таблице каркаса, предел $SKELETON_LIMIT" >&2
    status=1
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

# Путь к коду или класс в колонке «Правило» — спрятанный образец: сторож его
# не проверяет, значит он дрейфует молча. Второй образец — отдельная строка
# заботы. Ссылки на `docs/decisions/*` и `docs/rules/*` в «Правиле» законны.
while IFS= read -r row; do
    concern=$(printf '%s' "$row" | awk -F'|' '{ gsub(/^ +| +$/, "", $2); print $2 }')
    hidden=$(printf '%s' "$row" | awk -F'|' '{ print $4 }' \
        | grep -oE '`(app|resources|database|tests|scripts|routes|config)/[^`]*`|`App\\[A-Za-z\\]+`' | head -1 || true)
    if [ -n "$hidden" ]; then
        echo "✖ каркас «$concern»: путь в колонке «Правило» — $hidden; второй образец — отдельная строка" >&2
        status=1
    fi
done <<< "$rows"

[ "$status" -eq 0 ] && echo "✔ $FILE: $rest строк + $skeleton_rows строк каркаса, образцы на месте"
exit "$status"
