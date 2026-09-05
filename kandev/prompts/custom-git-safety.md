Working with git in this repository.

This repository is edited on the machine it is deployed to, and a human works
in the same tree. Uncommitted changes you did not make are normal there, and
they are somebody's unsaved work. The commands below destroy it without
confirmation and without a way back, so this is one of the few places where
the exact sequence matters more than your judgement of the situation.

Never run `git checkout -- .`, `git checkout .`, `git reset --hard`,
`git clean -fd`, or `git stash --include-untracked`.

When you need to revert files a formatter or linter touched, name the paths
explicitly — `git checkout -- path/to/file path/to/dir/`. A bare `.` or an
unscoped glob takes the human's work with it.

Treat any uncommitted or untracked change you did not make as intentional and
leave it alone. Do not aim for a clean tree; aim for none of your own edits
being uncommitted.

Read before you write history. `git log`, `git show`, `git blame` and
`git diff` are how you find out why code looks the way it does, and they
change nothing.

If the repository is not where the process started, pass the path explicitly
with `git -C <path>` rather than assuming the current directory.

## A sibling repository the project points at

Project conventions often send you to a repository next door — «read
`../listate-internal/docs/CRM-RULES.md` before working here». In a task with
that repository attached it is where the path says, beside your own working
copy. In a task without it the path resolves to nothing.

That is not the same as «unavailable», and stopping there costs a round trip
through the human for something you could have read. The repositories of this
machine live in `/projects/<имя>`, checked out at their main branch. So when a
relative path to a sibling does not resolve, look for the same repository at
`/projects/<имя>` and read it there.

Two conditions, both absolute. **Read only** — never write, never commit,
never run anything that touches its tree; it is somebody's working copy and
not part of your task. And **say where you read it**: that checkout is at its
own branch and may be newer or older than what your task expects, so an
artifact citing it names the path you actually opened. If the repository is
neither beside you nor in `/projects`, then it really is unavailable — say so
plainly and work with what the task gives you.
