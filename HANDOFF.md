# Handoff — rwu-academic-calendar

**Current as of 2026-08-17.** Read this before changing anything, then
[`LEDGER.md`](LEDGER.md) for every defect found so far and what proved each one
fixed. Several decisions here were made against specific evidence and should
not be re-litigated from first principles.

## What this is

An **unofficial** machine-readable version of RWU's academic calendar, plus a
browser-based schedule builder that can fill in a course from RWU's public
course catalog.

| | |
|---|---|
| Repo | <https://github.com/arhyneRWU/rwu-academic-calendar> (public) |
| Site | <https://arhynerwu.github.io/rwu-academic-calendar/> |
| Local | `~/PycharmProjects/rwu-academic-calendar` (venv at `.venv`) |
| Calendar source | RWU's [academic calendar page](https://www.rwu.edu/academics/resources-units/academic-calendar) — HTML tables, no ICS, no API |
| Course source | [Roger Central](https://collselfsrvprod.rwu.edu/Student/Courses) — Ellucian Colleague Self-Service, public, JSON behind a JS front end |

**State:** 18 commits, 330 tests, CI green, deployed. 4 academic years, 15
terms, 468 calendar events. 1,112 course meeting patterns across 69 subjects
for Fall 2026. `validate` reports 0 errors and 17 source inconsistencies —
RWU's own, not ours.

## Commands

```bash
./.venv/bin/rwu-calendar extract     # scrape rwu.edu -> data/*.yaml  (READ THE DIFF)
./.venv/bin/rwu-calendar validate    # structure, weekday cross-check, federal holidays
./.venv/bin/rwu-calendar build       # data/ -> public/
./.venv/bin/rwu-calendar drift       # live page vs data/; exit 2 on drift
./.venv/bin/rwu-calendar courses --list          # terms and subjects RWU publishes
./.venv/bin/rwu-calendar courses --term 26/FA    # pull one term (~15 min)
./.venv/bin/pytest -q
```

## Architecture, and the one rule that explains it

```
rwu.edu ─────[extract]──┐
                        ├──> data/ (committed, human-reviewed) ──[build]──> public/
Roger Central ─[courses]┘         *.yaml + courses/26FA/*.json              ICS + JSON
   scraped as a CHECK,                                                      + index.html
   never at build time
```

**Neither scraper ever runs at build time.** Builds read committed data and
never touch the network. A Monday cron re-scrapes the calendar and opens an
issue on divergence; a Tuesday cron refreshes courses and commits the diff.
This exists because the calendar page has used **three incompatible date
layouts in four years** — a build that scraped at publish time would break
silently, mid-semester. A broken scrape leaves the last good data serving.

**Correctness lives in Python, not JavaScript.** The page embeds a precomputed
"meeting grid"; the browser only filters it. Anything that could be wrong must
be a tested `Term` method, not JS.

## The domain fact everything hinges on

Every fall and spring term has exactly **one day swap** — a date running a
*different weekday's* timetable (Tue 13 Oct 2026 runs a Monday schedule).

- A T/Th course meets **26** times in Fall 2026, not the 28 a weekday count gives.
- An M/W course in Spring 2027 **gains Tue 16 Feb**, a date that is neither.

RWU has written this same fact **eight different ways in four years**. Never
pattern-match the prose; use `Term.effective_weekday()` or the grid.

## Decisions already made — don't redo these

| Decision | Why |
|---|---|
| Hand-reviewed YAML is the source of truth | Source page changes shape; see above |
| Publish ICS **and** JSON | ICS for humans/phones, JSON for programs |
| Per-term feeds (`fall-2026.ics`) | A year feed is all-or-nothing; skipping Winter shouldn't mean losing Fall |
| Feeds, not "pick terms & download" | A download goes stale; subscriptions stay live |
| Builder output is a download, not a feed | Per-person feeds need a server; static Pages can't |
| `RRULE`+`EXDATE`+`RDATE` | ~15× smaller, and an *editable series* in calendar apps |
| A year retires when its **spring term ends** | The moment it stops being what you plan against; a date already in the data |
| **No event-type dropdown** | Three adversarial reviewers: nobody can tell "academic" from "staff/admin" meeting, and the failure is silent, surfacing months later at an empty room |
| Two plain checkboxes instead | "Follows the class timetable" / "Skips holidays and breaks" — answerable about your own commitment |
| Course data: **five fields, no people** | Instructor names, seat counts and enrolment are in the payload and are not taken. A meeting pattern is a fact about a room and a clock |
| Courses committed, refreshed **weekly** | Same rule as the calendar; nightly would be standing load on a production student system for no real gain |

## Things that will bite you

**1. `offices_closed` is unknown on 33 of 92 no-class days.** Every Spring Break
day, Reading Day, SASH day. Absent means *the page didn't say*, **not** "offices
were open". There is no safe default. This is why the staff/admin meeting type
was cut. `validate` reports the gap per term.

**2. Summer is six overlapping sessions, not one term.** `classes_begin/end`
take min/max across all of them (20 May – 14 Aug 2026), which is right for "the
summer term" and wrong for any one student. Use `Term.sessions()`.

**3. A term does not own its January.** RWU publishes one table per term, and
some dates fall under two: MLK Day is printed under Spring, where spring has
not started, while the date lands inside the Winter intersession. Winter held
no record of it and the builder put a Monday class on the holiday.
`Term.inherited_no_class_events()` fills the gap and stamps `owner_term` so the
borrowed copy keeps one UID across both feeds. **If you add a new construction
path for `AcademicYear`, call `model.link()`** — otherwise inheritance silently
returns nothing and the bug comes back.

**4. RWU's page contains real typos, and one silently deleted a whole term.**
"Lat day of classes" meant Winter 2027 had no `classes_end`, so it vanished
from the builder with no error for weeks. `validate.check_structure` now
requires boundaries on **every** term with events — that check is the real fix;
the tolerant regex is a patch.

**5. `_txt()` strips tags *then* unescapes entities.** So upstream
`&lt;img onerror=…&gt;` becomes live markup. Correct for JSON/ICS (their
serializers encode); **HTML must escape at the sink** via `_e()`. This was a
confirmed stored XSS. See `SECURITY.md`.

**6. The published JSON is a contract.** The RWU wetlab app reads
`no-class-days.json`. Keys are never renamed or removed.
`tests/test_json_contract.py` enforces it.

**7. Feeds emit one VEVENT per calendar day, not per source row.** Summer's six
sessions repeat every holiday verbatim, so a row-per-event feed showed Memorial
Day four times in every subscriber's calendar. `emit._merge` collapses rows
sharing a date and label and *unions* their fields — in 2024 one copy read
"office Closed" (singular) while its siblings read "Offices", so first-wins made
the office status a coin toss.

**8. Course lookups need the numeric `Id`, not `SUBJECT_NUMBER`.** The code form
is accepted for some courses and silently returns an empty result for others —
`BIO_101` works, `HIST_100` returns a 200 and nothing at all. A full run
finished "successfully" with 417 patterns while dropping most of the catalog.
A subject that returns courses but zero patterns is now called out in the run
log. Also: read `FormattedMeetingTimes`, never `Meetings` (the latter's
`StartTime` is stamped with *today's* date in UTC), and Colleague sends booleans
as the strings `'True'`/`'False'`, which are **both truthy in Python**.

**9. Dates never come from the course catalog.** Roger Central's section range
runs through finals week — Fall 2026 ends `12-09` there and `12-02` here. Date
fields are not collected at all, which is the cheapest possible guarantee.

**10. The JS lives inside Python strings.** `_BUILDER_JS` is `r"""..."""`
precisely because a rewrite once put **literal CR/LF bytes inside a JS string
literal** — a syntax error that broke the whole builder while every
substring-matching test passed. Later, adding the catalog picker declared
`const stamp` twice, which is *also* a SyntaxError that kills the entire script
while the page still renders perfectly. `test_no_raw_carriage_returns` and
`TestBuilderScriptHasNoDuplicateDeclarations` guard both.

**11. CSS `hidden` is not reliable, and `color: inherit` on an input is a trap.**
The browser's `[hidden] {display:none}` loses to any author rule setting
`display` — `.crow` sets `display:flex`, so a date textarea was visible on every
row, always. And an input with `color: inherit` inherits its *label's* colour,
so every typed value rendered in caption grey at 2.1:1 contrast. There is now a
global `[hidden] {display:none !important}` and an explicit `CanvasText`.

**12. Substring tests are not enough for anything in the browser.** Verify in a
browser (`python3 -m http.server` in `public/`, then Playwright) and expand
generated ICS with `python-dateutil` to compare against the grid. **Hard-reload
or cache-bust** — a stale `index.html` will happily "prove" your change works
when the browser is serving the previous build. That practice has caught six
real bugs the test suite passed clean on.

## Deliberately not built

- **"Nth weekday of the month"** — no defensible default when the first
  Wednesday lands in Spring Break.
- **Staff/admin office-status rule** — see gotcha 1.
- **All-day events** in the builder; **weekday-only** weekly patterns (the grid
  holds no weekends). Listed dates *may* be weekends.
- **A public course dataset beyond five fields.** Considered and scoped down on
  purpose: no instructor names, no seat counts, no enrolment.
- **Institutional calendars** (Faculty Senate, athletics). RWU's events page
  runs 25Live with no public feed; Andrew confirmed there is no public access.
- **Timezones.** Builder times are floating local wall-clock — correct across
  the November DST change, wrong if the file is shared across timezones.
  `X-WR-TIMEZONE` tells Google and Outlook which zone to read them in.

## Open — needs a person, not a commit

1. **Someone other than me should use the builder.** Ten minutes, one colleague
   and one student. Testing proves the `.ics` is correct *given the inputs*; it
   cannot prove a person ticks the right boxes. Every UI bug in `LEDGER.md`
   under "Builder clarity" was found by looking, not by the 330 tests.
2. **Tell the Registrar it exists.** Andrew's call and already decided: show it
   off, ask about linking it. Worth doing before it gets wide use rather than
   after.
3. **The drift job's issue-opening branch has never fired.** The workflow is
   proven green on the no-drift path only. Forcing a divergence would prove it.
4. **Winter 2027 and Spring 2027 course data** appears automatically once RWU
   publishes those terms; only Fall 2026 exists today. Nothing to do but check
   the weekly job picked them up.
5. **`D1`**: RWU's Summer 2026 table has no Independence Day row — their
   omission, confirmed against the live page, deliberately not invented into
   `data/`. `check_federal_holidays` reports it every run.

## Relationship to the wetlab app

This is the **inbound** half of the two calendar features tracked in the wetlab
repo — consuming RWU's calendar so a scheduler knows about holidays. The
**outbound** half (publishing a person's shifts as a subscribable feed) is
unrelated code living in `backend/`. They share only the word "ICS".

The open question there is still open: whether a holiday *suppresses* a
student's availability block or merely annotates it. This repo supplies the
dates and their semantics and deliberately does not decide that.

`docs/WORK-IN-PROGRESS.md` in the wetlab repo still says this project is
"nothing exists, being built separately". That is stale — this is that project.
Updating it is work in a repo with other live sessions, so it has been left
alone.
