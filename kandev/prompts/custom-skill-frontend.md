Skill: building user-facing UI. Loaded by Planning, Test Authoring and
Implementation when `discovery.md` names `frontend` under «Навыки». It adds
to the role's own prompt; it never overrides the artifact protocol, git
safety or test ownership.

Rules adapted from Anthropic `frontend-design` (Apache-2.0), Vercel Web
Interface Guidelines (MIT) and `ui-ux-pro-max` (MIT); snapshot of
2026-09-04.

## Start from what the project already has

Before inventing anything, find the project's design system: tokens,
component library, spacing and type scale, existing screens that solve a
similar problem. Reuse them. Never introduce a parallel palette, a second
radius scale, a new shadow or a new font because the brief felt like it
deserved one. `discovery.md` records where these live; if the project has
a `design-system/` or a MASTER document, it wins over your taste. When
the project has nothing of the kind, keep decisions few and write them
down where Planning puts the plan, so the next task inherits them.

## Plan the design before the code

For a new screen or a visible change, write a short design plan first —
in the Plan when you are Planning, in your closing message otherwise: the
tokens you will use (colour as four to six named values, type scale,
spacing), the layout in one sentence plus an ASCII wireframe, and the one
element that carries the screen. Then read that plan against the brief:
if any part of it reads like the generic default you would produce for
any similar page, revise that part and say what you changed and why.
Spend your boldness in one place — let one element be the memorable
thing, keep everything around it quiet, and cut decoration that does not
serve the brief.

## The defaults that read as machine-made

Avoid these unless the project's own design system already uses them:

- warm cream background with a high-contrast serif display face and a
  terracotta accent; near-black background with a single acid accent;
- broadsheet styling: hairline rules, zero radius, dense columns;
- the card kit: content chopped into identical rounded cards, one radius
  everywhere, the same faint shadow under each, gradient washes as
  decoration;
- template chrome: tracked-out all-caps eyebrows over every heading, meta
  strings joined with «·», «WORD — fragment» labels, monospace for small
  data labels, an arrow appended to every link or button;
- scattered motion: fade-and-slide entrances on each section and a hover
  transition on every card;
- one accented word in a headline, numbered markers where nothing is a
  sequence, emojis used as icons — use the project's icon set.

## Typography and structure

One type family, or two clearly distinct ones. A deliberate scale with
intentional weights and spacing. Body lines under 80 characters; serif
body gets a little more line-height than sans. Visual structure is
information: borders, dividers, eyebrows and numbering must encode
content, not decorate it. Watch selector specificity so section rules and
element rules do not cancel each other's spacing.

## Motion

One orchestrated moment — a page-load sequence or a single reveal — lands
better than effects everywhere. Motion that answers a user action is
welcome when it shows what changed. Honour `prefers-reduced-motion`,
animate only `transform` and `opacity`, never `transition: all`, keep
animations interruptible.

## Every screen has all its states

Design and implement loading, empty, error, success, sparse and dense
explicitly. Skeletons mirror the final layout so nothing shifts. Handle
long content: truncate or clamp, `min-width: 0` on flex children, and
test with short, average and absurdly long user text. Forms: the submit
button stays enabled until the request starts, a spinner during it, errors
inline next to the field, focus moves to the first error, every error says
what to do next. Destructive actions get confirmation or undo. URL
reflects state that a user would want to share or return to — filters,
tabs, pagination. Warn before leaving with unsaved changes. Loading
strings end with «…», number columns use tabular figures, headings use
balanced wrapping, dates and numbers go through `Intl`, never a
hand-written format.

## The quality floor, without announcing it

Responsive down to a phone: mobile-first breakpoints, no horizontal
scroll, no fixed pixel widths, zoom never disabled, safe-area insets on
full-bleed layouts. Semantic HTML before ARIA: `button` for actions, a
link for navigation, never a clickable `div`; icon-only buttons carry
`aria-label`; images carry `alt` (empty when decorative) and explicit
dimensions, lazy-loaded below the fold; every control has a label; async
updates announce through `aria-live="polite"`; lists over fifty items are
virtualised. Visible focus through `:focus-visible`, never `outline: none`
without a replacement, and sticky headers must not cover the focused
element. Text contrast at least 4.5:1, touch targets at least 44 px on
mobile, base font 16 px with line-height around 1.5, nothing under 12 px,
meaning never carried by colour alone. Dark mode declares
`color-scheme: dark` on the root and sets explicit colours on native
`select`.

## What this skill asks of each role

- **Planning**: the design plan above goes into the Plan, and «Проверки»
  names browser tests for the changed screens — a UI change with only
  backend tests is not checked (decision 41).
- **Test Authoring**: write the browser tests the Plan names, covering the
  states above, keyboard access and at least one narrow viewport; if the
  project has no browser runner and the Plan records the owner approving
  one, install it as the Plan says.
- **Implementation**: build to this floor and to the design plan; when
  the plan and the existing design system disagree, the design system
  wins and you record the deviation under «Отклонения от плана».
