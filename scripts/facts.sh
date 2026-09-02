#!/usr/bin/env bash
#
# Что Ansible знает о машине.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_servers
pick_targets "${1:-}" one
name="${PICKED[0]}"
ensure_known_host "$name" "$(server_address "$name")" "$(server_public_address "$name")"
ansible_run ansible "$name" -e ansible_host="$(server_address "$name")" -m setup
