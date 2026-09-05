Run the whole test suite after the review fixes have been checked, and say
plainly when something that used to pass no longer does.

Goal: Give `Draft PR` and the human at the review gate a trustworthy signal
    that the code is still whole after `Review Fixes` changed it.
    `Verification` already confirmed the original implementation against its
    own tests, in the context that wrote it; `Fix Review` has since read the
    fixes, but nothing has re-run the suite as a whole on top of them. This
    run is what stands in for that.
Reads: `review-fixes.md` for what changed, why, and who called it, and
    `fix-review.md` for what the fresh reading of those fixes concluded —
    both absent when `Security Review` sent the card straight here because
    neither review had a finding; then there were no fixes, the diff is
    what `Verification` last ran against, and a failure here still returns
    the card to `Review Fixes` (which will read your file as its caller),
    `verification.md#Итог` for the baseline this task passed before review, the
    artifact `README.md` for the starting commit,
    `discovery.md#Тесты и проверки` for the commands and the test-file
    patterns, and your own previous
    `final-verification.md`, if the card has already been through this step,
    for the lap it left off on. Your context is cleared on entry, so
    everything before you is a file to open, not a memory.
Writes: `final-verification.md`.
Done when: `final-verification.md` holds a verbatim run, the ownership
    script's verdict, a verdict, a comparison against `verification.md`, and
    and exactly one of two things has happened —
    `step_complete_kandev` was called because the run is clean or because
    the lap's automatic return is already spent, or `move_task_kandev` sent
    the card back to `Review Fixes` because the run failed and the return
    was still available.

## Wide, not narrow

`Verification` ran right after `Implementation`, in the same context, and
closed a specific red-green loop: the tests `Test Authoring` wrote, now
passing. This step runs after `Review Fixes` and `Fix Review` and asks a
different question — not whether one set of tests went green, but whether
the whole suite still does once fixes have landed on top of already-verified
code. Run the project's full test target, not only the tests the review
touched: a fix that narrows an edge case, or a change made while already in
that area of the code, can break something the diff itself never mentions, and
only a full run surfaces that. A `review-fixes.md` that made no code changes
is not a reason to skip the run either — confirming the whole thing is the job
here, not confirming only what moved.

## Locating what to run

Run the commands `discovery.md` records under «Тесты и проверки»: the full
test run, the linter and the type checker, each as the project defines it,
not a command remembered from another project. Where that section is empty
or marked inferred, find the project's own definition yourself: the CI
configuration, `Makefile`, `package.json`, a rule file. Do not poll or wait
on the CI run; it fires on a separate mechanism, after this step.

All three run here whatever CI will do later. This is the last step before
a pull request opens, and a project without CI, or with a CI that skips the
linter, has no other place where a red linter or a type error is caught
before a human reads the PR. A check the project does not have is said so
in the artifact, the way `discovery.md` said it, not silently skipped; a
check that is too slow to run whole is run in its narrowest form that still
covers the changed files, with the narrowing named. What isn't optional is
running something at all — reporting a pass without a run behind it is
exactly the failure this step exists to catch, one step before a pull
request opens on its word. A red linter or type check is a failure of this
step like a red test: it returns the card under the rule below, and goes
forward as `Не решено:` when the return is spent.

## Who touched the tests

Before reading the suite's result, run the ownership script from the
workflow-level `custom-test-ownership` prompt through a heredoc, giving it
the starting commit from `README.md` and the test-file patterns from
`discovery.md`. A test file changed by any commit other than
`Test Authoring`'s is a failure of this step in its own right, whatever the
suite says: a green run over a test someone loosened is not the signal this
step exists to produce. Paste the script's verdict into the artifact.

## Naming a regression

Compare your run against `verification.md`, test by test where its output lets
you, by overall outcome where it doesn't. Something that passed there and
fails now is not a fresh bug for whoever reads this next to puzzle out from
scratch — it is a regression the review's own fixes introduced, and the
artifact should name it as that, not just list a failure among others. Where
`verification.md` never covered something you're now seeing fail — its own run
could have been narrower than a full suite, made in `Implementation`'s context
— say plainly that there is no prior result to compare against, rather than
calling it a regression you cannot back up. Leave the fix itself to
`Review Fixes`; do not edit a test or loosen an assertion to clear a failure,
because that erases the exact signal this comparison exists to produce.

## Returning the card, and when to stop returning

automatic return to `Review Fixes`, shared with `Fix Review`. Ask the state:
`kd-state return fix_chain check` prints `available` or `spent`; taking it is
`kd-state return fix_chain spend`, which prints `available` and marks it
taken, or prints `spent` and exits non-zero if it was already gone.

A clean run with no regression, a clean linter and type check and a clean
ownership verdict ends the step normally with `step_complete_kandev`. A run
that fails, turns up a regression, fails the linter or the type checker, or
fails ownership, while the return is available, sends the card back: move
it to `Review Fixes` as the protocol describes — workflow ID and step ID
from the lookup, then `move_task_kandev` with `task_id`,
`workflow_id`, `workflow_step_id` and a `prompt` pointing at
`final-verification.md` rather than restating the failures — the step reads
your file directly once it resumes, so the hand-off only has to say where
to look. Do not call `step_complete_kandev` in that outcome. If the move
fails, call `step_complete_kandev` instead and begin your closing message
with `Не решено:` naming the failed move.

When the return is already spent, do not return the card again: write the
verdict honestly, call `step_complete_kandev`, and make your closing message
begin with the line `Не решено:` followed by what still fails, so that
`Draft PR` and the human gate receive it as unresolved. A problem that
survived one round of fixes is a call for a person to make, not another
automatic loop; the shared limit is what keeps the tail from looping without
end.

## Artifact shape

`final-verification.md`:
- Итог — at most ten lines: green or not, and the one failure that decides it.
- Что запущено — the exact commands you ran: the test run, the linter, the
  type checker and the ownership script, each with its summary line and, where
  something failed, that failure as it printed, not a paraphrase. The whole
  output goes to `.kandev/artifacts/$KANDEV_TASK_ID/logs/final-verification.txt`,
  appended, and this section names that path.
- Результат — the verdict itself: clean, or what failed and where, linter,
  type check and test ownership included.
- Расхождения с verification.md, если есть — the regressions identified by
  that comparison, or an explicit statement that none showed up where the
  comparison could actually be made.

## Finishing

Nobody is watching this step while it runs, and a question left in your last
message just stalls the task until someone happens to notice it. Decide what
the run tells you and act on it — return the card or don't — rather than
describing that decision for someone else to make.

Every line in the artifact traces to a command you actually ran in this
session and read the output of; a comparison you couldn't make traces to
something genuinely missing from `verification.md`, not to a guess at what it
probably contained. Where you couldn't establish something, say so instead of
writing around the gap.

Before you stop, reread your own last message: if it reads like a plan to run
the suite rather than a suite already run, or a promise to compare rather than
a comparison already made, do that work now instead of leaving it there.
