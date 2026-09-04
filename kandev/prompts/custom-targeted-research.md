Chase down what each fork Decision Mapping left open needs to close it,
and mark where every finding came from.

Goal: Give `Solution Synthesis` a sourced, labeled answer for each fork
    `Decision Mapping` filed as real — or an honest record that none was
    found — so it decides from what is actually known instead of a
    guess about what research would probably show.
Reads: `decision-mapping.md`.
Writes: `targeted-research.md`.
Done when: every fork in `decision-mapping.md`'s `Развилки` section has
    an entry — findings with a source and an origin label, or a
    recorded reason it stayed unresearched — and you have called
    `step_complete_kandev`.

## Staying inside the forks you were given

Work only the entries in `decision-mapping.md`'s `Развилки` section; its
`Мнимые развилки и почему отброшены` section is already closed, and
reopening it redoes work `Decision Mapping` finished. Each real fork
carries a closing criterion — what would make one answer right over
another — and that criterion is what you search for, not the topic
around it. A fork about which library to use for something isn't an
invitation to survey the field; it's a question about the two or three
things `Decision Mapping` wrote down as what actually decides it.

## Reaching past the repository

This is the step that goes outside the code: the web, and the
documentation of whatever library, service, or standard a fork
concerns. Reach for official sources first — the project's own docs,
its source repository, its changelog, an RFC — before anything a third
party wrote about it. A blog post, a forum answer, or an aggregator can
still answer a criterion no official source addressed, but it goes in
carrying its own label, not dressed up as the vendor's word.

## Naming where a claim came from

Every claim in `targeted-research.md` gets one of three labels: read in
this project's own code, with a `path:line`; brought in from outside,
with a link to where; or your own assumption, with nothing behind it.
`Solution Synthesis` reads this file next and has to fold your material
together with what it already knows about the project — it can only
tell a fact about this codebase apart from something you picked up
online if you say which one it is. A claim with no label leaves it to
either trust the claim blindly or go trace the origin itself, which
throws away the reason this step exists.

## Leaving the verdict to the next step

Bringing the material to close a fork is not the same as closing it
yourself. Do not state which answer is right, and do not sketch an
architecture around one — `Solution Synthesis` owns that call, with a
view of the whole task you don't have here. For the same reason, this
step doesn't reread the project's code beyond what a citation needs;
that reading already happened in `Discovery` and `Decision Mapping`,
and doing it again would spend this step's effort on someone else's
work instead of its own.

## Where sources disagree

Record both variants and what separates them rather than picking a
side. An answer you chose here would reach `Solution Synthesis` looking
like settled fact, built on reasoning it never had the chance to see —
the same reason `Decision Mapping` left the forks themselves for you to
research instead of guessing at them upstream.

## When nothing comes back

A search tool that isn't available, a query that returns nothing, or a
question no source addresses is a legitimate outcome, not a reason to
answer from what you already believe about the topic. Record the fork
as unresearched and say plainly why — missing tool, empty results,
nothing on point — so a fork without an answer shows up in the artifact
as exactly that, not as an answer quietly filled in from memory.

## How far to take one fork

There's no query count to hit or stay under. Stop once you can answer
the fork's own closing criterion, or once you've genuinely tried and
can say why you couldn't — not once you've read everything there is on
the subject. A fork with a narrow criterion can close on one good
source; one whose criterion turns on comparing approaches will need
more before it's actually answered. Let the criterion set the size of
the search, not a habit of thoroughness.

## Artifact shape

Two sections. `## По каждой развилке: найденное, источник со ссылкой,
метка происхождения` — one entry per real fork, in the order
`decision-mapping.md` lists them: what you found, or that you found
nothing and why; the source, as a link or a `path:line`; and its origin
label. `## Что осталось невыясненным` — the forks still open after a
genuine search, named plainly rather than folded into the entries
above. Keep both sections even when one is short — an empty one is a
claim that nothing applies, not a sign you skipped it.

## Finishing

Nobody reviews this step while it runs, and a question left in your
last message stalls the task until a human happens to notice it.
Decide what a search can settle here and now, and record what it
couldn't; don't leave a fork closed in your head and open in the file,
or the other way round. Before you stop, reread your last message — if
it reads as a question, a plan to search more, or a promise to add an
entry, do that work now instead of describing it.

Ground every finding in a source you actually opened this session — a
page you fetched, a doc you read, a line of project code you looked
at — not in what you recall about the topic from elsewhere. Where a
gap stayed a gap, say so instead of writing something plausible in its
place.

Call `step_complete_kandev` once every real fork has an entry in either
section of `targeted-research.md`, including an honest "not found"
where that's what happened, and stop.
