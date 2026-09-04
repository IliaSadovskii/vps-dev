Write tests for the behaviour this task requires, and prove each one fails for
the right reason before any implementation code exists.

Goal: Leave a red test suite that pins down what "done" means for this task,
    so that `Implementation` — running next in this same session — has a
    target it cannot quietly redefine, and so that anyone who later reads the
    commit history or `test-authoring.md` can see the tests came first and
    failed on the missing behaviour, not on a mistake in the test itself.
Reads: The native Kandev Plan via `get_task_plan_kandev`, when this task went
    through `Planning` — the Quick route never runs `Planning`, so no Plan
    existing there is the expected state, not a gap to report; `scoping.md`
    for what this task covers and what it deliberately leaves out;
    `discovery.md` for how this project is built and what rules it states
    about itself, including how its tests are written and run; and the task's
    own conversation through `get_task_conversation_kandev`, since your
    context was cleared and anything a human said about this task lives only
    there.
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
asked you to cover. Where neither source settles a detail the test needs,
decide it yourself and record the assumption in the artifact rather than
leaving the test looser than the behaviour it's meant to pin down.

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
a point where it could check it. A test that passes on this first run tells
you nothing either: it means either the behaviour already exists or the test
isn't checking what you think it is, and either way it needs rewriting, not
keeping.

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

The trailer `Kandev-Step: Test Authoring` on your commit is what a script
checks later to confirm which step touched the test files — not a courtesy
note. A written rule against loosening a test, however plainly it's stated, is
read by exactly the agent that later wants to loosen that test to make a stuck
implementation pass; a rule that lives only in prose has no footing against
that pressure once the pressure exists. The trailer moves the check outside
the session where the pressure will show up, into `git log`, where it holds
regardless of what any later turn decides is convenient. Commit your test
files, and only your test files, under that trailer before this step ends.

## When there is no test to write

If the repository has no test runner and setting one up is beyond this task's
scope, or the behaviour genuinely cannot be exercised by a test — say that
plainly in `test-authoring.md` instead of writing a test that always passes to
fill the section. A trivial test that asserts nothing meaningful is worse than
an honest gap: it reads downstream as coverage that isn't there.

## Artifact shape

`test-authoring.md` carries three sections, kept even when short:
`Какое поведение покрыто`, `Файлы тестов`, `Вывод прогона`.
`Какое поведение покрыто` names each behaviour a test targets, tied to the
Plan or `scoping.md` if either named it. `Файлы тестов` lists the paths you
wrote or changed. `Вывод прогона` carries the actual terminal output of the
failing run for each test — not a description of it — so a reader can see the
failure reason for themselves instead of taking your word for its meaning.

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
`Kandev-Step: Test Authoring` trailer, and `test-authoring.md` holds all three
sections — or, where no test could be written at all, an honest record of why
not.
