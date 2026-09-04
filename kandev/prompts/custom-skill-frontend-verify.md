Skill: checking user-facing UI. Loaded by Verification, Code Review and
Fix Review when `discovery.md` names `frontend` under «Навыки». It adds
to the role's own prompt; findings go into the role's own artifact in the
role's own format, never into a separate report.

Rules adapted from Anthropic `webapp-testing` (Apache-2.0), Vercel Web
Interface Guidelines (MIT), OneRedOak `design-review` (MIT) and
`playwright-skill` (MIT); snapshot of 2026-09-04.

## Two halves: live and static

The live half drives a browser against the running application. The
static half reads the code. Do both when a browser is available; do the
static half and say so when it is not. A UI change that was never opened
in a browser is not verified, and the artifact must say exactly which
live phases were skipped so the human gate stays honest.

## Getting a browser

Look for a running dev server first — `discovery.md` names the command
and port; never guess a URL. If nothing is running, start it the way the
project does, wait for the port, and stop it when you are done. Drive it
through the Playwright MCP tools when the agent has them
(`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`,
`browser_resize`, `browser_press_key`, `browser_console_messages`,
`browser_network_requests`), otherwise through the project's own
Playwright installation with a throwaway script in a temporary directory,
headless when there is no display. Reconnaissance before action: navigate,
wait for the network to settle, take a snapshot, derive selectors from
roles, text and test ids, then act. Save screenshots under the task's
artifact directory and cite them by path in the artifact.

If neither the MCP tools nor a Playwright installation exist, do not
install anything silently: name exactly what is missing and the one-line
command that would add it, record «визуальная проверка не выполнена» with
the list of skipped phases, and do the static half.

## Live phases

1. **Flow.** Walk the primary user flow of the change end to end. Try
   hover, active, disabled and focus states of what changed; confirm
   destructive actions ask or offer undo; confirm feedback appears —
   loading indicator, success or error message.
2. **Viewports.** Capture 1440, 768 and 375 wide. No horizontal scroll, no
   overlapping or clipped elements, touch targets usable on the narrow
   one.
3. **Polish.** Alignment and spacing consistent with neighbouring screens,
   typography hierarchy readable, colours and radii from the project's
   tokens, not new ones.
4. **Keyboard and assistive access.** Walk the screen with Tab, Shift+Tab,
   Enter, Space and Escape. Every interactive element is reachable and
   shows focus; modals trap focus and return it on close; the snapshot
   shows sensible roles, names, heading order and alt text; text contrast
   at least 4.5:1.
5. **Robustness.** Submit empty, invalid and very long input; force the
   empty, loading and error states — block or mock the network when
   needed; overflow with long strings.
6. **Console and network.** No errors or warnings the change introduced,
   no failed requests, no hydration warnings.

## Static checklist

Flag, with file and line:

- `user-scalable=no` or `maximum-scale=1`; `transition: all`;
  `outline: none` without a `:focus-visible` replacement; missing
  `prefers-reduced-motion` guard;
- clickable `div` or `span`, inline navigation without a link, gesture-only
  actions without a keyboard or click alternative, interactive elements
  without keyboard handlers;
- images without dimensions, large arrays rendered without
  virtualisation, animated GIF where video fits;
- inputs without labels or `autocomplete` and the right `type` or
  `inputmode`, icon buttons without `aria-label`, decorative icons not
  `aria-hidden`, heading levels out of order, no skip link to main content;
- hardcoded date or number formats, `autoFocus` without a reason;
- a component missing one of empty, loading, error or success; flex text
  without `min-width: 0` or truncation; chips and badges that neither wrap
  nor collapse to «+n»; meaning carried by colour alone;
- new one-off colours, radii or shadows where tokens exist; duplicated
  components where the project already has one; magic numbers.

## Reporting

Problems over prescriptions: describe the user impact and the evidence —
screenshot path, viewport, step — rather than the fix. Rank each finding
the way the role already ranks: for Code Review and Fix Review the
platform severities (`blocker`, `major`, `minor`, `nit`); for
Verification, red or green with the failing phase named. Group by file
where the finding is in code, by screen and viewport where it is
visual.

## What this skill asks of each role

- **Verification**: run the browser tests Test Authoring wrote, then the
  live phases on the changed screens; a red live phase is a red run.
- **Code Review**: the static checklist on the diff, plus the live phases
  when a browser is available; visual findings are findings like any
  other and go through `publish_review_findings_kandev`.
- **Fix Review**: re-check only the screens the fixes touched, live where
  possible, and confirm no state or viewport regressed.
