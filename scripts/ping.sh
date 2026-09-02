#!/usr/bin/env bash
#
# Быстрая проверка «сервер отвечает». Отдельно от audit: нужен ответ
# за секунду, а не полный обход проверок.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_servers
pick_targets "${1:-}" all
targets=("${PICKED[@]}")

for n in "${targets[@]}"; do
    ensure_known_host "$n" "$(server_address "$n")" "$(server_public_address "$n")"
done
for n in "${targets[@]}"; do
    addr="$(server_address "$n")"
    ansible_run ansible "$n" -e ansible_host="$addr" -m ping
done
