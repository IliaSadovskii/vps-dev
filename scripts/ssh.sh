#!/usr/bin/env bash
#
# Зайти на машину. Отпечаток проверяется тем же порядком, что и в настройке:
# раньше эта команда шла мимо ansible/known_hosts и человек получал сырой
# вопрос ssh «continue connecting?» — тот самый, который вся остальная
# обвязка старательно превращает в осознанную сверку с панелью провайдера.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_ssh_key
load_servers
pick_targets "${1:-}" one
name="${PICKED[0]}"
addr="$(server_address "$name")"
ensure_known_host "$name" "$addr"

# dev_login_user, а не ansible_user: последний в реестре — шаблон
# (на свежей машине обвязка подставляет туда root), и ansible-inventory
# отдаёт его нераскрытым.
ssh_user="$(ansible_run ansible-inventory --host "$name" | jq -r '.dev_login_user // empty')"
[ -n "$ssh_user" ] || die "В реестре у машины ${name} не указан пользователь"

say "${ssh_user}@${addr}"
exec ssh -o UserKnownHostsFile="$KNOWN_HOSTS" -i "$SSH_KEY" "${ssh_user}@${addr}"
