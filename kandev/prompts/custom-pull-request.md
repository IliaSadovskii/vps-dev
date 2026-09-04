Turn the finished change into a draft pull request that reads like it belongs
to this repository, with everything the chain left unresolved stated up front.

Goal: Hand `Human Review` and whoever holds merge rights on the host a pull
    request they'd recognize as one of their own — draft, because no human has
    looked at this work yet, and a ready PR would pull reviewers in before
    that gate happens — and one that tells the reviewer first what the chain
    could not settle on its own.
Reads: `scoping.md` for what this task covers and what was deliberately left
    out, `plan-review.md`, `fix-review.md` and `final-verification.md` for
    what each left unresolved (and the last for the literal output of what
    last ran), `test-authoring.md` and `verification.md` for the assumptions
    and plan deviations no human has seen and for what needs a person's
    hands, `review-fixes.md` for what changed as a result of review and
    what was left unfixed (`review-fixes.md` and `fix-review.md` are absent
    when both reviews were clean and `Security Review` skipped the fix
    steps; then say so in the validation notes), the native Plan's
    «Проверки» through `get_task_plan_kandev` when the route ran
    `Planning`, for the kinds of
    check the owner declined or deferred, `documentation.md` for what the
    change left unexplained anywhere in the repository, and your own
    previous `pull-request.md` when the card has been through here before.
    You run in `Final Verification`'s context, which began empty; all of
    these are files to open, not memories.
Writes: `pull-request.md`; when «Отложено» is non-empty, one card in this
    workflow's `Backlog` for the deferred items.
Done when: the PR exists on the host and `pull-request.md` records its URL,
    or — if creation failed — records that outcome and why, and
    `step_complete_kandev` has been called either way.

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
here.

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
findings `review-fixes.md` left unfixed as minor, and what
`documentation.md` lists under «Что осталось незадокументированным и
почему». Each item with a pointer to the file it came from and, where
there is one, the path in the code.

A deferred item that lives only in a PR description dies with the PR. When
`Отложено` is non-empty, create one card in this workflow's `Backlog`
through `create_task_kandev`: title «Долг по PR <number>», with the number
the host assigned, a description listing the same items with their file
pointers, `workflow_step_id` the `Backlog` step from
`list_workflow_steps_kandev`, `source_task_id` this task, and
`start_agent: false`, so it waits for the owner instead of starting a
chain. On a repeat lap your previous `pull-request.md` says whether such a
card exists: if it records one, rewrite that card's description with
`update_task_kandev` (its `task_id` and the new `description`) rather
than creating a second; if it records none, create one. Either way,
`pull-request.md` records the card — its ID and title — or that none was
needed.

## What the rest of the description is built from

Draw content from what already exists rather than re-deriving it: `scoping.md`
for what this task covers and what was left out on purpose,
`final-verification.md` for what actually ran, `review-fixes.md` for what
changed after review, and `documentation.md`'s «Что осталось
незадокументированным и почему» for the reasoning this change carries that
had nowhere in the repository to live — this description is that reasoning's
only home. Nothing you didn't read or run belongs in the description — claim
only the testing `final-verification.md` shows actually happened, red
included, and if the template has a validation or testing section, fill it
with that record, not with a "tests passing" checkbox. Leave no template
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

## Draft, and checking before you open one

Confirm the branch is pushed before anything else here — nothing earlier in
this chain has guaranteed that, and a PR can't open against a branch the
remote doesn't have. Check whether a PR already exists for this branch
(`gh pr list --head <branch>`, or the equivalent on GitLab) before creating
one. This step runs again on every rework lap — a human unhappy at
`Human Review` sends the card back to `Review Fixes`, and the chain returns
here — so a repeat visit is the ordinary case, not an anomaly. Read your own
previous `pull-request.md` first when there is one: it holds the URL and what
the description was built from last time, and this lap's work is what changed
since. When a PR is already open for this branch, do not create a second one:
bring its title and description up to date with what changed since — the
four opening sections included, rebuilt from the current files — leave it
a draft, and
record that URL. Two open requests would leave the review gate reading
whichever one it happened to open. Otherwise create it with this host's CLI —
`gh pr create --draft` on GitHub, `glab mr create --draft` on GitLab, matching
whichever this repository's remote actually is — and pass the draft flag
explicitly rather than relying on whatever the CLI defaults to today.

Do not switch on the host's automatic CI repair for this PR. Its commits
would land after every review in this chain has already run, and a failing
check is for the human at the gate to see, not for a fixer to paper over.

## Artifact shape

`pull-request.md`:
- Ссылка на PR — the URL, or, if creation failed, what failed and why.
- Что вошло в описание — the sections you filled and where each one's
  content came from: the repository's template section names, or the
  fallback shape if there was no template, what «Не решено», «Решено без
  вас», «Нужны ваши руки» and «Отложено» contain, and the debt card —
  its ID and title, created or updated this lap — or that none was needed.
- Заход — this step's ordinal count on this task: 1 the first time, one
  more than your own prior `pull-request.md` shows on any later lap, and
  whether this lap created the PR or updated an existing one.

## Finishing

Nobody reviews this step before it acts — that is the point of staying draft —
so where a template section is ambiguous, decide what it's asking for rather
than leaving it as a question, and record what you assumed instead. Before you
stop, reread your last message: if it reads like a plan for opening the PR
rather than the PR already being open, do that work now instead of leaving it
there.

Every line in the description and every field in `pull-request.md` traces to a
file you read or a command you ran this session — the PR URL comes from
`gh pr create`'s own output, not from memory of having run it. Where something
in Reads was missing or stale, say so in `pull-request.md` rather than filling
the gap from assumption.
