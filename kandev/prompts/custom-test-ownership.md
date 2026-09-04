Who may touch a test file, checked from git history rather than from prose.

Test files in a task's history belong to `Test Authoring`: only commits
carrying the trailer `Kandev-Step: Test Authoring` may touch one. The script
below is what enforces that. `Verification`, `Final Verification` and
`Fix Review` run it and record its output verbatim in their artifact; a
failure is a blocking finding for the role that ran it — named, carried
forward, decided by a human — and never something to make green by editing,
moving or deleting the test or by rewriting history.

Inputs: the starting commit recorded in the artifact `README.md`, and the
test-file glob patterns from the «Тесты и проверки» section of
`discovery.md`, space-separated. Run it from inside the repository, or set
`REPO` to its root:

```sh
START=<starting-commit> PATTERNS='<glob> <glob>' sh <<'EOF'
set -fu
: "${START:?starting commit from README.md}"
: "${PATTERNS:?test-file globs from discovery.md}"
g() { git -C "${REPO:-.}" "$@"; }
status=0
for c in $(g rev-list --reverse "$START..HEAD"); do
  step=$(g show -s --format=%B "$c" \
    | sed -n 's/^Kandev-Step:[[:space:]]*//p' | tail -n 1)
  for f in $(g show --pretty=format: --name-only "$c"); do
    for p in $PATTERNS; do
      case "$f" in
        $p) if [ "$step" != "Test Authoring" ]; then
              printf '%s %s [%s]\n' "$c" "$f" "${step:-no trailer}"
              status=1
            fi
            break ;;
      esac
    done
  done
done
if [ "$status" -eq 0 ]; then echo "test ownership: ok"
else echo "test ownership: FAIL"; fi
exit "$status"
EOF
```

Each offending line is `<commit> <file> [<trailer or "no trailer">]`; the
exit code is non-zero when any exist. If `discovery.md` records no patterns,
the check cannot run: say so in the artifact instead of guessing them.
