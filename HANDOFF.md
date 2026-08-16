# Handoff — rwu-academic-calendar

**Written 2026-08-16**, at the end of the session that built this repo from
nothing. Read this before changing anything; several decisions here were made
against specific evidence and should not be re-litigated from first principles.

## What this is

An **unofficial** machine-readable version of RWU's academic calendar, plus a
browser-based schedule builder.

| | |
|---|---|
| Repo | <https://github.com/arhyneRWU/rwu-academic-calendar> (public) |
| Site | <https://arhynerwu.github.io/rwu-academic-calendar/> |
| Local | `~/PycharmProjects/rwu-academic-calendar` (venv at `.venv`) |
| Source | RWU's [academic calendar page](https://www.rwu.edu/academics/resources-units/academic-calendar) — HTML tables, no ICS, no API |

**State:** 12 commits, 202 tests passing, CI green, deployed. 4 academic years,
15 terms, 468 events. `rwu-calendar validate` reports 0 errors and 15 source
inconsistencies (RWU's own, not ours).

## Commands

```bash
./.venv/bin/rwu-calendar extract     # scrape -> data/*.yaml   (READ THE DIFF)
./.venv/bin/rwu-calendar validate    # structure + weekday cross-check
./.venv/bin/rwu-calendar build       # data/ -> public/
./.venv/bin/rwu-calendar drift       # live page vs data/; exit 2 on drift
./.venv/bin/pytest -q
```

## Architecture, and the one rule that explains it

```
rwu.edu ──[extract]──> data/*.yaml ──[build]──> public/*.ics + *.json + index.html
 scraped WEEKLY         committed,              generated, deterministic,
 AS A CHECK ONLY        human-reviewed          published to Pages
```

**The scraper is a check, never the build pipeline.** Builds read committed
YAML and never touch the network. A Monday cron (`drift.yml`) re-scrapes and
opens a GitHub issue on divergence. This exists because the source page has
used **three incompatible date layouts in four years** — a build that scraped
at publish time would break silently, mid-semester.

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

> **Update 2026-08-16, later the same day.** A full code review found ten
> defects, all fixed and recorded in [`LEDGER.md`](LEDGER.md) — read that
> alongside this file. Two were wrong answers being served: MLK Day missing
> from Winter 2027, and the recommended phone feed showing Memorial Day four
> times. Gotchas 8 and 9 below come from it.

## Things that will bite you

**1. `offices_closed` is unknown on 33 of 92 no-class days.** Every Spring Break
day, Reading Day, SASH day. Absent means *the page didn't say*, **not** "offices
were open". There is no safe default: absent-as-open schedules staff meetings
through Spring Break; absent-as-closed cancels meetings on days offices are
open. This is why the staff/admin meeting type was cut. `validate` reports the
gap per term.

**2. Summer is six overlapping sessions, not one term.** `classes_begin/end`
take min/max across all of them (20 May – 14 Aug 2026), which is right for "the
summer term" and wrong for any one student. Use `Term.sessions()`. The grid
already emits one entry per session.

**3. RWU's page contains real typos, and one silently deleted a whole term.**
"Lat day of classes" meant Winter 2027 had no `classes_end`, so it vanished
from the builder with no error for weeks. `validate.check_structure` now
requires boundaries on **every** term with events — that check is the real fix;
the tolerant regex is a patch.

**4. `_txt()` strips tags *then* unescapes entities.** So upstream
`&lt;img onerror=…&gt;` becomes live markup. Correct for JSON/ICS (their
serializers encode); **HTML must escape at the sink** via `_e()`. This was a
confirmed stored XSS. See `SECURITY.md`.

**5. The published JSON is a contract.** The RWU wetlab app reads
`no-class-days.json`. Keys are never renamed or removed.
`tests/test_json_contract.py` enforces it. Values may be corrected; keys may
not move.

**6. The JS lives inside Python strings.** `_BUILDER_JS` is now `r"""..."""`
precisely because a rewrite once put **literal CR/LF bytes inside a JS string
literal** — a syntax error that broke the whole builder while every
substring-matching test still passed. `test_no_raw_carriage_returns` guards it.

**7. Substring tests are not enough for the builder.** Verify in a browser
(`python3 -m http.server` in `public/`, then Playwright), and expand generated
ICS with `python-dateutil` to compare against the grid. That practice caught
two real bugs the test suite missed — the CR/LF syntax error, and a dates-only
event silently losing its first date because `DTSTART` is only *implicitly* an
occurrence when there is no `RRULE`.

**8. A term does not own its January.** RWU publishes one table per term, and
some dates fall under two of them: MLK Day is printed under Spring, where
spring has not started, while the date lands inside the Winter intersession.
Winter therefore held no record of it and the builder put a Monday class on the
holiday. `Term.inherited_no_class_events()` fills that gap and stamps
`owner_term` so the borrowed copy keeps one UID across both feeds. If you add a
new construction path for `AcademicYear`, **call `model.link()`** or
inheritance silently returns nothing and the bug comes back.

**9. Feeds emit one VEVENT per calendar day, not per source row.** Summer's six
sessions repeat every holiday verbatim, so a row-per-event feed showed Memorial
Day four times in every subscriber's calendar. `emit._merge` collapses rows
sharing a date and label, and unions their fields rather than taking the first
— in 2024 one copy read "office Closed" (singular) while its siblings read
"Offices", so first-wins made the office status a coin toss.

## Deliberately not built

- **"Nth weekday of the month"** — no defensible default when the first
  Wednesday lands in Spring Break. Skip? Shift? Both are wrong sometimes.
- **Staff/admin office-status rule** — see gotcha 1.
- **All-day events** in the builder.
- **Institutional calendars** (Faculty Senate, athletics). RWU's events page
  runs 25Live but exposes only a `datefinder` widget, no public feed. Andrew
  confirmed 25Live has no public access. Users enter their own events instead.
- **Timezones.** Builder times are floating local wall-clock — correct across
  the November DST change, wrong if the file is shared across timezones.

## Open / next

1. **Have someone else try the builder** before sharing the link widely. Still
   the top item, and the only one that cannot be closed by writing code: the
   two checkboxes are better than the dropdown but remain the weakest link,
   and ticking the wrong one produces a calendar that *looks* right. Their
   explanation is now a `<details>` that works on a phone — it used to be a
   hover-only tooltip, i.e. absent exactly where most students would meet it.
2. Consider surfacing `Term.sessions()` in the summer UI copy — the six
   session names are long and currently shown verbatim in the dropdown.
3. ~~Winter/summer terms have no `check_coverage` expectations.~~ **Closed
   2026-08-16.** It was not theoretical: that gap hid both the missing MLK Day
   and the missing Independence Day. `validate.check_federal_holidays` now
   checks every term by date rather than by RWU's wording.
4. The wetlab repo's `docs/WORK-IN-PROGRESS.md` still says the inbound calendar
   feed is "nothing exists, being built in a separate project". That's stale —
   this is that project, and it's done. Updating it is worktree work in a repo
   with other live sessions, so it was deliberately left alone.

## Relationship to the wetlab app

This is the **inbound** half of the two calendar features tracked in the wetlab
repo — consuming RWU's calendar so a scheduler knows about holidays. The
**outbound** half (publishing a person's shifts as a subscribable feed) is
unrelated code living in `backend/`, already designed, token layer already
built. Don't confuse them; they share only the word "ICS".

The open question there is still open: whether a holiday *suppresses* a
student's availability block or merely annotates it. This repo supplies the
dates and their semantics and deliberately does not decide that.
