#!/usr/bin/env bash
#
# Заново запомнить ключ машины. Нужно, когда её пересоздали: ключ у неё
# новый, а в known_hosts лежит старый, и подключение падает на несовпадении.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_servers
pick_targets "${1:-}" one
name="${PICKED[0]}"
addr="$(server_address "$name")"

scan="$(ssh-keyscan -H "$addr" 2>/dev/null || true)"
[ -n "$scan" ] || die "Машина ${name} (${addr}) не отвечает на порту 22."

ssh-keygen -R "$addr" -f "$KNOWN_HOSTS" >/dev/null 2>&1 || true
printf '%s\n' "$scan" >> "$KNOWN_HOSTS"
sort -u "$KNOWN_HOSTS" -o "$KNOWN_HOSTS"

# Записываем отпечаток и в реестр: там он под присмотром git, и дальше
# подлинность машины проверяется сравнением, а не вопросом человеку.
#
# ИМЕННО dev_host_fingerprint и именно в виде SHA256:… — это единственное
# имя, которое читают lib.sh, lint.sh и сам servers.yml. Записать сюда
# что-то другое значило бы сообщить «ключ записан», а на деле реестр
# получил бы переменную, которую не читает никто, и отпечаток остался бы
# прежним — от машины, которой уже нет.
fingerprint="$(printf '%s\n' "$scan" | ssh-keygen -lf - 2>/dev/null \
    | awk '$4 == "(ED25519)" {print $2}' | head -1)"

if [ -z "$fingerprint" ]; then
    say "Не удалось вычислить отпечаток ключа ed25519 — впиши его в servers.yml сам."
elif grep -q "dev_host_fingerprint:" <(sed -n "/^        ${name}:/,/^        [a-z]/p" "${ROOT_DIR}/servers.yml"); then
    # Не подменяем молча: расхождение здесь означает либо пересозданную
    # машину, либо чужой ключ, и решать это должен человек.
    echo ""
    echo "  В servers.yml у ${name} отпечаток уже записан. Сверь и замени сам:"
    echo "    dev_host_fingerprint: \"${fingerprint}\""
else
    tmp="$(mktemp)"
    awk -v n="        ${name}:" -v k="          dev_host_fingerprint: \"${fingerprint}\"" \
        '{ print } $0 == n { print k }' "${ROOT_DIR}/servers.yml" > "$tmp"
    mv "$tmp" "${ROOT_DIR}/servers.yml"
    say "Отпечаток записан в servers.yml — не забудь закоммитить"
fi

echo "✔ Ключ запомнен. Сверь отпечаток с тем, что показывает панель провайдера:"
ssh-keygen -lf <(ssh-keyscan "$addr" 2>/dev/null)
