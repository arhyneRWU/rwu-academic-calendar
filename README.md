# RWU Academic Calendar — unofficial machine-readable feeds

### ➡️ **[Open the calendar site](https://arhynerwu.github.io/rwu-academic-calendar/)**

| | |
|---|---|
| 📅 **[Add to your phone](https://arhynerwu.github.io/rwu-academic-calendar/#add-it-to-your-phone)** | Subscribe to holidays, breaks and day swaps — step-by-step for iPhone, Google and Outlook |
| 🗓️ **[Build your own schedule](https://arhynerwu.github.io/rwu-academic-calendar/#builder)** | Classes, office hours, meetings, clubs — get an `.ics` with every occurrence, holidays removed and day swaps applied |
| 🔗 **[Subscribe now](webcal://arhynerwu.github.io/rwu-academic-calendar/rwu-no-class-days.ics)** | One tap on a phone. Or paste `https://arhynerwu.github.io/rwu-academic-calendar/rwu-no-class-days.ics` |

> [!IMPORTANT]
> **This is not an official Roger Williams University publication.** It is
> derived, by scraping, from RWU's [public academic calendar page][src] and is
> maintained by one person for use by his own programs. It is not endorsed by
> the university, the Registrar, or anyone else. **Verify against the [official
> calendar][src] before relying on it for anything that matters.**

RWU publishes its academic calendar as HTML tables and printable PDFs. There is
no `.ics` feed and no API. This repo turns that page into calendar feeds you can
subscribe to and JSON your programs can read.

[src]: https://www.rwu.edu/academics/resources-units/academic-calendar

## Subscribe

| Feed | URL |
|---|---|
| Everything | `https://arhynerwu.github.io/rwu-academic-calendar/rwu-academic-calendar.ics` |
| No-class days + day swaps only | `https://arhynerwu.github.io/rwu-academic-calendar/rwu-no-class-days.ics` |
| One academic year | `…/2026-2027.ics` |
| **One term only** | `…/fall-2026.ics` · `…/spring-2027.ics` · `…/winter-2027.ics` |

Per-term feeds exist because the year feed is all or nothing. If you don't
teach in January, subscribe to Fall and Spring and skip Winter — each term is
its own live subscription. Every term id in `no-class-days.json` has a matching
`<term-id>.ics` and `<term-id>.json`.

Add by URL in Google Calendar (*Other calendars → From URL*), Apple Calendar
(*File → New Calendar Subscription*), or Outlook (*Add calendar → Subscribe from
web*).

## Consume as JSON

| File | What it's for |
|---|---|
| `no-class-days.json` | **Start here.** Term boundaries, no-class dates, day swaps, and a precomputed `class_days` list per term. |
| `rwu-academic-calendar.json` | Every event with its classification. |
| `2026-2027.json` | One academic year. |

```bash
curl -s https://arhynerwu.github.io/rwu-academic-calendar/no-class-days.json
```

```jsonc
{
  "id": "fall-2026",
  "classes_begin": "2026-08-26",
  "classes_end": "2026-12-02",
  "no_class_dates": [
    { "date": "2026-09-07", "label": "Labor Day: No Classes - All University Offices Closed" }
  ],
  "day_swaps": [
    { "date": "2026-10-13", "observes_schedule_of": "monday",
      "label": "Tuesday - Monday Classes Observed" }
  ],
  "class_days": ["2026-08-26", "2026-08-27", "..."]
}
```

## Stability — this JSON is a contract

Tools already consume `no-class-days.json`. It is treated as a published
interface, not an implementation detail:

- **Keys are never renamed or removed.** New keys may be added at any time, so
  parse permissively and ignore what you don't recognise.
- **Dates are always `YYYY-MM-DD` strings**, never timestamps.
- **Term ids are stable** — `fall-2026` resolves to the same term forever.
- **`no_classes` is always a real boolean**, never null or absent.
- **`day_swaps` and `no_class_dates` never overlap.** Do not union them; a swap
  day holds classes.
- **Retired academic years keep serving.** Nothing is ever unpublished.

`tests/test_json_contract.py` enforces all of the above, so a change that would
break a consumer fails CI rather than shipping quietly. If a breaking change
ever becomes unavoidable, the old key ships alongside the new one for at least
a full academic year.

## The one thing to get right: day swaps are not days off

Every fall and spring term has exactly one **day swap** — a day that holds
classes on a *different weekday's* timetable, compensating for a break.

```
2026-10-13  Tue   runs Monday's schedule
2027-02-16  Tue   runs Monday's schedule
```

A consumer that models only `no_classes` will place a Tuesday lab on a day that
is actually running Monday's timetable. That is why `day_swaps` is a separate
list from `no_class_dates`, and why `observes_schedule_of` is typed rather than
left in the label. RWU has written this same fact **eight different ways** in
four years, so do not pattern-match the prose yourself:

```
Friday Classes Meet, Thursday Courses do not Meet
Monday Schedule Observed - Monday classes Meet-Tuesday Classes do not Meet
Monday Schedule - Monday classes meet
Monday Classes Meet, Tuesday Courses do not Meet
Tuesday - Monday Classes Observed
```

`Term.effective_weekday(date)` folds holidays and swaps into one answer: the
weekday whose timetable actually runs, or `None` if no class meets.

## What's in it

Four academic years, 15 terms, 468 events.

| Term | Classes begin | Classes end | No-class | **Class days** |
|---|---|---|---|---|
| Fall 2023 | Wed Aug 30 | Wed Dec 13 | 7 | 70 |
| Spring 2024 | Wed Jan 24 | Wed May 8 | 9 | 68 |
| Fall 2024 | Wed Aug 28 | Wed Dec 11 | 7 | 70 |
| Spring 2025 | Wed Jan 22 | Wed May 7 | 9 | 68 |
| Fall 2025 | Wed Aug 27 | Wed Dec 10 | 7 | 70 |
| Spring 2026 | Wed Jan 21 | Wed May 6 | 9 | 68 |
| Fall 2026 | Wed Aug 26 | Wed Dec 2 | 7 | 65 |
| Spring 2027 | Wed Jan 27 | Wed May 5 | 10 | 63 |

Plus Winter intersessions and Summer sessions. Note that **2026-27 is five class
days shorter** than the three years before it, in both terms.

`class_days` counts weekdays between the first and last day of classes, minus
no-class days. Reading Day and finals fall *after* the last day of classes, so
they are outside the span rather than subtracted from it.

## How it works, and why it's built this way

```
rwu.edu page ──[ extract ]──> data/*.yaml ──[ build ]──> public/*.ics + *.json
   scraped          reviewed,      committed      generated,     published
   weekly           by a human     source of      deterministic  to Pages
   as a CHECK                      truth
```

**The scraper is the check, not the pipeline.** `data/*.yaml` is the source of
truth and is committed; builds read it and never touch the network. A weekly CI
job re-scrapes and opens an issue if the live page has drifted.

That inversion is deliberate. The source page has used **three incompatible date
layouts in four years**:

| Years | Layout |
|---|---|
| 2026-27 | four columns — `Event ǀ Month ǀ Date ǀ Day` |
| 2023-24 … 2025-26 | two columns — `Event ǀ "Aug. 21-22, Thurs.-Fri."` |
| Winter tables | two columns — `Event ǀ "22-Jan"` (day first) |

A build that scraped at publish time would break on the next redesign, silently,
while generating a semester. This way a redesign fails one weekly job and the
feeds keep serving the last known-good data.

### Validation, including RWU's own errors

RWU prints the weekday beside each date, which is a free checksum. Comparing it
against the real weekday of that date catches transcription errors on both
sides. As of the 2026-08-16 extraction it finds **seven genuine errors on RWU's
page** — for example 2027-03-25 is a Thursday but is printed as Wednesday, and
2025-12-29 is a Monday printed as Friday.

`offices_closed` deserves a specific warning: it is only set where RWU's own
label says so. **33 of 92 no-class days never state office status** — every
Spring Break day, every Reading Day, every SASH day. Absent means *the page
did not say*, not *offices were open*. `rwu-calendar validate` reports the
gap per term. Do not build a rule on this field without handling the unknowns.

These are reported, not corrected and not fatal: the dates are taken as
authoritative and the printed weekday is treated as the typo. Run
`rwu-calendar validate` to see the current list.

## Local use

```bash
python3 -m venv .venv && ./.venv/bin/pip install -e '.[dev]'
./.venv/bin/rwu-calendar extract     # scrape -> data/*.yaml  (review the diff!)
./.venv/bin/rwu-calendar validate    # structural checks + weekday cross-check
./.venv/bin/rwu-calendar build       # data/ -> public/
./.venv/bin/rwu-calendar drift       # compare live page against data/; exit 2 on drift
./.venv/bin/pytest
```

The generated schedule is a **recurring series** (`RRULE` + `EXDATE` for
holidays + `RDATE` for day swaps), not dozens of separate events, so your
calendar app lets you edit or delete the whole thing at once. Event UIDs are
derived from the course itself, not its position in the form, so regenerating
after editing a row updates in place instead of creating duplicates.

Builds are byte-deterministic — `DTSTAMP` is fixed and UIDs are content-derived —
so rebuilding without a data change produces an empty diff, and subscribers never
see duplicate events.

### Updating for a new academic year

1. `rwu-calendar extract`
2. **Read the diff.** This is the human review step; the whole design exists to
   make it small and legible.
3. `rwu-calendar validate`, then commit `data/`. CI rebuilds and publishes.

## Working on this

Read [`HANDOFF.md`](HANDOFF.md) first. It records the decisions that are not
obvious from the code — why the scraper is a check rather than a build step,
why there is no event-type dropdown, and the six things that will bite you.

## Licence

Code MIT (`LICENSE`). The calendar dates themselves are facts about a public
university calendar and are not claimed as anyone's property here; the labels are
quoted verbatim from RWU's public page.
