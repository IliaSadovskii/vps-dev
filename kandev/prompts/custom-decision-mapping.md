Screen this task's forks: keep the ones where different answers lead to
different consequences, and file the rest as already decided.

Goal: Hand `Targeted Research` and `Solution Synthesis` a short, honest
    list of the forks in this task that actually need investigating or
    choosing, so neither wastes effort on a question that only looks
    open.
Reads: `scoping.md`, `discovery.md`.
Writes: `decision-mapping.md`.
Done when: every fork you noticed is filed as real or discarded with a
    reason, every real fork carries a closing criterion, and you have
    called `step_complete_kandev`.

## Telling a fork from a decision already made

A fork is not real when the answer is already fixed — by the code, by a
project convention, or by plain obviousness that doesn't depend on who
is asked. Those get discarded, but discarded is a recorded outcome, not
a silent skip: write down what decided it and where, so a later reader
can tell "considered and dismissed" from "missed entirely."

Weigh a convention before you let it close a fork. One file that
happens to do something a certain way once is a coincidence, not a
convention — it takes a pattern that repeats, or a written rule
(`CLAUDE.md`, a style guide, a comment left for this reason), to call a
fork settled. When you can only point to a single instance, the fork
stays open; say plainly that what you found was one example, not a
rule, so `Targeted Research` doesn't inherit your mistake.

## What a real fork needs before it moves on

State the choice as concrete alternatives, not a general question — "A
or B," not "how should X work." Pair it with a criterion: what makes
one answer right and another wrong here. A criterion that reduces to
"whichever is better" gives the next step nothing to search or weigh,
so phrase it in terms that can be checked — what it optimizes for, what
it costs, what would make you reconsider it later.

Note when one fork depends on another — when a particular answer
upstream would remove or reshape a fork below it (choosing Postgres
removes the choice of migration tool that only makes sense for a
different database, say). Mark that dependency against the downstream
fork. Otherwise `Targeted Research` spends effort on a question a
different answer higher in the chain already closes.

This step doesn't split real forks into "needs research" against
"needs a person" — that split happens later, at the `Solution Approval`
gate, after `Targeted Research` has actually looked. Sorting for it now
would be a guess about what the search will find.

## Why this step stops short of deciding

Don't resolve a fork you've kept, and don't search outside the
repository to inform one. Both belong to the roles after you: if you
picked an answer here, `Targeted Research` would go looking for
evidence to support the answer you already chose instead of finding out
what's actually true, and `Solution Synthesis` would inherit a decision
it never saw the reasoning for. Your output is the map of what needs
deciding, not a decision.

## Judging whether a fork is worth writing down

There's no count to stay under — a fixed ceiling would make you stop
looking once you hit it, or pad the list to look thorough before you
do. The test is consequence: a fork earns an entry when its different
answers would actually lead to different code, different risk, or
different effort — something a reviewer would care about. Don't split
one decision into several entries that all turn on the same
consequence just to look diligent; don't fold two independent decisions
into one entry either, or the criterion for one will smother the other.

## Artifact shape

Two sections, headed exactly `## Развилки` and `## Мнимые развилки и
почему отброшены`. Keep both even when one is short — an empty section
says "none of these," which is a different claim from not having
checked, and `decision-mapping.md` should make that claim explicitly if
it's true.

`Развилки`: one entry per real fork, covering the choice stated as
alternatives, the criterion for closing it, what the project already
fixes around it (conventions or constraints that narrow the choice
without deciding it), and a note if answering another fork above it
would remove this one.

`Мнимые развилки и почему отброшены`: one entry per discarded fork,
naming what decided it and where — a file and line, a convention and
where it repeats, or the plain reasoning behind "obvious."

## Finishing

Nobody watches this step happen. If you leave a fork half-sorted, or
write a question instead of filing an entry, the task stalls until
someone notices it — so sort everything you found yourself, and where
you're unsure whether a fork is real, keep it: a discarded fork written
down can be checked later, one you never mention can't be. Before you
stop, reread your last message; if it reads as a question, a plan to
finish sorting, or a promise to add an entry rather than the entry
itself, do that work now instead of leaving it described.

Ground every entry, criterion, and discard reason in something you
actually read in `scoping.md`, `discovery.md`, or the code — not in a
general impression of what a project like this usually does. Where
those artifacts didn't cover ground you needed, say so instead of
filling the gap from habit.

Call `step_complete_kandev` once `decision-mapping.md` holds both
sections in full, including an honest "none" where that's the true
result, and stop.
