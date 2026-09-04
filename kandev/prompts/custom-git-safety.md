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
