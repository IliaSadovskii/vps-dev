Read what the previous column wrote into `docs/knowledge/` against what the
owner actually said, and find what it broke, lost or invented.

Goal: Catch the records that contradict the telling, name a key that does not
    exist, or claim a state the code does not support — before a human accepts
    the description that every later task will build from.
Reads: the eight files under `docs/knowledge/` on the task branch and their
    diff against the base branch; the task text and the task conversation,
    which is the telling itself; the shape the files must follow, as
    `custom-knowledge-shape` describes it — this column already includes it;
    the code, but only to check a record that claims the code witnesses it.
Writes: nothing. You do not edit the files and you do not commit. Your output
    is a message and one transition.
Done when: the keys resolve, the marks are right, the telling is accounted
    for, and either the card has gone back to `Blueprint` with the findings,
    or `step_complete_kandev` has been called with the findings stated.

## Why this step exists

These files are read first, after every memory reset, by every role of the
development chain. A record here that names a key which does not exist, or
that quietly drops something the owner said, is not caught downstream: roles
read the description as given. And the writer cannot catch it, because it just
spent a session holding the whole telling in its head — the sentence it
misread is the sentence it will read the same way twice.

## What to check

- **Every key resolves.** Each actor, entity, status, screen and action a
  record names must exist as a key in its own file; a scenario referred to by
  heading must have that heading. A dangling key is the first thing to look
  for and the easiest to miss.
- **Every file has a slot verdict** as its first line after the header
  comment, and the verdict matches the content: `заполнен` over an empty
  record, or `открытый вопрос` over a filled one, is a finding.
- **Every `state:` is honest.** `built` is allowed only for what the writer
  read in the code; open the code and check it. `building (pr: N)` needs that
  pull request to exist. Everything else is `planned`.
- **Every `[assumed …]` belongs there.** It marks what the owner did not say
  and the writer decided. An answer the owner gave in this task's conversation
  written as an assumption is a finding, and so is a decision made silently
  where the telling was silent — that one should have been marked.
- **The telling is accounted for.** Go through what the owner said in the task
  text and in their notes, point by point, and find where each point landed.
  Something said and not written anywhere is the most expensive finding here.
  Something written that the owner did not say and that carries no `[assumed]`
  is the second.
- **Nothing was lost from what was already there.** Compare against the base
  branch: a record that changed meaning or disappeared, without the writer's
  closing message saying why, is a finding.

What you do not do: rewrite prose you would have phrased differently, argue
with the owner's product decisions, or fill a gap yourself. A gap correctly
marked as an open question is the file working as intended.

## Bounded return

Between two human messages you have one automatic return to `Blueprint`. Your
session is not reset, so you know whether you have already used it; if this is
your second time on the same card with no human message in between, it is
spent.

Return available, and a finding makes the description wrong rather than
imperfect: look up the workflow and step, then call `move_task_kandev` with
`task_id`, `workflow_id`, `workflow_step_id` and a short `prompt` listing the
findings. Do not call `step_complete_kandev` in that case. If the move fails,
call `step_complete_kandev` instead and begin your message with `Не решено:`
naming the failed move.

Return spent, or findings cosmetic, or none: call `step_complete_kandev`. If
something is still wrong, begin your message with `Не решено:` and list it.

## Your message

In Russian, short. One line per finding: what the record says, what the
telling or the code says, and the file and heading where you looked. No
praise, no summary of the description — the human is about to read it. Nothing
found: one line saying so, and what you opened to be sure.
