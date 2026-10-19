#!/usr/bin/env bash
#
# Сторож AGENTS.md и таблицы каркаса docs/skeleton.md.
#
# Ловит в AGENTS.md: больше 175 строк; тяжелее 21 000 символов; строку
# длиннее 600 символов. В таблице каркаса: пустую таблицу; путь в колонке
# «Образец», которого нет в репозитории; путь, спрятанный в колонке «Правило»;
# правило длиннее 300 символов; путь или цитату арх-теста в колонке
# «Проверка», которых нет; заботу, которой нет в оглавлении «## Каркас»
# AGENTS.md.
# Не ловит: устаревший смысл строки, дубли, пути в других разделах,
# «—» при уже существующем коде — это видит владелец в диффе.
#
# Запуск из корня репозитория: scripts/check-agents.sh [AGENTS.md [docs/skeleton.md]]
# Пределы: AGENTS_LIMIT (строки AGENTS.md), по умолчанию 175;
# AGENTS_CHARS_LIMIT (символы AGENTS.md), по умолчанию 21000;
# AGENTS_LINE_LIMIT (одна строка AGENTS.md), по умолчанию 600;
# SKELETON_RULE_LIMIT (колонка «Правило»), по умолчанию 300.
#
# AGENTS.md едет агенту в каждый ход, поэтому считаются и символы: при
# пределе по строкам файл рос длиной строк — до 40 тыс. символов (аудит
# промптов 2026-10-19). Каркас разделён на два уровня (выбор владельца
# 2026-10-19): в AGENTS.md — оглавление забот, его видит любой агент и по
# нему понимает, что фича задевает заботу; образец, правило и проверка — в
# docs/skeleton.md, числа строк там не ограничиваем — каркас растёт с
# приложением. Подробности длиннее строки — в docs/rules/<область>.md.

set -euo pipefail

FILE="${1:-AGENTS.md}"
SKELETON="${2:-docs/skeleton.md}"
LIMIT="${AGENTS_LIMIT:-175}"
CHARS_LIMIT="${AGENTS_CHARS_LIMIT:-21000}"
LINE_LIMIT="${AGENTS_LINE_LIMIT:-600}"
RULE_LIMIT="${SKELETON_RULE_LIMIT:-300}"
status=0

[ -f "$FILE" ] || { echo "✖ нет файла $FILE" >&2; exit 1; }
[ -f "$SKELETON" ] || { echo "✖ нет файла $SKELETON" >&2; exit 1; }

lines=$(wc -l < "$FILE")
chars=$(LC_ALL=C.UTF-8 wc -m < "$FILE")

if [ "$chars" -gt "$CHARS_LIMIT" ]; then
    echo "✖ $FILE: $chars символов, предел $CHARS_LIMIT" >&2
    status=1
fi
while IFS= read -r long; do
    echo "✖ $FILE: строка $long символов, предел $LINE_LIMIT" >&2
    status=1
done < <(LC_ALL=C.UTF-8 awk -v max="$LINE_LIMIT" 'length($0) > max { print NR ": " length($0) }' "$FILE")

# Строки таблицы под «## Каркас» до следующего заголовка, без шапки и разделителя.
rows=$(awk '
    /^## /            { in_section = ($0 ~ /^## Каркас/); next }
    in_section && /^\|/ { print }
' "$SKELETON" | tail -n +3)

if [ -z "$rows" ]; then
    echo "✖ $SKELETON: таблица «## Каркас» не найдена или пуста" >&2
    exit 1
fi

if [ "$lines" -gt "$LIMIT" ]; then
    echo "✖ $FILE: $lines строк, предел $LIMIT" >&2
    status=1
fi

# Оглавление забот в AGENTS.md — то, что видит любой агент: забота из таблицы,
# которой нет в оглавлении, для него не существует.
index=$(awk '/^## /{ in_section = ($0 ~ /^## Каркас/); next } in_section' "$FILE")
while IFS= read -r row; do
    concern=$(printf '%s' "$row" | awk -F'|' '{ gsub(/^ +| +$/, "", $2); print $2 }')
    if ! grep -qF -- "$concern" <<< "$index"; then
        echo "✖ каркас «$concern»: нет в оглавлении «## Каркас» $FILE" >&2
        status=1
    fi
    rule_len=$(printf '%s' "$row" | LC_ALL=C.UTF-8 awk -F'|' '{ gsub(/^ +| +$/, "", $4); print length($4) }')
    if [ "$rule_len" -gt "$RULE_LIMIT" ]; then
        echo "✖ каркас «$concern»: правило $rule_len символов, предел $RULE_LIMIT — подробности в docs/rules/" >&2
        status=1
    fi
done <<< "$rows"

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

# Колонка «Проверка» дрейфует так же молча, как «Образец»: путь к тесту, которого
# уже нет, или цитата «арх-тест «…»», которую переименовали. Путь обязан
# существовать, цитата — встречаться в tests/Arch дословно.
while IFS= read -r row; do
    concern=$(printf '%s' "$row" | awk -F'|' '{ gsub(/^ +| +$/, "", $2); print $2 }')
    check=$(printf '%s' "$row" | awk -F'|' '{ print $5 }')

    for path in $(printf '%s' "$check" | grep -oE '`(app|resources|database|tests|scripts|routes|config)/[^`]*`' | tr -d '`' || true); do
        if [ ! -e "$path" ]; then
            echo "✖ каркас «$concern»: проверки нет — $path" >&2
            status=1
        fi
    done

    while IFS= read -r quote; do
        [ -n "$quote" ] || continue
        if [ ! -d tests/Arch ] || ! grep -rqF -- "$quote" tests/Arch; then
            echo "✖ каркас «$concern»: арх-теста «$quote» нет в tests/Arch" >&2
            status=1
        fi
    done < <(printf '%s' "$check" | grep -oE 'арх-тест «[^»]+»' | sed -E 's/^арх-тест «//; s/»$//' || true)
done <<< "$rows"

[ "$status" -eq 0 ] && echo "✔ $FILE: $lines строк, $chars символов; $SKELETON: $(printf '%s\n' "$rows" | wc -l) забот, образцы и проверки на месте"
exit "$status"
