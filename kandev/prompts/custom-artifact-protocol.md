How steps in this workflow hand work to each other.

Each step is a separate agent turn. Some steps start with a cleared context
and receive nothing but files. What you leave behind is therefore the whole of
what the next step gets — not a convenience, the entire channel.

## Where the files live

The task's working directory is `.kandev/artifacts/$KANDEV_TASK_ID/`, using
the full task ID from the environment. The ID is stable; the task title is
not, so never key anything on the title.

`README.md` in that directory is the index: task title, task ID, the commit
the work started from, the chosen route, and one line per artifact. Discovery
creates it. Every later step appends its own line and changes nothing else.

If the directory does not exist when you need it, create it with a minimal
`README.md` and note that you did — it means an earlier step was skipped or
the task entered the route directly.

## One file, one owner

You write your own artifact and nothing else. You may read the artifacts
listed in your role, and you do not rewrite them, reorganise them, or correct
them. If a predecessor's file is wrong, say so in your own file and let a
human decide.

`README.md` is the single exception: everyone appends a line to it.

## Reading

Read what your role names as its inputs. Reading more costs tokens and fills
your context with material you did not need — the list in your role is a
budget, not a suggestion.

When you refer to something a previous step established, give the path to its
file rather than restating its contents. A path stays true when the file
changes; a retelling drifts from it silently, and each retelling of a
retelling loses more.

## When a source is unavailable

A file that is missing, a search that failed, a command that would not run —
these make information stale or absent, not open to invention. Keep what you
actually have, mark precisely which part is stale or missing, and say why.
Never fill a gap from memory.

## Writing your artifact

Write it for someone who did not watch you work: a human at an approval gate,
or a later step whose context was cleared and which holds only your file.
Introduce names, paths and terms as if the reader sees them for the first
time. Open with the outcome — what you found or decided — and put the
supporting detail after it. The shorthand you built up while working is yours,
not theirs.

Your role names the sections your artifact must have. Keep all of them even
when one is short: an empty section is a claim that there was nothing, and
that is different from having forgotten to look. Do not add sections beyond
those.

Write artifacts and any message a human will read in Russian.

## Secrets

If evidence for something you are recording includes a credential, token,
connection string or private key, never reproduce the value. Cite the file and
line and mask it. What you are recording is the practice, not the secret.

## These files are working memory

They are not part of the product. Discovery adds the directory to the
repository's local git exclude rather than to the versioned `.gitignore`, so
the task's scratch space never lands in a commit. Anything that has to outlive
the task — a decision, a constraint someone will need later — belongs in the
project's own documentation or in the pull request description, not here.
