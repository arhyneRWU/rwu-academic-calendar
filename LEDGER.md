# Ledger

Running record of defects found, their state, and what proved each one fixed.
Newest work at the top. A row leaves `open` only when a test fails without the
fix.

**Convention:** `verified` means proven the way the bug was found — in a real
browser for builder bugs, against real `data/` for extraction bugs. A passing
unit test alone is `fixed`, not `verified`.

## Open — needs a human, not a commit

| # | What | Why it is not code |
|---|---|---|
| H1 | **One colleague and one student should use the builder before the link is shared widely.** Ten minutes each. | Testing proves the `.ics` is correct *given the inputs*. It cannot prove a person ticks the right boxes, and a wrong tick yields a calendar that looks entirely right — you find out in October at an empty room. |
| H2 | **Tell the Registrar this exists.** | It carries RWU's name, is published from a personal account, and is aimed at RWU students. The disclaimer is prominent and scraping a public page is fine, but a conversation had beforehand beats one had during a mid-semester divergence. The weekly drift job is the good thing to point at. |
| H3 | The drift job's **issue-opening branch has never fired** — only the no-drift path is proven (run 31950932130, green). | Needs real divergence, or a deliberate edit to `data/` to force it. Straightforward code, but unwatched. |

## Course catalog picker — 2026-08-16

Added after production readiness. Scope decided deliberately: **five fields,
no people.** Roger Central's payload carries instructor names, seat counts and
enrolment; none are read, stored or published, and there are tests asserting
both that the source still has them and that our files do not.

| # | What | State |
|---|---|---|
| C1 | Adding the picker declared `const stamp` a second time — a SyntaxError that killed the **entire** builder script while the page still rendered perfectly. Every substring test passed. | **verified** — renamed; `TestBuilderScriptHasNoDuplicateDeclarations` now parses the IIFE's own scope and fails on any redeclaration, with a guard-the-guard test so it cannot pass by finding nothing |
| C2 | First draft read `PlannedMeetings`, which does not exist on the response. | fixed before shipping — the real list is `FormattedMeetingTimes`; tested against an unedited captured response |
| C3 | `Meetings[].StartTime` is an ISO datetime stamped with *today's* date in UTC — right only by accident, wrong across DST. | fixed — read `FormattedMeetingTimes`, which is already 24-hour local |
| C4 | Colleague sends booleans as the strings `'True'`/`'False'`; both are truthy in Python, so the naive check fails open and schedules every TBD section. | fixed — `_truthy()`, with a test asserting `bool('False') is True` so the trap stays documented |
| C5 | A long pull saved only at the end, so a timeout at subject 100 discarded ~15 minutes of paced requests. | fixed — writes per subject as it goes |
| C6 | The existing test asserted the builder issues **no** network request. The picker fetches course lists, so that claim needed to change rather than be deleted. | **verified** — now asserts no XHR/beacon/socket/POST at all, that both fetches are relative paths built from one helper, and that nothing the user types is ever a fetch argument |

**Known limit, not a defect:** course data goes stale during add/drop in a way
the academic calendar never does. The page stamps when it was pulled and says
to check Roger Central. A weekly refresh is the deliberate cadence — nightly
would be a standing load on a production student system for no real gain.

## Production readiness — 2026-08-16

Asked and answered: the feeds were ready, the builder was not. Three gaps
found by checking rather than remembering, all now closed.

| # | What | State |
|---|---|---|
| P1 | The `?` explaining "Follows the class timetable" was a `title=` tooltip, so it needed a **mouse hover** — on a phone, where most students meet the builder, the explanation of its trickiest control did not exist. Screen readers skipped it too. | **verified** — replaced with a `<details>` open by default that explains *both* checkboxes (the second never had any explanation) and says what to do when unsure. Keyboard-focusable, taps open and shut, no script. Checked at 375px. |
| P2 | Once every extracted year retires, `pick_current` falls back to the newest — right, but the page then showed a finished year under "Current academic year" and looked maintained. | **verified** — a warning above the fold naming the date the data ran out and pointing at the official calendar; the eyebrow becomes "Most recent academic year". Boundary tested either side of 2027-05-05. |
| P3 | RWU publishes the four term tables at different times, so the picker showed three terms and no explanation. Someone planning a summer course found a silent absence. | **verified** — names the absent term ("Summer 2027 has not been published by RWU yet… Nothing is broken"). Wording agrees with itself for one term and for several. |

Also added while in there: `aria-live="polite"` on the preview, so the
gains-and-losses list is announced as it changes rather than only seen.

**Checked and already fine:** mobile layout at 375px (no horizontal scroll,
nothing overflowing), `lang`, a single `h1`, no heading skips, every input
labelled, no unlabelled buttons.

## Not a defect — recorded so it is not rediscovered

| # | What | Finding |
|---|---|---|
| D1 | Summer 2026 has no Independence Day, though 2023-24 and 2024-25 do. 4 July 2026 is a Saturday, observed Friday the 3rd. | **RWU's omission, not a parse miss** — confirmed by re-extracting the live page (49 events, no such row). Deliberately *not* added to `data/`: these feeds publish what RWU published, and inventing a date is worse than reporting a gap. `validate.check_federal_holidays` reports it on every run. |

## Done — review of 2026-08-16

Found by a full read of the repo, verified against real data and a live
browser. Fixed in the order below.

| # | Severity | What | State |
|---|---|---|---|
| 1 | **wrong answer** | MLK Day (2027-01-18) is printed under Spring 2027 but falls inside Winter 2027, which never saw it. The winter feed carried no holiday and the builder scheduled a Monday class on it. | **verified** — `Term.inherited_no_class_events`; browser-confirmed the winter Monday series now ends 11 Jan |
| 2 | **wrong answer** | The recommended phone feed listed Memorial Day 4× and Juneteenth 3× on one date — one copy per summer session. | **verified** — one VEVENT per calendar day; 468 → 389 events, no duplicate (date, summary) in any feed |
| 3 | **breaks next year** | "Retired academic years" listed every non-current year, so a newly extracted year appeared as retired with a future retirement date. | **verified** — split into retired / "Published ahead of time"; checked at three simulated dates |
| 4 | builder | Weekend dates inside the term were rejected as "only dates inside \<term\>" — a correct input told it was wrong. | **verified** — validity is now the term span; Saturdays accepted, 2026-02-31 still refused |
| 5 | builder | Two rows agreeing on name, days and start time emitted one UID; one silently vanished on import. | **verified** — `…-2` suffix on later duplicates only, so the ordinary case keeps its stable UID |
| 6 | builder | `esc()` escaped `;` `,` and newline but not `\`, emitting undefined escapes like `\D`. | **verified** — round-tripped `BIO 320 — Lecture C\D` back through `icalendar` |
| 7 | builder | Output was unfolded; the `DESCRIPTION` line ran to 102 octets against RFC 5545's 75. | **verified** — folds on UTF-8 octets and code points; no line over 75, em dash intact |
| 8 | latent | `_year_rows` raised `TypeError` for a year with no fall/spring. `Event.to_dict` dropped any falsy value, including an explicit `offices_closed: False`. | fixed — renders `—`; `to_dict` deleted (it was dead) |
| 9 | hardening | `json.dumps` does not escape `/`, so a `</script>` in an upstream label would break out of the grid's script block. | fixed — `<` escaped; test injects the payload |
| 10 | cosmetic | No favicon; every page load logged a 404. | **verified** — `href="data:,"`; console clean |

### Follow-through

`validate.check_federal_holidays` was added because both #1 and D1 were the
same failure: `check_coverage` matched *label text*, and only for fall and
spring — so it could not see either. The new check asks calendar arithmetic
instead, across every term, and observes weekend holidays on the adjacent
weekday. Across four years it now reports exactly one gap: D1.

### One-time churn for subscribers

Summer UIDs changed, because `session` came out of the UID key (that is what
fix 2 required). Anyone subscribed to a summer feed sees the duplicate copies
disappear and one correctly-merged event take their place, once. No other
term's UIDs moved.
