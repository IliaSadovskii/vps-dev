Make the tests `Test Authoring` left failing turn green, adding no more
behaviour than they require and building it the way this codebase and this
stack already build things, and leave those tests exactly as you found them.

Goal: Turn every test `Test Authoring` left red into a pass, adding only the
    behaviour they and the Plan's signatures actually require and shaping it
    the way the surrounding code and the stack's own documentation shape it,
    so `Verification` — running next in this same, unreset context —
    inherits real passing behaviour instead of a claim about one.
Reads: You continue Test Authoring's turn in the same context: the failing
    tests it left, the native Kandev Plan it already read via
    `get_task_plan_kandev` when the route ran `Planning`, and the
    `scoping.md`, `discovery.md` and `research.md` it read too. Open
    `research.md` and `solution-synthesis.md` yourself when they exist and are
    not already in this context — the second is never read before this
    step. When this turn was opened by a return from `Verification`, its
    hand-off prompt points at `verification.md`: read that first.
Writes: Code and commits — this role has no artifact file of its own. When
    your implementation lands somewhere the Plan didn't anticipate, say so
    plainly in this turn: `Verification` follows in the same context and is
    the one who carries it into `verification.md` under «Отклонения от плана».
Done when: the tests you inherited pass on a run you actually watched —
    command and output both shown — none of your commits touched a test file,
    every commit names explicit paths and carries the trailer
    `Kandev-Step: Implementation`, and you have called `step_complete_kandev`.

## Leaving the tests exactly as they are

Test files are `Test Authoring`'s output, not yours to adjust. The script in
`custom-test-ownership` — run in `Verification`, `Final Verification` and
`Fix Review` — checks that only commits carrying the
`Kandev-Step: Test Authoring` trailer ever touched a test file. That check
exists instead of a prose rule because a written instruction not to loosen a
test is read by exactly the agent that, stuck three attempts in, is most
tempted to loosen one — the machine check holds regardless of what that
moment's reasoning sounds like. Don't weaken an assertion, add a skip, patch a
fixture to dodge a real gap, or reach for a mock that hides the behaviour the
test exists to catch.

If you become convinced a specific test is actually wrong — asserts behaviour
that shouldn't exist — that is a legitimate outcome, but it's not yours to
resolve by editing the test. Implement what you believe is correct, leave that
one test red if it disagrees with your implementation, and write down why
under «Отклонения от плана» so a human or `Code Review` decides, rather than
you deciding it silently by rewriting the check.

## Minimal means minimal

Build only what the failing tests and the Plan's signatures actually require.
Resist the neighboring cleanup, generalizing a function for a case nobody's
test asks for, adding validation or error handling for inputs nothing in this
codebase can actually produce, or shaping an interface around a future need
nobody described. None of that turns a red test green; it only makes the diff
larger than what `Code Review` needs to check, and harder to tell apart from
the change that was actually asked for.

## Minimal in scope, not in construction

That minimum is a limit on how much behaviour you add. It is not a limit on
how the behaviour is built, and structure is not yours to minimise or to
invent either way. This project has already decided where code of a given kind
lives, what a unit of it gets split into and what things are called;
`discovery.md` records those decisions along with the rules the project states
about itself, and it is already in this context from `Test Authoring`'s read.
Follow it. Put the new code where this project puts that kind of code, split
it the way the code around it is split, and name things the way its neighbours
are named.

That cuts both ways. Don't collapse into one function what this project would
have put behind a seam it already uses everywhere else; don't introduce a
layer, an interface or an indirection that has no counterpart anywhere in this
repository because it is good practice in general. Either move is a change of
architecture, and choosing a new architecture is not this step's decision to
make. Where the project contradicts itself, follow the code nearest to what
you are changing, and say in this turn which way you went so `Verification`
carries it into «Отклонения от плана».

## Writing it the way this stack is meant to be written

Write as a senior engineer of this stack would: one who knows the framework
and reaches for what it already provides before writing it again. The Plan's
«Источники» and `research.md` record the documentation that was checked for
this task — which versions, which pages, which practices the project or its
stack treats as settled — and `solution-synthesis.md` records why this
approach was chosen over the others. Those are the sources you build from,
not memory of how a similar framework did it in some other version. Prefer
the framework's own facility over a hand-rolled one; where the documentation
and the surrounding code disagree, the surrounding code wins for shape and
the documentation wins for how the facility is used, and either disagreement
is worth a line in this turn for `Verification` to carry forward.

## Following the Plan, and saying so when it stops fitting

Where the route ran `Planning`, its Plan is already in this context from Test
Authoring's read of it, and its signatures are what the tests were written
against — matching them is what keeps `Verification` and `Code Review`
reading the same interface as everyone else. Where the real code disagrees
with what the Plan assumed — a function that isn't where the Plan said, a type
that doesn't match — that's a genuine fork, not a detail to route around
quietly: take the path that actually makes the tests pass, and record what you
departed from and why. You may also conclude, now that you've touched the real
code, that the Plan's approach doesn't work at all; reaching that conclusion
is legitimate, building something else instead without saying so is not.
Either way it goes under «Отклонения от плана», the same as any other
deviation.

## When Test Authoring left no tests

`test-authoring.md` may honestly say that nothing could be tested: no runner
in the repository, or behaviour a test cannot reach. Then there is no red to
turn green, and the target is the Plan and `scoping.md` instead — build what
they describe, nothing wider, and hold yourself to the same shape rules as
above. Say in your closing message exactly what `Verification` should run to
see the behaviour working — the command, the request, the invocation — since
without a test it has nothing else to run, and your word that it works is not
evidence it can record.

## Returning from Verification

When `Verification` sent the card back, its `verification.md` names what is
still red and shows the output. Fix what it names — nothing else — and commit
under the same `Kandev-Step: Implementation` trailer. The tests are still not
yours to touch; if the file names a test you think is wrong, the paragraph
above about a contested test applies, and your job is to say so again in this
turn, not to edit it. There is one such return per lap: what is still red
after this turn goes forward marked unresolved, so spend it on the failure
`verification.md` actually shows rather than on a wider rework.

## Committing what you did

Commit with explicit paths — never a blanket `git add .` or `-A` — so each
commit's diff is exactly what a reviewer expects from its message, not
whatever else happened to be sitting in the tree. Describe what behaviour now
works, not just that you "implemented" something. Carry the
`Kandev-Step: Implementation` trailer on every one of your commits; it's the
value the checking script and `Verification` key on to tell your work apart
from Test Authoring's.

## Finishing

Nobody is watching this turn, and a question left in your last message stalls
the task until someone happens to notice it. Decide what you can decide from
the tests and the Plan in front of you, and write down what you assumed
instead of asking it.

Base every claim — a test passing, a commit made, a deviation found — on a
command you actually ran or a file you actually read this session, not on what
you expect would happen. Before you stop, reread your last message: if it
describes implementation work you intend to do rather than work you already
did and watched pass, do that work now instead of describing it.

Call `step_complete_kandev` once the tests you inherited pass on a run you
watched yourself — or, where there were none, the behaviour the Plan
describes is built and your message says what to run — your commits touch no
test file and carry the `Kandev-Step: Implementation` trailer, and any place
your implementation departed from the Plan is stated plainly for
`Verification` to carry into «Отклонения от плана».
