# Ledger

Running record of defects found, their state, and what proved each one fixed.
Newest work at the top. A row leaves `open` only when a test fails without the
fix.

**Convention:** `verified` means proven the way the bug was found — in a real
browser for builder bugs, against real `data/` for extraction bugs. A passing
unit test alone is `fixed`, not `verified`.

## Open

| # | Severity | What | Where |
|---|---|---|---|
| — | | nothing open | |

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
