Bring this project's own documentation back in line with the change that just
landed — correcting what the change made false, and adding only what this
project already documents.

Goal: Leave the repository's documentation true about the code as it now
    stands, so the next person or agent reading it is not led by a description
    of how things used to work. `Discovery` reads that documentation at the
    start of every task and every later role trusts what it says;
    documentation that drifted is not merely stale, it actively misinforms the
    work that comes after it.
Reads: `review-fixes.md` and `final-verification.md` are already in this
    context — you continue the turn they ran in. What you have to look at
    yourself is the change: its full diff against the commit the task started
    from, recorded in the artifact directory's `README.md`, and whatever
    documentation that diff touches on.
Writes: `documentation.md` under `.kandev/artifacts/$KANDEV_TASK_ID/`, plus
    commits to the project's own documentation files when there is something
    to correct.
Done when: every documentation file the change made wrong is either corrected
    or recorded with a reason it wasn't, `documentation.md` holds its three
    sections, any commit you made carries the trailer
    `Kandev-Step: Documentation` and touches no code or test file, and you
    have called `step_complete_kandev`.

## Correcting outranks writing

The work here is repair first. Read the diff, then go looking for text in this
repository that describes what that diff changed — a README next to the
module, a `docs/` page, a comment block that documents an interface rather
than explaining a line, a configuration example, an entry in `CLAUDE.md` or a
contributor guide. Anything that says something about the code which is no
longer true is what you are here to fix.

Writing something new is the smaller half and has a higher bar: add a page, a
section or an entry only where this project already documents that kind of
thing. A project with a `docs/` directory organised by module documents
modules — a new module belongs there. A project with no documentation beyond a
README does not want a documentation tree invented for it by an agent that
visited once. When the change deserves explanation and this project has
nowhere that explanation belongs, say so in `documentation.md` and leave it
for the pull request description, which is where `Draft PR` puts the reasoning
behind a change.

## What documentation is for, and what it isn't

Prose that restates what the code says will be wrong again within a few
changes, and this step is where that cycle either continues or stops. Prefer
to document what the code cannot state about itself: why a decision went the
way it did, what invariant must hold, what contract something external depends
on, how to run the thing. Where you find existing prose that merely narrates
what a function does, and the change made it wrong, deleting it is a
legitimate repair — the shortest true documentation beats a longer one that
has to be maintained against every edit.

Watch for the documentation that is checked rather than read: an example in a
doc that CI executes, a snippet used as a test, a generated reference. Where
the change breaks one of those, it is a real failure and belongs in
`documentation.md` plainly, not a wording fix.

## Staying out of the code

You touch documentation, not behaviour. Don't change source files, don't
change tests, and don't fix a bug you notice while reading — the review steps
have already run, the suite has already been run green by
`Final Verification`, and a code change made here goes to the pull request
behind everyone's back. Something you notice that looks wrong goes into
`documentation.md` as an observation for the human at the review gate.

The one exception is documentation that lives inside a source file: a
docstring, a module header comment, an interface comment that describes a
contract. Correcting that text is documentation work and is in scope. Changing
the code around it is not.

## Commits

Commit with explicit paths — never a blanket `git add .` or `-A` — and carry
the trailer `Kandev-Step: Documentation` on every commit you make. That
trailer is what lets a reviewer, and the script that checks who touched what,
tell a documentation edit apart from the implementation it describes.

## Artifact shape

`documentation.md` carries three sections, kept even when short:

`## Что исправлено` — each documentation file you changed, with its path and
one line on what was untrue and what it says now.

`## Что проверено и осталось верным` — the documentation you looked at because
the change plausibly touched it, and which turned out to still be accurate.
This is what makes an empty first section a claim rather than a shrug: it says
where you looked.

`## Что осталось незадокументированным и почему` — anything the change
deserves said about it that has nowhere in this project to live, plus anything
you deliberately left alone. Whoever writes the pull request description reads
this.

## Finishing

Nobody is watching this turn, and finding nothing to correct is a perfectly
good outcome — a change that touched no documented behaviour leaves the first
section empty and the second one full. What is not a good outcome is an empty
file that doesn't say where you looked.

Base every claim on a file you actually opened this session and a diff you
actually read, not on what the change was supposed to have done. Before you
stop, reread your last message: if it describes documentation you intend to
correct rather than corrections you already committed, do that work now
instead of describing it.

Call `step_complete_kandev` once `documentation.md` holds its three sections
and every correction you made is committed, and stop.
