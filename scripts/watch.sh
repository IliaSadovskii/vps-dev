#!/usr/bin/env bash
#
# Присмотр за машинами: отвечают ли, не просят ли перезагрузки, есть ли
# место на диске, на месте ли брандмауэр и частная сеть.
#
# Запускается по расписанию из GitHub Actions. Сейчас о падении сервера
# не узнаёт никто — узнаёшь, когда захочешь поработать и не достучишься.
#
# Проверки намеренно грубые: это не наблюдение за метриками, а ответ
# на вопрос «всё ли ещё стоит на ногах». Тонкие метрики появятся вместе
# с приложением, и это другой инструмент.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Порог свободного места. Ниже — предупреждаем: диск забивают образы
# и журналы контейнеров, и кончается он всегда неожиданно.
readonly DISK_FREE_MIN_PERCENT=15

load_servers
pick_targets "${1:-}" all
targets=("${PICKED[@]}")

PROBLEMS=()

check_one() {
    local name="$1" addr out

    if ! addr="$(server_address "$name" 2>/dev/null)"; then
        echo "  ✖ ${name}: нет адреса — ни в частной сети, ни в реестре"
        PROBLEMS+=("${name}: машины нет в частной сети")
        return 1
    fi

    echo "  → ${name} (${addr})"

    # Без этого проверка падает на непроверенном ключе хоста: known_hosts
    # в git не хранится, и на свежей машине его нет ни локально, ни в CI.
    ensure_known_host "$name" "$addr" >/dev/null 2>&1 || {
        echo "    ✖ не удалось подтвердить ключ машины"
        PROBLEMS+=("${name}: ключ машины не совпал с записанным в реестре")
        return 1
    }

    # Одной командой, а не пятью подключениями: каждое стоит секунд,
    # а проверок будет больше по мере роста.
    # shellcheck disable=SC2016  # подстановки раскрываются на сервере, не здесь
    out="$(ansible_run ansible "$name" -e ansible_host="$addr" -b -m shell -a '
        echo "reboot=$([ -f /var/run/reboot-required ] && echo yes || echo no)"
        echo "disk_free=$(df --output=pcent / | tail -1 | tr -dc "0-9")"
        echo "ufw=$(systemctl is-active ufw 2>/dev/null)"
        echo "tailscale=$(systemctl is-active tailscaled 2>/dev/null)"
        echo "docker=$(systemctl is-active docker 2>/dev/null)"
        echo "containers=$(docker ps -q 2>/dev/null | wc -l)"
    ' 2>/dev/null)" || {
        echo "    ✖ не отвечает"
        PROBLEMS+=("${name}: сервер не отвечает")
        return 1
    }

    # Ansible раскрашивает вывод, и строки начинаются с управляющих
    # последовательностей — разбор по началу строки без этого не работает.
    out="$(printf '%s' "$out" | sed 's/\x1b\[[0-9;]*m//g')"

    local reboot disk ufw ts docker containers used
    reboot="$(sed -n 's/^reboot=//p' <<< "$out" | tr -d '\r')"
    used="$(sed -n 's/^disk_free=//p' <<< "$out" | tr -d '\r')"
    ufw="$(sed -n 's/^ufw=//p' <<< "$out" | tr -d '\r')"
    ts="$(sed -n 's/^tailscale=//p' <<< "$out" | tr -d '\r')"
    docker="$(sed -n 's/^docker=//p' <<< "$out" | tr -d '\r')"
    containers="$(sed -n 's/^containers=//p' <<< "$out" | tr -d '\r')"
    disk=$((100 - ${used:-100}))

    echo "    отвечает, свободно ${disk}% диска, контейнеров ${containers:-?}"

    [ "$reboot" = "yes" ] && {
        echo "    ⚠ просит перезагрузки"
        PROBLEMS+=("${name}: установлены обновления, нужна перезагрузка")
    }
    [ "$disk" -lt "$DISK_FREE_MIN_PERCENT" ] && {
        echo "    ⚠ мало места: ${disk}%"
        PROBLEMS+=("${name}: на диске осталось ${disk}%")
    }
    [ "$ufw" = "active" ] || {
        echo "    ✖ брандмауэр не работает"
        PROBLEMS+=("${name}: брандмауэр не работает — публичный SSH мог открыться")
    }
    [ "$ts" = "active" ] || {
        echo "    ✖ частная сеть не работает"
        PROBLEMS+=("${name}: служба частной сети не работает")
    }
    [ "$docker" = "active" ] || {
        # Доска Kandev, чат Agent of Empires и сами агенты живут в Docker —
        # без него на машине нечем работать.
        echo "    ✖ Docker не работает"
        PROBLEMS+=("${name}: Docker не работает — доска и чат лежат")
    }
    return 0
}

echo "→ Присмотр за машинами"
for name in "${targets[@]}"; do
    check_one "$name" || true
done

echo ""
if [ "${#PROBLEMS[@]}" -eq 0 ]; then
    echo "✔ Всё на ногах"
    exit 0
fi

echo "✖ Что не так:"
printf '  %s\n' "${PROBLEMS[@]}"
exit 1
