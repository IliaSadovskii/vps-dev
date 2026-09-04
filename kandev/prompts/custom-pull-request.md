Turn the finished change into a draft pull request that reads like it belongs
to this repository, then switch on automatic CI repair once the PR is linked.

Goal: Hand `Human Review` and whoever holds merge rights on the host a
  pull request they'd recognize as one of their own — draft, because no
  human has looked at this work yet, and a ready PR would pull reviewers
  in before that gate happens.
Reads: `scoping.md` for what this task covers and what was deliberately
  left out, `final-verification.md` for the literal output of what last
  ran, and `review-fixes.md`, if the route passed through review, for
  what changed as a result.
Writes: `pull-request.md`.
Done when: the PR exists on the host and `pull-request.md` records its
  URL and whether automatic CI repair is on, or — if creation failed —
  records that outcome and why, and `step_complete_kandev` has been
  called either way.

## The repository's template outranks yours

Check for `.github/pull_request_template.md` before drafting anything, along
with its common variants — `.github/PULL_REQUEST_TEMPLATE.md`,
`docs/pull_request_template.md`. If one exists, read it whole and build the
description inside its sections, not the shape described below: the template
records what this specific team agreed a PR description should contain, and
this step is a visitor to that agreement, not a party to it. Fall back to a
plain summary-plus-validation shape only when no template exists anywhere in
the repository.

## Title

Check whether this project actually writes Conventional Commits titles —
`git log --oneline -20` on the default branch shows you, rather than assuming
the convention because it's common elsewhere. If it does, match that form
(`type: description` or `type(scope): description`); this matters beyond
style, because on a squash merge the PR title usually becomes the commit
message and lands in release notes. If the project doesn't use that
convention, write a title that reads like the rest of its history instead of
importing one.

## What the description is built from

Draw content from what already exists rather than re-deriving it: `scoping.md`
for what this task covers and what was left out on purpose,
`final-verification.md` for what actually ran, and `review-fixes.md` for what
changed after review, if the route went through one. Nothing you didn't read
or run belongs in the description — claim only the testing
`final-verification.md` shows actually happened, and if the template has a
validation or testing section, fill it with that record, not with a "tests
passing" checkbox. Leave no template placeholder unfilled, and describe the
work no more favorably than the work itself does — whoever reads this is
deciding whether the change is worth their review time, not receiving a pitch
for it.

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
one: this step can run again if `Final Verification` sends work back through
`Review Fixes`, and a second draft would leave the review gate looking at two
open requests instead of one. Otherwise create it with this host's CLI —
`gh pr create --draft` on GitHub, `glab mr create --draft` on GitLab, matching
whichever this repository's remote actually is — and pass the draft flag
explicitly rather than relying on whatever the CLI defaults to today.

## Switching on CI auto-fix

Once the PR exists and is linked to the task, turn on automatic repair so a
failing check gets fixed without a human relaunching this chain: call
`update_task_pr_automation_kandev` (GitHub) with `repository_id` and
`pr_number` naming the PR you just created, or
`update_task_mr_automation_kandev` (GitLab) with `repository_id`,
`project_path`, and `mr_iid` naming the MR — either way pass
`auto_fix_enabled: true` scoped to that one PR, not the whole task, so the
call doesn't reach into some earlier PR the task still happens to be linked
to. If PR creation failed, leave the switch alone; there is nothing to attach
it to, and the failure belongs in `pull-request.md` instead.

## Artifact shape

`pull-request.md`:
- Ссылка на PR — the URL, or, if creation failed, what failed and why.
- Что вошло в описание — the sections you filled and where each one's
  content came from: the repository's template section names, or the
  fallback shape if there was no template.
- Включена ли автоматическая починка CI — on and scoped to this PR, off
  because creation failed, or off with the reason if you chose not to
  enable it.

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
