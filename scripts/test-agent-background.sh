#!/usr/bin/env bash
# Примеры решений хука agent-background: код выхода, глубина, флаг фона.
set -euo pipefail

hook="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ansible/roles/style/files/agent-background"
bad=0

check() {
    local want=$1 input=$2 got=0
    "$hook" <<<"$input" >/dev/null 2>&1 || got=$?
    if [ "$got" != "$want" ]; then
        echo "  ✖ ждали $want, вышло $got: $input"
        bad=1
    fi
}

check 0 '{"tool_input":{"prompt":"x","run_in_background":true}}'
check 2 '{"tool_input":{"prompt":"x","run_in_background":false}}'
check 2 '{"tool_input":{"prompt":"x"}}'
check 0 '{"agent_id":"a1","tool_input":{"prompt":"x","run_in_background":false}}'
check 2 '{"agent_id":"a1","tool_input":{"prompt":"x","run_in_background":true}}'
check 2 '{"agent_id":"a1","tool_input":{"prompt":"x"}}'

[ "$bad" = 0 ] && echo "  ✔ хук фона: примеры сходятся"
exit "$bad"
