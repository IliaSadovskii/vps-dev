#!/usr/bin/env bash
#
# Перезагрузить машину и дождаться, пока вернётся.
#
# Отдельной командой, а не шагом настройки: перезагрузка без присмотра —
# это то, о чём узнаёшь, когда сядешь работать и машина не откликнется.
# Решение о времени принимает человек.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_servers
pick_targets "${1:-}" one
name="${PICKED[0]}"
addr="$(server_address "$name")"
ensure_known_host "$name" "$addr"

if [ -t 0 ]; then
    echo ""
    echo "Перезагрузка ${name} (${addr}). Машина будет недоступна минуту."
    read -rp "Продолжить? [y/N] " ok
    [ "$ok" = "y" ] || die "Отменено."
fi

say "Перезагружаю ${name}"
ansible_run ansible "$name" -e ansible_host="$addr" -b -m reboot -a "reboot_timeout=300"

say "Машина вернулась, проверяю состояние"
"${ROOT_DIR}/scripts/watch.sh" "$name"
