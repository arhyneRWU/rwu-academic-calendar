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

## Builder clarity and cross-platform import — 2026-08-17

Three complaints — "it's just iPhone I think", "the courses added is
strange", and "it feels like you're restricted to just scheduled classes" —
turned out to be twelve: three CSS, one default that stopped being right the
moment the catalog picker existed, three actions that did their work in
silence, one setting working perfectly somewhere nobody could reach it, and one
gap between the two halves of the site — a personal schedule that knew about
the day swap but never said so.

| # | What | State |
|---|---|---|
| U1 | **Every value the user typed rendered in the caption grey.** `color: inherit` on an input inherits from its parent, which is the grey uppercase `<label>`. Values came out at `rgba(136,136,136,.6)` — about 2.1:1 contrast — at 12.8px, because `font: inherit` also took the caption's size. A filled form was indistinguishable from an empty one. | **verified** — `color: CanvasText` (tracks light/dark on its own) and an explicit size; placeholders stay grey |
| U2 | **The "Dates, one per line" textarea was visible on every row, always.** It is marked `hidden`, but the browser's `[hidden] {display:none}` loses to any author rule setting `display`, and `.crow` sets `display:flex`. Nothing in the markup looked wrong. | **verified** — `[hidden] {display:none !important}` |
| U3 | **Horizontal scroll on a phone**, 852px against a 375 viewport — but only *after* choosing a subject. A flex item defaults to `min-width:auto` and will not shrink below its content, and the picker's longest option is a whole section line. An earlier mobile check passed because it never loaded a subject. | **verified** — `min-width: 0`; re-checked at 375px with a subject loaded |
| U4 | **`DTSTAMP` frozen at `20000101`.** Correct for the published feeds, where a fixed stamp keeps rebuilds diffing clean — wrong for a personal download, because a client comparing timestamps reads a re-import as no newer than what it holds and declines to update. That silently broke the one thing content-derived UIDs exist for. | **verified** — real stamp plus `SEQUENCE:0` |
| U5 | **The builder opened with a blank, class-shaped row and a `+ Add another item` button.** Sitting directly under the catalog picker with no heading of its own, it read as *the other way to add a course*, and "another item" inherited that meaning — so office hours, meetings, clubs and work shifts looked out of scope until you clicked and read the placeholder. The catalog dropdown now handles classes, which makes a class-shaped default actively wrong. | **verified** — two labelled boxes (*Your classes* from the catalog, *Anything else that repeats* with examples), no row built until someone asks for one, and an empty-state line so an empty list does not look broken. Checked at 375px with a catalog course added, and both submit paths re-run in the browser |
| U6 | **Pressing *Add* in the catalog said nothing.** The course was added correctly, but the list sits below the fold on a phone, so the only evidence was off-screen — and the picker kept the course selected, so a second press looked like the way to make something happen. | **verified** — a `role="status"` line naming the section, the course picker cleared for the next one, and a two-second flash on the new row. Two courses added in a row in the browser |
| U7 | **The download was a synthetic click on an anchor that never appeared on the page.** On a desktop that is the whole interaction; on iOS Safari and inside any in-app browser (Outlook's, Teams', Instagram's) it can be declined outright — and when it is, *nothing happens on screen at all*: no file, and no way to tell whether the button worked. Reported as "the download doesn't download a thing". | **verified** — the file is now offered as a **real link on the page** that stays there to be tapped, in a block that says so; the automatic click is still attempted first. The blob is fetched back and parsed in the browser: 2 VEVENTs, CRLF, no line over 75 octets |
| U8 | The import instructions covered iPhone, Outlook desktop, Outlook web, Google and Mac Calendar — but not **Outlook on a phone**, which is the app most likely to be open when someone taps the file, and the one with no Import menu at all. | **verified** — says to import once at outlook.office.com and let it sync down, and warns that tapping the file lands it in Apple Calendar instead |
| U9 | **The reminder looked lost.** It was not — every VEVENT still carried its `VALARM`, and the preview still said "reminder 15 min before". But the only control for it lives inside a row's expanded form, and catalog rows arrive collapsed, so for the main path through the builder it was behind a click nobody makes; the collapsed line did not mention it either. A setting you cannot see or reach is a setting you have lost. | **verified** — one **Remind me** control for the whole schedule beside the download button, which moves every row that has not been set by hand; a row's own select still wins once touched, and the collapsed line now ends with the reminder. Browser-checked: global 15→30 moved both rows, a hand-set row held `P1D` while the global went to `PT5M`, and the downloaded file carried `TRIGGER:-PT5M` and `TRIGGER:-P1D` |
| U10 | **A downloaded schedule contained only what you typed.** The dates that *change* that schedule — the day swap above all — were visible only if you separately subscribed to a feed. Someone who used the builder and stopped there had a calendar that silently skipped Thanksgiving with no entry explaining why. | **verified** — RWU's own dates ride along: all-day, `TRANSP:TRANSPARENT` **and** `X-MICROSOFT-CDO-BUSYSTATUS:FREE` (Outlook reads the latter), no `VALARM`, on by default with an opt-out. **UIDs are the published feeds' own**, so subscribing *and* downloading yields one Thanksgiving rather than two — checked against `fall-2026.ics` and `rwu-no-class-days.ics`. Fall 2026 contributes 10 entries; the file goes 1 event → 11 |
| U11 | **In Outlook, an imported schedule arrived as ~39 separate appointments per course** instead of one recurring series you can edit one occurrence of. The file was *already* a proper series — one `VEVENT`, one `RRULE`, expansion confirmed at 39 and 26 dates — so this was Outlook's importer, on the two constructs it handles worst: `RDATE`, which its recurrence model cannot represent at all, and a long comma-joined `EXDATE` that has to be folded. Faced with either, it keeps the meetings and throws away the pattern. | **verified** — no `RDATE` at all: the day swap's gained Tuesday is now its own single event with its own stable UID, which is what it actually is. One `EXDATE` property per date. Re-expanded with `dateutil`: still exactly 39 and 26 dates, 13 Oct present for MWF and absent for T/Th. **Confirmed in Outlook desktop by Andrew, 2026-08-18**: the course now prompts *this occurrence / the series*, 13 October appears once as its own extra meeting, and the week of 9 November correctly shows Mon and Fri with Wednesday absent for Veteran's Day — which proves the `EXDATE` change landed as well as the `RDATE` one. |
| U12 | **Add/drop and withdrawal deadlines were in the data and never offered.** The ride-along carried closures and term boundaries only — so the dates that actually cost money to miss were the ones a personal calendar did not get. | **verified** — three tick-boxes instead of one: closures (8), first/last day (2), and *Student deadlines* (10: add, drop, withdrawal, advisement, registration, exam period), off until ticked. Counts are per term and an empty group disables its own box. Add, drop and withdrawal carry `TRIGGER:-PT9H` — **not** `-P1D`, which on an all-day event fires at midnight the previous day; nine hours before midnight is 3pm the afternoon before, while the Registrar is open. Everything stays `TRANSP:TRANSPARENT`. Browser-checked: 12 events → 22 on ticking, 4 alarms, and grades/residence-life/orientation still excluded |

**And the actual reason it felt iPhone-only:** the file was always a valid
`.ics` that any app can read. But the page's only instructions were for
*subscribing to the feed*, and iOS is the one platform where opening the
downloaded file just works. Everywhere else needs an Import menu — different in
every app, and in Outlook desktop it is *File → Open & Export → Import/Export*,
not double-clicking the file, which imports one appointment and drops the rest.
There are now instructions for iPhone, Outlook desktop, Outlook web, Google
Calendar and Mac Calendar, plus `METHOD:PUBLISH`, `X-WR-TIMEZONE` and
`charset=utf-8` for the importers that want them.

**The UI**, separately: each added course collapses to one line
(`MWF 9:00 AM–9:50 AM · MNS 210 · 39 dates`) with a *from catalog* tag,
expanding to the full form only when you click it — a plain `<details>`, no JS
state. Catalog rows arrive collapsed; hand-entered ones open, since they are
empty. An incomplete row says what is missing rather than silently failing to
appear in the preview.

## Page order and density — 2026-08-19

"Most people are going to use the builder, not the subscription feed." The page
was built the other way round and had been quietly admitting it: a banner near
the top read *"Most people want this → Build your own class schedule"*, which is
a page telling you its own order is wrong.

Measured at 375px, before and after, on the same viewport:

| | before | after |
|---|---|---|
| Whole page | 10.7 screens | 9.6 |
| "Build your own schedule" | 2.5 screens down | **0.6** |
| Term picker | 2.9 | 0.8 |
| **First control you can use** (subject) | 3.6 | **0.9** |
| Download button | 5.4 | 2.7 |

| # | What | State |
|---|---|---|
| S1 | **The builder sat below a complete second feature.** To reach it you scrolled past the year cards, the subscribe buttons and the feed link box. | **verified** — builder directly under the disclaimer; the feed section follows it under its own heading. The jump-link banner went with the reason for it |
| S2 | **The checkbox explanation was in the wrong place**, not merely too long: open by default *above* the form, between the term picker and the course picker, describing two controls that live inside an item row the reader has not created yet. | **verified** — moved into that row, directly after the two checkboxes, shut. Still a `<details>`: touch, keyboard and screen reader, no script, which is what P1 required. A test asserts it carries no `title=` so it cannot regress into a tooltip |
| S3 | The preamble said the same thing twice — a paragraph, then three numbered step markers repeating it. | **verified** — one sentence; `.steps` and its CSS deleted, along with the now-dead `.banner` rules |

**A measurement error worth recording.** The first pass at these numbers was
taken while the browser pane reported a zero-width viewport, and every
`getBoundingClientRect` reading was inflated — the page was called 46.6 screens
when it was 10.7, and the explain block 4 screens when it was 0.6. The design
conclusions happened to survive, but only because the *order* was wrong
independently of how tall anything was. Fix: build the previous commit in a
temporary worktree, serve both, and measure them in the same viewport in the
same session. Check `innerWidth` is non-zero before trusting a layout number.

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
| C7 | **The section lookup used the wrong key and lost most of the catalog.** `courseId` was built as `SUBJECT_NUMBER`; the site itself sends the numeric course `Id`. The wrong form is accepted for *some* courses and silently returns an empty result for others — `BIO_101` works, `HIST_100` returns nothing, no error, no status code. A full run finished "successfully" with 417 patterns across 26 subjects while dropping the rest on the floor. | **verified** — captured the site's own XHR to find the real key; a subject with courses but zero patterns is now called out in the run log, which is the guard that would have caught it on run one |
| C8 | No retry. A quarter-hour of requests to a remote host met `[Errno 60] Operation timed out` at subject six and the whole run died. | fixed — four attempts with backoff on 5xx and connection errors, never on 4xx; one unreachable course no longer ends the run |

**How C7 got caught, since it is the interesting part.** The numbers looked
fine: 417 patterns, no errors, plausible spread. What did not look fine was
*EDU: 0* and *HIST: 1* for a fall term. Checking one subject against the live
site took two minutes and showed ten HIST courses with sections. The lesson is
the same one in gotcha 7 of the handoff: a clean run is not evidence, and the
cheapest check is against reality rather than against our own output.

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
| D2 | A beta tester: the feed lists Fall 2026 finals on 4, 7, 8 and 9 December but not Saturday 5 December, which the Registrar's exam grid shows a column for. | **Two RWU documents disagree; we match the one we cite.** The academic calendar page reads verbatim: *Final Examinations: Day and Evening Classes — DEC 4, FRI* and *DEC 7-9, MON-WED*. No Saturday, and no year back to 2023 lists one. The **exam grid** — the time-block matrix that assigns each course its slot — is a separate Registrar publication and can carry dates the calendar does not. Not invented into `data/`, same call as D1. The builder now says the grid is a different document and to check it for your own exam; a test pins the four dates and asserts no year claims a Saturday, so a future extraction that produces one gets a human look. |
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
