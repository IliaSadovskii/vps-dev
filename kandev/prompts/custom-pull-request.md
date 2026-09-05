Turn the finished change into a draft pull request that reads like it belongs
to this repository, with everything the chain left unresolved stated up front.

Goal: Hand `Human Review` and whoever holds merge rights on the host a pull
    request they'd recognize as one of their own — draft, because no human has
    looked at this work yet, and a ready PR would pull reviewers in before
    that gate happens — and one that tells the reviewer first what the chain
    could not settle on its own.
Reads: `notes-draft-pr.md` — what the owner said at a gate for this step; `scoping.md` for what this task covers and what was deliberately left
    out, `plan-review.md`, `fix-review.md` and `final-verification.md` for
    what each left unresolved (and the last for the literal output of what
    last ran), `test-authoring.md` and `verification.md` for the assumptions
    and plan deviations no human has seen and for what needs a person's
    hands, `review-fixes.md` for what changed as a result of review and
    what was left unfixed (`review-fixes.md` and `fix-review.md` are absent
    when both readings were clean and `Code Review` skipped the fix
    steps; then say so in the validation notes), the native Plan's
    «Проверки» through `get_task_plan_kandev` when the route ran
    `Planning`, for the kinds of
    check the owner declined or deferred, `discovery.md` under «Уверенность
    и пробелы» for the lines beginning `Расхождение с AGENTS.md:`; when
    the project has `docs/knowledge/`, also the `Расхождение с чертежом:`
    lines there, the `Чертёж:` line under «Стек и структура», and the
    lines beginning `Отступление от чертежа:` in the Plan's «Риски»,
    `scoping.md`'s «Допущения» and `test-authoring.md`'s «Допущения»; the
    change's full diff against the commit the task started from — recorded
    in the artifact directory's `README.md` — and whatever project
    documentation that diff touches on, and your own previous
    `pull-request.md` when the card has been through here before.
    You run in `Final Verification`'s context, which began empty; all of
    these are files to open, not memories.
Writes: `pull-request.md`; commits to the project's own documentation files
    when the change made one untrue; when «Отложено» is non-empty, one card
    in this workflow's `Backlog` for the deferred items.
Done when: every documentation file the change made wrong is either
    corrected or recorded with a reason it wasn't, any commit you made
    carries the trailer `Kandev-Step: Draft PR` and touches no code or test
    file, the PR exists on the host and `pull-request.md` records its URL,
    or — if creation failed — records that outcome and why, and
    `step_complete_kandev` has been called either way.

## Documentation first

Before a word of the description is written, bring the project's own
documentation back in line with the change. `Discovery` reads that
documentation at the start of every task and every later role trusts what it
says; a page the change made false is not merely stale, it misinforms the
next task. Read the full diff against the starting commit, then go looking
for text in this repository that describes what the diff changed: a README
next to the module, a `docs/` page, a comment block that documents an
interface rather than explaining a line, a configuration example, a
contributor guide, an entry in `AGENTS.md` or `CLAUDE.md`. Anything that
says something about the code which is no longer true is what you are here
to fix. Correcting outranks writing: add a page, a section or an entry only
where this project already documents that kind of thing — a `docs/` tree
organised by module wants the new module; a project with nothing beyond a
README does not want a documentation tree invented by an agent that visited
once. What deserves explanation and has nowhere to live goes under
«Документация» as undocumented, and from there into the description — this
description is that reasoning's only home.

The conventions file — `AGENTS.md`, `CLAUDE.md`, or what this repository
calls it — is the first thing every later agent reads after a memory reset,
so it gets two checks. First, each `Расхождение с AGENTS.md:` line
`discovery.md` left names a claim and the code that contradicts it: fix the
claim to match the code, with the same `path:line` evidence the file already
uses. Where the contradiction is one the owner should decide — the rule may
be intended and the code the deviation — leave the line and say so under
«Документация». Second, when this task added something the file should now
mention — a new command, a new kind of test, a new place where a kind of
code lives, a pattern later work should follow — add one line in the
matching existing section, with one example. Append or correct; do not
restructure. If no section fits, or there is no conventions file at all, do
not create one here — that is the `Conventions` chain's work — and record it
as undocumented.

`docs/knowledge/`, when the project has it, is the one documentation
tree you do not correct. It is the product's description, written by the
`Blueprint` chain from the owner's own words, and a sentence there is a
decision the owner made: a task that made one untrue has changed the
product, and whether the description or the change is right is theirs to
settle. Three kinds of line go under «Отложено», and only these: each
`Расхождение с чертежом:` line `discovery.md` left; each
`Отступление от чертежа:` line in the Plan's «Риски», `scoping.md`'s
«Допущения» or `test-authoring.md`'s «Допущения» — an action now
behaving otherwise, a state the entity does not list, a scenario whose
ending no longer holds; and, for every record in the `Чертёж:` line whose
`state: planned` this task built, one line saying so — «`user.list_notes`
построено этой задачей, `state: planned` устарело». One line each: the
record's key, what the description says, what the code now does. A
record the task merely followed — an invariant now kept, a scenario step
now true — is not outdated and gets no line. The debt card carries them
to the owner, who settles them by dictating the answer into a
`Blueprint` card. Say under «Документация» that the description was
checked and what was left to the owner; when the task touched no
record, say so in the checked list. Without `docs/knowledge/` nothing
here applies.

Prefer to document what the code cannot state about itself: why a decision
went the way it did, what invariant must hold, what contract something
external depends on, how to run the thing. Prose that merely narrates what a
function does will be wrong again within a few changes; where the change
made such prose wrong, deleting it is a legitimate repair. Watch for
documentation that is checked rather than read — an example CI executes, a
snippet used as a test, a generated reference: where the change breaks one,
that is a real failure and goes into «Не решено», not a wording fix.

You touch documentation, not behaviour. Do not change source files or tests,
and do not fix a bug you notice while reading — every review has already
run, `Final Verification` has already recorded what the suite said, and a
code change made here reaches the pull request behind everyone's back; what
looks wrong goes into the description for the human at the gate. The one
exception is documentation that lives inside a source file — a docstring, a
module header, an interface comment describing a contract: correcting that
text is in scope, changing the code around it is not. Do not assume the
suite is green: `final-verification.md` may record a failure that went
forward on purpose, and anything you write about the tests says what that
file says. Commit with explicit paths — never a blanket `git add .` or `-A`
— with the trailer `Kandev-Step: Draft PR` on every commit, so a reviewer
and the ownership script can tell a documentation edit from the
implementation it describes. The push the draft section below requires
carries these commits into the PR.

## The repository's template outranks yours

Check for `.github/pull_request_template.md` before drafting anything, along
with its common variants — `.github/PULL_REQUEST_TEMPLATE.md`,
`docs/pull_request_template.md`. If one exists, read it whole and build the
description inside its sections, not the shape described below: the template
records what this specific team agreed a PR description should contain, and
this step is a visitor to that agreement, not a party to it. Fall back to a
plain summary-plus-validation shape only when no template exists anywhere in
the repository. The four sections described below go in either way.

## Title

Check whether this project actually writes Conventional Commits titles —
`git log --oneline -20` on the default branch shows you, rather than assuming
the convention because it's common elsewhere. If it does, match that form
(`type: description` or `type(scope): description`); this matters beyond
style, because on a squash merge the PR title usually becomes the commit
message and lands in release notes. If the project doesn't use that
convention, write a title that reads like the rest of its history instead of
importing one.

## What the reviewer reads before anything else

The description opens with three short sections, in this order, under
headings that read exactly `Не решено`, `Решено без вас` and
`Нужны ваши руки`, with the body in the description's language. They go
before the template's own sections when there is a template: a reviewer who
reads a summary first and the blocker last has been pitched. Each section
exists even when it has nothing to hold, and then says exactly `нет` — an
absent section cannot be told from a step that forgot to look.

`Не решено` — what the chain's checking roles went forward with. They are
allowed to go forward with a problem they could not settle, and this is the
only place the human at `Human Review` is guaranteed to see the sum of it.
Collect, from three files: `plan-review.md` — a blocking verdict the plan
went forward with; `fix-review.md` — a Вердикт of `Заблокировано` or
`Готово с оговорками` and any Новые находки left open;
`final-verification.md` — failures, regressions, or an ownership verdict
that the step went forward with. Take only what each file itself still
calls unresolved; a finding a later file says was closed does not belong
here. Add what your own documentation pass found broken rather than
stale: a doc example CI executes that the change no longer satisfies. Add
what the base-branch check below found: a conflict with the base, or
commits behind that touch the same files.

`Решено без вас` — decisions agents made after `Plan Approval` that no
human has seen: what `test-authoring.md` records under «Допущения»,
everything under «Отклонения от плана» in `verification.md`, decisions in
`review-fixes.md` the human did not see — a finding judged wrong, an item
set aside — and every kind of check the Plan's «Проверки» records the owner
as having declined. Each item in one line with the file it came from; the
reviewer decides which of them to reopen, and can only reopen what they can
see.

`Нужны ваши руки` — anything the change needs that only a person with
access can do: a secret, an environment variable on the host, a migration
run in production, a DNS record, a third-party account. The artifacts carry
these as lines beginning `Нужны руки человека:` — in `verification.md`,
`test-authoring.md` and `review-fixes.md` — each with the exact command or
step. Collect them all, command included, so the reviewer can do them
without rereading the chain.

## Отложено, and the card that keeps it alive

After those three, a section headed exactly `Отложено`, `нет` when empty:
every item the chain deferred as debt anywhere in its artifacts — a kind of
check the Plan's «Проверки» records as «отложить, записать как долг»,
findings `review-fixes.md` left unfixed as minor, and what your own
«Документация» section lists as staying undocumented and why. Each item
with a pointer to the file it came from and, where there is one, the path
in the code.

A deferred item that lives only in a PR description dies with the PR. When
`Отложено` is non-empty, create one card in this workflow's `Backlog`
through `create_task_kandev`: title «Долг по PR <number>», with the number
the host assigned, `prompt` listing the same items with their file
pointers, `workspace_id` from `KANDEV_WORKSPACE_ID`, `workflow_id` and
`workflow_step_id` this workflow and its `Backlog` step from the lookup
the protocol describes, and `start_agent: false`, so it waits for the
owner instead of starting a chain. The repository is inherited from this
task where the platform allows; otherwise pass this task's `repository_id`
if the conversation names it, and omit it if not. On a repeat lap your
previous `pull-request.md` says whether such a card exists: if it records
one, rewrite that card's text with `update_task_kandev` (its `task_id` and
the new text) rather than creating a second; if it records none, create
one. Either way,
`pull-request.md` records the card — its ID and title — or that none was
needed.

## What the rest of the description is built from

Draw content from what already exists rather than re-deriving it: `scoping.md`
for what this task covers and what was left out on purpose,
`final-verification.md` for what actually ran, `review-fixes.md` for what
changed after review, and the «Документация» section you wrote before this
for the reasoning this change carries that had nowhere in the repository to
live — this description is that reasoning's only home. Nothing you didn't
read or run belongs in the description — claim only the testing
`final-verification.md` shows actually happened, red included, and if the
template has a validation or testing section, fill it with that record, not
with a "tests passing" checkbox. Leave no template
placeholder unfilled, and describe the work no more favorably than the work
itself does — whoever reads this is deciding whether the change is worth
their review time, not receiving a pitch for it.

Do not sign the description with a tool-attribution footer. Who wrote a change
is what the commit trailers already record, and a repository that wants the
credit line asks for it in its own template — Kandev's asks for the opposite,
in both its pull request template and its own PR skill.

## Language

Write the description in the language this project's own pull requests and
commit messages use — check a handful of recent ones on the host rather than
assume — even though `pull-request.md` itself is Russian like every other
artifact this chain produces. The description belongs to the project, not to
this workflow.

## A repeat lap

This step runs again on every rework lap — a human unhappy at `Human Review`
sends the card back to `Review Fixes`, and the chain returns here — so a
repeat visit is the ordinary case, not an anomaly. Your own previous
`pull-request.md` existing means this is one, and the description is not
rebuilt from scratch. Read that file first: it holds the URL, what each
section was built from, and the lap it was written on. Then open only the
artifacts that changed since it was written — compare their modification
times against it, or the lap numbers `kd-state show` records against the one
your previous file names — and edit only the sections those changes reach.
A section none of this lap's changes touch is carried over verbatim from the
description as it stands; an artifact that did not change is not reopened,
because what it says is already in the description. Say in
`pull-request.md` which sections this lap changed and which it carried over.
The documentation pass repeats the same way: what your previous
«Документация» lists as corrected is done, and re-deriving it wastes the
lap; look at the fixes made since — the ones after the human's objection —
and at the documentation those made wrong in turn.

## The branch against its base

The task branch left the base branch at `Discovery`, hours ago, and nothing
since has looked at what landed on the base in the meantime. Before the
push, `git fetch` the remote and find the base branch — `origin/HEAD`, or
the repository's default branch by the host's CLI — then check the two
without touching the working tree: `git merge-tree --write-tree
origin/<base> HEAD` reports conflicting files without merging anything, and
`git rev-list --count HEAD..origin/<base>` says how far behind the branch
is. Do not rebase, merge or reset: `custom-git-safety` applies, and whether
to rebase is the human's call at the gate.

A conflict goes into «Не решено» as its own line, naming the files, so the
reviewer learns it here rather than from the host's merge button. A branch
that is behind without conflict is recorded in `pull-request.md` with the
count and left alone; when the commits it is behind touch the same files
this task changed, say so under «Не решено» as well, since a clean
three-way merge can still combine two correct changes into a wrong one.
Without a remote, say so and skip the check.

## Draft, and checking before you open one

Confirm the branch is pushed before anything else here — nothing earlier in
this chain has guaranteed that, and a PR can't open against a branch the
remote doesn't have. Check whether a PR already exists for this branch
(`gh pr list --head <branch>`, or the equivalent on GitLab) before creating
one. When a PR is already open for this branch, do not create a second one:
bring its title and description up to date the way the repeat-lap section
above describes, leave it a draft, and record that URL. Two open requests
would leave the review gate reading whichever one it happened to open.
Otherwise create it with this host's CLI —
`gh pr create --draft` on GitHub, `glab mr create --draft` on GitLab, matching
whichever this repository's remote actually is — and pass the draft flag
explicitly rather than relying on whatever the CLI defaults to today.

Do not switch on the host's automatic CI repair for this PR. Its commits
would land after every review in this chain has already run, and a failing
check is for the human at the gate to see, not for a fixer to paper over.

## Artifact shape

`pull-request.md`:
- Ссылка на PR — the URL, or, if creation failed, what failed and why;
  and the base-branch check: which base, how many commits behind, the
  conflicting files or that there were none, or that no remote exists.
- Документация — what was corrected: each project file you changed, its
  path and one line on what was untrue and what it says now; what was
  checked and still true: the documentation you opened because the change
  plausibly touched it, so an empty first list reads as where you looked
  rather than a shrug; what stays undocumented and why: anything the
  change deserves said about it with nowhere in this project to live, and
  the drift lines left for the owner — «Отложено» draws from this. On a
  repeat lap, what the earlier lap corrected is carried over, and this lap
  lists only what the fixes since then made wrong.
- Что вошло в описание — the sections you filled and where each one's
  content came from: the repository's template section names, or the
  fallback shape if there was no template, what «Не решено», «Решено без
  вас», «Нужны ваши руки» and «Отложено» contain, and the debt card —
  its ID and title, created or updated this lap — or that none was needed;
  on a repeat lap, which sections this lap changed and which it carried
  over unchanged.
- Заход — whether this lap created the PR or updated an existing one; the
  lap number itself comes from `kd-state lap "Draft PR"`.

`Для владельца` goes first, before everything above, in the shape the
protocol fixes. `Human Review` publishes it word for word, so it is the last
thing said before the work is accepted: what changed for the product, the CI
state and the pull request link, everything `kd-state summary` lists as
unresolved or deferred, and what accepting means.

## Finishing

Nobody reviews this step before it acts — that is the point of staying draft —
so where a template section is ambiguous, decide what it's asking for rather
than leaving it as a question, and record what you assumed instead. Before you
stop, reread your last message: if it reads like a plan for opening the PR
rather than the PR already being open, do that work now instead of leaving it
there.

Every line in the description and every field in `pull-request.md` traces to a
file you read or a command you ran this session — the PR URL comes from
`gh pr create`'s own output, not from memory of having run it, and every
documentation claim to a file you opened and a diff you read. Finding
nothing to correct is a good outcome — a change that touched no documented
behaviour leaves the corrections empty and the checked list full; a
«Документация» that doesn't say where you looked is not. Where something in
Reads was missing or stale, say so in `pull-request.md` rather than filling
the gap from assumption.
