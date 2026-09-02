#!/usr/bin/env bash
#
# Показать реестр машин. Адрес в частной сети спрашиваем у самой сети:
# в реестре он не хранится, чтобы копия не разъехалась с реальностью.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_servers
# У servers.yml этого проекта нет полей location/region, которые были
# у боевого сервера, — здесь машина одна, и её местоположение не то,
# что нужно сверять на глаз. Показываем то, что реестр правда хранит.
ansible_run ansible-inventory --list | jq -r '
  ._meta.hostvars as $hv
  | .dev.hosts[]?
  | $hv[.] as $h
  | "\(.)\t\($h.dev_provider // "—") \($h.dev_hardware // "")\t\($h.dev_public_address // "—")"
' | while IFS=$'\t' read -r name prov pub; do
    tailnet="$(discover_tailnet_address "$name")"
    echo "$name"
    echo "  провайдер:       $prov"
    echo "  публичный адрес: $pub"
    echo "  частная сеть:    ${tailnet:-— (машины в сети нет)}"
    echo ""
done
