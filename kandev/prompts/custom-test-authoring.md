Write tests for the behaviour this task requires, and prove each one fails for
the right reason before any implementation code exists.

Goal: Leave a red test suite that pins down what "done" means for this task,
    so that `Implementation` — running next in this same session — has a
    target it cannot quietly redefine, and so that anyone who later reads the
    commit history or `test-authoring.md` can see the tests came first and
    failed on the missing behaviour, not on a mistake in the test itself.
Reads: The native Kandev Plan via `get_task_plan_kandev`, when the route ran
    `Planning` — when it did not, no Plan existing is the expected state, not
    a gap to report; `plan-review.md` when it exists, for the non-blocking
    notes that name a test scenario; `scoping.md` for what this task covers
    and what it
    deliberately leaves out; `discovery.md` for how this project is built and
    what rules it states about itself, including «Тесты и проверки» — where
    its tests live and how they run; `research.md` when it exists, for the
    stack documentation and practices already found for this task;
    `docs/knowledge/scenarios.md` when `discovery.md`'s `Чертёж:` line
    names scenarios or actions, for the scenarios whose steps name this
    task's actions, and `docs/knowledge/actions.md` for the `state:` of
    the actions those scenarios name; your own
    previous `test-authoring.md` when it exists, since that means this is a
    repeat lap; and `notes-test-authoring.md`, since your context was cleared and anything a
    human said at a gate lives only there.
Writes: `test-authoring.md` under `.kandev/artifacts/$KANDEV_TASK_ID/`.
Done when: every test file you wrote has been run, its failure output is
    captured verbatim in `test-authoring.md`, that output shows the test
    failing on the behaviour under test rather than on a broken import,
    fixture, or syntax error, your commit carries the trailer
    `Kandev-Step: Test Authoring`, and you have called `step_complete_kandev`.

## Reading what already narrows the work

If `get_task_plan_kandev` returns a Plan, it names the signatures, files, and
boundaries `Planning` already committed to — write your tests against those,
not against your own guess at how the feature should be shaped. `scoping.md`
tells you which behaviour this task actually owns; a test for something
`scoping.md` marks out of bounds is not caution, it is scope the task never
asked you to cover. `discovery.md`'s «Тесты и проверки» tells you where a
test file goes, what it is called and which command runs it — put yours
where the project puts them, so the patterns recorded there match your files.
The Plan's «Проверки» also says which kinds of test this change needs —
unit, integration, browser scenario, visual, contract — and which of them
the project already runs. Write every kind the Plan kept, not only the
cheapest; a kind the Plan named and you skipped is a gap `Plan Review`
already ruled out. Where «Проверки» records the owner approving a tool the
project did not have, install and configure it as part of this step —
following the tool's own documentation, in the place and shape the
project's existing test setup uses — and commit that setup with the same
trailer as the tests. Install nothing the Plan does not record as approved.
`research.md`, where it exists, and the Plan's «Источники» name the stack's
documentation and the practices already settled for this task; a test that
exercises the framework the way its documentation shows is one
`Implementation` can satisfy the way this stack intends. Where no source
settles a detail the test needs, decide it yourself and record the assumption
under «Допущения» rather than leaving the test looser than the behaviour
it's meant to pin down — `Draft PR` reads that section to show the
reviewer what was decided without them. Anything a test needs that only a
person with access can provide — a credential, a service account, a
variable on the host — goes there too, as a line beginning
`Нужны руки человека:` with the exact command or step; `Draft PR` collects
those lines by their marker.

## Loading the skills Discovery named

«Стек и структура» in `discovery.md` ends with a `Навыки:` line. For each
skill it names that lists `Test Authoring` in the «Skills» table of
`custom-artifact-protocol` — `custom-skill-frontend` for user-facing UI —
call `get_shared_prompt_kandev` with that exact name before you write a
test, and write by its rules on top of this prompt's: they never loosen
the commit trailer or failing for the right reason. A skill the tool
cannot return, or a tool that is not there, goes under «Допущения», and
you proceed without it.

## Scenarios as test cases, when the project has them

When `discovery.md` names records under `Чертёж:`, read the scenarios in
`docs/knowledge/scenarios.md` whose steps name this task's action keys.
Each is a test case in the owner's own terms: «Исходная точка» is the
fixture, the steps are the calls, «Чем заканчивается» is the assertion —
and that ending was answered by the owner, so a test asserting anything
weaker pins down less than the product promises. A scenario every action
of which is `built` once this task lands — the others were built before,
this task builds the last one, wherever in the scenario it stands — gets
a test that walks it whole, start to ending, in the kind of test the
Plan's «Проверки» kept for it, carrying on a line of its own the comment
`kandev:scenario <заголовок сценария>`, so anyone can later count which
scenarios a test proves and which only a reading of the code does. A
scenario that still names a `planned` action after this task gets its
built steps covered like any other behaviour; do not walk it whole from
a stub. Say under «Какое поведение покрыто» which scenarios you read,
which one got its whole-walk test, or that none qualified and why.
Where the Plan departs from a scenario's ending, the Plan wins —
`Plan Approval` saw it — and «Допущения» gets one line,
`Отступление от чертежа: scenarios.md#<заголовок> — <what the ending
says, what the tests assert instead>`, so `Draft PR` tells the owner
the description is outdated. Without a `Чертёж:` line nothing here
applies.

## Plan Review's notes that are test work

`plan-review.md`, when it exists, holds «Незаблокирующие замечания» — what
`Plan Review` saw and let the plan go forward with. Some of them name a test
scenario the plan is missing or has too weak: an empty query, a boundary
«Проверки» skipped, a failure path no stage exercises. Those are test work
for this step, not advice for someone later: write those tests too, in the
same red state as the rest. Nobody downstream reads that section for tests —
`Implementation` builds against your files — and a scenario left there
resurfaces one lap later as a `Code Review` finding that could have been a
test today. Record in `test-authoring.md` which notes you took — each under
«Какое поведение покрыто», tied to the note — and which you did not and
why, under «Допущения»: the note was outside `scoping.md`, the Plan already
settled it, or it names no test at all.

## A repeat lap

Your own previous `test-authoring.md` existing means this step has run
before: a human dragged the card back here after leaving notes, or a finding
downstream asked for a test. Take this lap's number from
`kd-state lap "Test Authoring"` and work from the difference, not from
scratch. Write only the tests that message or that
finding asks for. Tests from an earlier lap that pass now are the record of
behaviour already built: leave them as they are, and delete nothing. The rule
below that a test passing on its first run needs rewriting applies to the
tests you add on this lap, not to the ones you inherit. «Файлы тестов» and
«Вывод прогона» cover this lap's files; «Какое поведение покрыто» keeps the
earlier entries and adds the new ones.

## Failing for the right reason

This is the one thing every account of this work agrees on, and it is the part
that is easy to get wrong without noticing. A test can fail for two entirely
different reasons, and only one of them means anything. The reason you want is
the test's own assertion catching behaviour that does not exist yet — a
comparison that fails, a response that doesn't come back, a value that isn't
there. The reason you don't want is the test never getting far enough to make
that comparison at all: a missing import, a typo in a call, a fixture that
throws before the test body runs, a syntax error, a config the test runner
can't find. Both look identical in the one place it's tempting to check — a
non-zero exit code — and only reading the actual failure text tells them
apart.

Treat every failure as unclassified until you've read what it says. When the
message names the thing you're testing for — the missing function, the absent
field, the wrong output — that's the reason you were after, and the test stays
as written. When it names anything else — an import path, an undefined name, a
fixture error, a stack trace pointing at the test's own setup — that is not
evidence the behaviour is missing, it's evidence the test can't run yet. Fix
the test — the import, the fixture, the setup — and run it again. Repeat until
the failure text itself is about the behaviour, not about getting the test to
a point where it could check it. A new test that passes on this first run
tells you nothing either: it means either the behaviour already exists or the
test isn't checking what you think it is, and either way it needs rewriting,
not keeping.

## Not building the thing you're testing for

Writing a stub, an empty function, or a placeholder file so the test can at
least import something is the shortcut that produces the wrong kind of red or
a false green — it moves the failure from "behaviour missing" to whatever the
stub happens to do, and sometimes past failure entirely. Let the test fail on
the absence itself: an import that doesn't resolve, a call to something that
doesn't exist. That absence is `Implementation`'s starting point, not a rough
edge for you to smooth first.

## Mocking only what the plan calls external

Stub out network calls, other services, or anything the Plan or `scoping.md`
names as outside this task's boundary. Anything inside that boundary — the
module this task is about — stays real in the test, even where it doesn't
exist yet and the test fails because of that. Mocking the thing under test
hides the exact absence the test exists to prove.

## Why the commit trailer, not just this text

The trailer `Kandev-Step: Test Authoring` on your commit is what the script
in `custom-test-ownership` checks later to confirm which step touched the
test files — not a courtesy note. A written rule against loosening a test,
however plainly it's stated, is read by exactly the agent that later wants to
loosen that test to make a stuck implementation pass; a rule that lives only
in prose has no footing against that pressure once the pressure exists. The
trailer moves the check outside the session where the pressure will show up,
into `git log`, where it holds regardless of what any later turn decides is
convenient. Commit your test files, and only your test files, under that
trailer before this step ends.

## When there is no test to write

If the repository has no runner for a kind of test the change needs and the
Plan does not record the owner approving one — or the behaviour genuinely
cannot be exercised by a test — say that plainly in `test-authoring.md`,
naming the kind that is missing, instead of writing a test that always
passes to fill the section. A trivial test that asserts nothing meaningful
is worse than an honest gap: it reads downstream as coverage that isn't there.

## Artifact shape

`test-authoring.md` carries five sections, kept even when short:
`Какое поведение покрыто`, `Файлы тестов`, `Вывод прогона`, `Допущения`,
`Заход`.
`Какое поведение покрыто` names each behaviour a test targets, tied to the
Plan, `scoping.md` or a `plan-review.md` note if any of them named it.
`Файлы тестов` lists the paths you
wrote or changed. `Вывод прогона` carries the failure line of each new test word for word —
not a description of it — so a reader sees the reason instead of taking your
word for its meaning. The whole run goes to
`.kandev/artifacts/$KANDEV_TASK_ID/logs/test-authoring.txt`, and this section
names that path.
`Допущения` holds what you decided where neither the Plan nor `scoping.md`
settled it, the `plan-review.md` notes you did not turn into tests and why,
and the `Нужны руки человека:` lines, or says plainly that there were none.
`Заход` says, past the first lap, what sent the card back here; the number
comes from `kd-state lap "Test Authoring"`.

## Finishing

Nobody watches this step while it runs, and a question left in your last
message stalls the task until a human happens to notice it. Decide what you
can decide from the Plan and `scoping.md`, write down what you assumed where
neither settled it, and before you stop, reread your last message — if it
reads as a plan to write tests rather than tests already written and run, do
that work now instead of describing it.

Base every line in `test-authoring.md` on a run you actually watched in this
session, not on what a test would probably do — a failure you didn't read yet
might be failing for the wrong reason. Where the repository leaves you no way
to test something, say that plainly instead of writing a test that only looks
like coverage.

Call `step_complete_kandev` once every test you wrote has a captured run
showing it failing for the right reason, your commit carries the
`Kandev-Step: Test Authoring` trailer, and `test-authoring.md` holds all five
sections — or, where no test could be written at all, an honest record of why
not.
