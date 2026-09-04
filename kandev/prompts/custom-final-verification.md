Run the whole test suite after the review fixes have been checked, and say
plainly when something that used to pass no longer does.

Goal: Give `Draft PR` and the human at the review gate a trustworthy signal
    that the code is still whole after `Review Fixes` changed it.
    `Verification` already confirmed the original implementation against its
    own tests, in the context that wrote it; `Fix Review` has since read the
    fixes, but nothing has re-run the suite as a whole on top of them. This
    run is what stands in for that.
Reads: `review-fixes.md` for what changed, why, and who called it,
    `fix-review.md` for what the fresh reading of those fixes concluded,
    `verification.md` for the baseline this task passed before review, the
    artifact `README.md` for the starting commit, `discovery.md` for the
    project's test-file patterns, and your own previous
    `final-verification.md`, if the card has already been through this step,
    for the lap it left off on. You run in `Fix Review`'s context, so
    everything before it is a file to open, not a memory.
Writes: `final-verification.md`.
Done when: `final-verification.md` holds a verbatim run, the ownership
    script's verdict, a verdict, a comparison against `verification.md`, and
    a Заход number, and exactly one of two things has happened —
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

Find the test command the way `Verification` does: the CI configuration,
`Makefile`, `package.json`, or whatever the project's own tooling declares,
not a command remembered from another project. Run locally whatever gives a
fast, precise signal here, and skip whatever the CI pipeline is already
certain to run once `Draft PR` opens a pull request — duplicating a check
that's about to run anyway spends the turn without adding information. Do not
poll or wait on that external run; it fires on a separate mechanism, after
this step. What isn't optional is running something at all — reporting a pass
without a run behind it is exactly the failure this step exists to catch, one
step before a pull request opens on its word.

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

Between two human messages, this step and `Fix Review` share a single
automatic return to `Review Fixes`. Whether it is still available is written
in the latest `review-fixes.md`, under Заход: `Вызван: ревью` or
`Вызван: человек` means no automatic return has happened yet in this lap;
`Вызван: Fix Review` or `Вызван: Final Verification` means it has been spent.

A clean run with no regression and a clean ownership verdict ends the step
normally with `step_complete_kandev`. A run that fails, turns up a
regression, or fails ownership, while the return is available, sends the
card back: call `list_workflow_steps_kandev`, find the exact `Review Fixes`
step ID, and call `move_task_kandev` with only this task's ID, that
`workflow_step_id`, and a `prompt` pointing at `final-verification.md`
rather than restating the failures — the step reads your file directly once
it resumes, so the hand-off only has to say where to look. Do not call
`step_complete_kandev` in that outcome.

When the return is already spent, do not return the card again: write the
verdict honestly, call `step_complete_kandev`, and make your closing message
begin with the line `Не решено:` followed by what still fails, so that
`Draft PR` and the human gate receive it as unresolved. A problem that
survived one round of fixes is a call for a person to make, not another
automatic loop; the shared limit is what keeps the tail from looping without
end.

## Artifact shape

`final-verification.md`:
- Что запущено, дословный вывод — the exact command or commands you ran,
  the ownership script among them, and their terminal output as it printed,
  not a paraphrase of what they found.
- Результат — the verdict itself: clean, or what failed and where, test
  ownership included.
- Расхождения с verification.md, если есть — the regressions identified by
  that comparison, or an explicit statement that none showed up where the
  comparison could actually be made.
- Заход — this step's ordinal count on this task: 1 the first time,
  and one more than your own prior `final-verification.md` shows on any
  later pass. The number is for the reader; the return decision comes from
  `review-fixes.md`, not from it.

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
