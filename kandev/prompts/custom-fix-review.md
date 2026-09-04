Review the review fixes with a fresh context before their test run is trusted.

Goal: Confirm that every disposition in `review-fixes.md` is supported by the
    actual diff, that each fix closes the finding or human objection it names,
    and that the fix introduced no new correctness or security defect.
Reads: `discovery.md` (project rules and its test-file patterns),
    `scoping.md`, `code-review.md`, `security-review.md`, `review-fixes.md`,
    `final-verification.md` when it caused the current rework, the artifact
    `README.md` for the starting commit, your own previous `fix-review.md`
    when this step has run before, and the task conversation through
    `get_task_conversation_kandev`.
Writes: `fix-review.md`; new actionable defects also go through
    `publish_review_findings_kandev`.
Done when: every current-entry disposition has been checked against code and
    commits, the artifact has all four sections below, and exactly one of
    `step_complete_kandev` (non-blocking, or blocking with the automatic
    return already spent) or `move_task_kandev` (blocking, return still
    available) has been called. Never call both.

## Establish the review-fix diff

Read the starting commit from the artifact `README.md`. Inspect the commits
whose `Kandev-Step` trailer is `Review Fixes` and which were made for the
entry `review-fixes.md` describes. Use that file to map commits to findings.
Do not substitute arbitrary working-tree changes for committed task history;
pre-existing or unattributed dirty changes are not evidence of a fix. If the
base or ownership cannot be established, record that as blocking.

## Check every disposition

For each item `review-fixes.md` says it handled — original review finding,
final-verification failure, or latest human objection, depending on who
called it — verify one of these outcomes:

- the named commit changes the stated defect and the triggering case no longer
  follows from the code;
- the explanation for rejecting the finding is supported by the actual call or
  data flow;
- the item is explicitly deferred because it requires an owner decision, with
  no code pretending otherwise.

Do not accept “fixed”, a green narrow test, or a commit hash on its own.
Trace far enough to establish the claim. Also inspect the changed lines as a
new diff for regressions, widened scope, changed trust boundaries, and
behavior that no approved scope or plan asked for.

## Test files are off limits in this tail

Only `Test Authoring` changes tests, and it does not run between the review
and the pull request. Any test file in a `Review Fixes` commit — added,
edited, skipped, deleted, an assertion loosened — is blocking on its own, no
matter what finding it claims to close; a finding that genuinely needs a test
change goes forward for a human to route to `Test Authoring`. Do not judge
this by eye alone: run the ownership script from the workflow-level
`custom-test-ownership` prompt through a heredoc, giving it the starting
commit from `README.md` and the test-file patterns from `discovery.md`, and
paste its verdict into the artifact.

## Publishing new defects

Publish only defects introduced or left unresolved by the fixes; do not
republish the original finding merely to say it remains open. Each item sent
to `publish_review_findings_kandev` must use the platform schema exactly:
`file`, 1-based `line`, optional `line_end`, `severity` from
`blocker|major|minor|nit`, a kebab-case `category`, one-line `title`, and
Markdown `body`. Put confidence in `body` and in the artifact; it is not a
tool field. In a multi-repository task also provide `repo`.

The review panel is additive. You cannot close an older finding through this
tool; describe its disposition in `fix-review.md` and leave the human to mark
that panel item resolved after checking it.

## Bounded return

Between two human messages, this step and `Final Verification` share a single
automatic return to `Review Fixes`. Whether it is still available is written
in the latest `review-fixes.md`, under Заход: `Вызван: ревью` or
`Вызван: человек` means no automatic return has happened yet in this lap;
`Вызван: Fix Review` or `Вызван: Final Verification` means it has been spent.

Blocking verdict, return available: move the card to `Review Fixes` as the
protocol describes — workflow ID and step ID from the lookup, then
`move_task_kandev` with `task_id`, `workflow_id`, `workflow_step_id` and a
short `prompt` pointing to `fix-review.md`. Do not call
`step_complete_kandev` in that outcome. If the move fails, call
`step_complete_kandev` instead and begin your closing message with
`Не решено:` naming the failed move.

Blocking verdict, return spent: do not loop again. Call
`step_complete_kandev`, and make your closing message begin with the line
`Не решено:` followed by the blocker, so that `Draft PR` and the human gate
receive it as unresolved rather than as noise.

## Artifact shape

`fix-review.md` has exactly these sections:

- `## Вердикт` — `Готово к проверке`, `Готово с оговорками`, or
  `Заблокировано`, naming the deciding issue.
- `## Проверка исправлений` — one entry per current finding or objection, its
  disposition, evidence, and your conclusion, plus the ownership script's
  verdict.
- `## Новые находки` — every defect introduced by the fixes, with file, line,
  severity, confidence, and publication status; explicitly empty when none.
- `## Заход` — this step's ordinal on the task, and what the latest
  `review-fixes.md` said under Вызван, so the return decision is auditable.

Write the artifact and your user-facing message in Russian. Base every claim
on files and commands opened in this session. Then perform exactly one
transition: `move_task_kandev` for a blocking result while the return is
available, otherwise `step_complete_kandev`.
