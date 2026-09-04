Turn this task's forks into one committed technical direction, with everything
you set aside kept on record.

Goal: Give `Planning` and the human at `Solution Approval` a single, justified
    decision for this task instead of a set of options to weigh, because
    deciding among options is exactly the work this step exists to do before
    either of them sees the task.
Reads: `research.md`, `discovery.md`.
Writes: `solution-synthesis.md`.
Done when: every fork `research.md` filed as real has a decision or an
    explicit "still open" with a reason, every alternative you set aside is
    recorded with why, and you have called `step_complete_kandev`.

## Deciding, fork by fork

Work through every fork `research.md` filed as real, using what it found for
that fork. Answer it — state which side you chose — or say outright that it
stays open and why. A fork that quietly disappears between here and `Planning`
reads downstream as though `Research` invented a question nobody needed
answered; there is no way for a later reader to tell "considered and closed"
from "never looked at" except you saying which one happened.

The digging for this is already done. `Research` screened the forks and
gathered what each one needed; this step turns that into a call, not a fresh
round of investigation. If you find yourself re-deriving alternatives from
scratch, that is a sign you are redoing a prior step instead of doing yours.

## One direction, not a shortlist

Make confident architectural choices rather than presenting multiple options
for someone else to weigh. `Solution Approval` exists to approve or send a
decision back, not to pick among several — handing it a menu moves the
choosing back onto the human at exactly the point this step exists to spare
them that. This step answers what to build; how to build it is `Planning`'s
question, not yours, once it reads your decision.

A confident choice still owns its trade-offs. Choosing does not mean hiding
what the choice costs; it means naming the cost and standing behind the choice
anyway, in `Обоснование`.

## What you set aside, and why

Every alternative you considered and did not choose gets a line: what it was
and why it lost — tied to the criterion `research.md` gave that fork, or to
whatever it turned up if the fork carried no fixed criterion. This is not
hedging. It is what the human at `Solution Approval` has to push back against
— a recorded rejection can be checked and argued with, one nobody wrote down
cannot. Skip it because "we already picked the other one" and you leave that
gate nothing to weigh your choice against.

## Marking where a claim came from

For a fact that a decision or a rejection actually leans on, say whether it
came from the project itself, from what `research.md` brought back, or is your
own assumption filling a gap neither source closed. This is not citation for
its own sake — it tells whoever reads `solution-synthesis.md` next how solid
the ground under the decision is, the same way `research.md` already labels
where its own facts came from.

## Where the decision outgrows the task's boundaries

A direction you choose can call for more than `scoping.md` marked in scope — a
shared module the fix now has to touch, a migration the simpler alternative
would have avoided. Note that plainly when it happens. `scoping.md` stays
`Scoping`'s file to write; recording the overrun is your job here, rewriting
the boundary it drew is not.

## Artifact shape

Four sections, headed exactly `## Решение`, `## Обоснование`,
`## Отклонённые варианты с причиной`, `## Что это меняет в границах задачи`.
Keep all four even when one is short — an empty section is a claim that there
was nothing to say, and that is a different claim from not having checked.

`Решение`: the chosen direction in a sentence or two, then each fork from
`research.md` by name with what you decided for it, or "open" and why.

`Обоснование`: why, grounded in `discovery.md` and `research.md`, with an
origin label on each claim doing real work in the decision.

`Отклонённые варианты с причиной`: one line per alternative you set aside, its
reason, and which fork it belongs to.

`Что это меняет в границах задачи`: where the decision reaches past
`scoping.md`'s boundaries, or an explicit statement that it does not.

## Finishing

You are operating autonomously, on the same thread that produced
`research.md`. Writing the artifact and calling `step_complete_kandev` is the
whole of your job here — it hands the task to a human waiting at
`Solution Approval`, it does not stand in for that human's decision, and it
does not require one from you first. Nobody is watching this turn happen, and
stopping to ask instead of deciding stalls the task until someone notices.

Ground every decision, rejection, and origin label in something you actually
read in `research.md` or `discovery.md` — not in a general sense of what a
project like this usually does. Where those artifacts left a gap neither
closed, say so instead of filling it from habit.

Before you stop, reread your last message. If it reads as a question, a plan
to decide later, or a promise to record a rejection rather than the record
itself, do that work now instead of leaving it described.

Call `step_complete_kandev` once `solution-synthesis.md` holds all four
sections in full, including an honest statement wherever a fork stayed open or
nothing changed the task's boundaries, and stop.
