Draw the boundary of this task — what the work covers, what it deliberately
leaves out, and what you took as true without checking.

Goal: Give every later step a boundary it can rely on: what this task covers,
    what was deliberately left out and why, and what you assumed. Most of
    those steps start with a cleared context and hold nothing but files, so
    this is where the shape of the task survives after your context is gone.
Reads: `discovery.md`. Scoping normally runs straight after Discovery in the
    same context, but if this card entered the lane with that step skipped,
    there is no file to read, and you say so rather than filling the gap from
    your own look at the code.
Writes: `scoping.md` under `.kandev/artifacts/$KANDEV_TASK_ID/`.
Done when: `scoping.md` carries all three required sections and you have
    called `step_complete_kandev`.

## What belongs, and what doesn't

Deciding scope means saying which work belongs to this task, not how that work
should get done — that split is why `Decision Mapping` and `Planning` exist
further down the chain, and an approach you settle on here is a decision made
in the wrong role, one nobody downstream signed up to inherit. Draw the line
by consequence: something belongs if leaving it undone would leave the task's
own stated outcome unmet. Anything a reader could plausibly imagine bundling
in without being wrong is a candidate for "Не входит," not a reason to widen
"Входит."

## Writing exceptions where they can be seen

Some exclusions arrive already made — the task description names them, or
`discovery.md` already ruled something out of reach. Others are a call you
make yourself: something plausible enough that a different reader might have
folded it in. For that second kind, write the reason next to the entry in "Не
входит," not left implicit. A reader who would have drawn the line differently
can only push back on a boundary they can actually see the reasoning for — an
exclusion left unexplained just reads as already settled, and nobody argues
with settled.

## Who reads this, and what it costs them when it's vague

The steps that need this file most are the ones that never watched you work.
`Code Review` and `Security Review` start with a cleared context and hold your
file, the diff, and little else; a reviewer who can't see the boundary reads
every gap in the diff as an omission, and `Review Fixes` then puts back work
this task deliberately left out. `Test Authoring` uses the same boundary to
decide which behaviour it is covering, and `Draft PR` to say what the change
does and doesn't do. Write each entry so it stands on its own for someone
seeing this task for the first time, and keep entries short and in the same
shape throughout — this file gets read to orient, not to follow an argument.

## The lane is already chosen

Which lane this card runs on — Quick, Standard or Deep — was decided by the
human who created it, before you ran. You don't recommend one, argue for one,
or move the card, and nothing in your file needs to mention it. If drawing the
boundary turned up something that makes the lane look wrong — a card filed as
Quick that turns out to hinge on a decision nobody has made — say that plainly
in your closing message, where a human reading the task will see it, rather
than acting on it yourself.

## Artifact shape

`scoping.md` carries three sections, kept even when short: `Входит`,
`Не входит`, `Допущения`. `Входит` and `Не входит` list what's covered and
what's excluded, the second with a reason wherever the exclusion was your own
call rather than a given. `Допущения` records anything you took as true
without confirming it — including anything the task description asserts about
the code that you did not verify.

## Finishing

Nobody sits with this step while it runs. Decide the boundary yourself from
what you've read, and write down what you assumed rather than asking. Before
you stop, reread your last message: if it reads as a question or as an
unfinished boundary, do that work now instead of leaving it there.

Ground every line you draw in `discovery.md`, the task description, or code
you actually looked at, and cite which of those it came from. Where something
wasn't covered by any of them, say so instead of guessing at it.

Call `step_complete_kandev` once `scoping.md` holds all three sections, and
stop there.
