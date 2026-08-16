# Security policy

## What this project is, in security terms

A static site on GitHub Pages plus a Python build tool. There is **no server,
no database, no user account, and no API**. The published site is a handful of
`.ics`, `.json` and one `.html` file. That removes most of the attack surface
a web application would have, and it is worth being explicit about what
remains.

## What the site does with your data

**Nothing leaves your browser.** The class-schedule builder runs entirely
client-side: course names, rooms, meeting days and times are held in the page,
turned into a calendar file with the browser's own APIs, and handed to you as a
download. There is:

- no analytics, telemetry, or tracking of any kind
- no cookies, no `localStorage`, no `sessionStorage`
- no form that submits anywhere
- no third-party requests — no CDN, no web fonts, no embedded widgets
- no `<script src=...>` at all; the only JavaScript is inline and same-origin

You can verify all of this: view source, or open the network tab and watch it
stay empty.

## Threat model

| Concern | Assessment |
|---|---|
| **Data exfiltration** | Nothing is transmitted. The builder never issues a network request. |
| **Cross-site scripting** | The one place user input reaches `innerHTML` (the schedule preview) is HTML-escaped, and a test asserts it. See below. |
| **Supply chain** | The site has zero runtime dependencies. The build uses `icalendar` and `PyYAML`, pinned in `pyproject.toml` and used only at build time — they never run in a visitor's browser. |
| **Content integrity** | Feeds are generated from `data/*.yaml`, which is committed and reviewed. A build cannot reach the network, so a compromised or altered rwu.edu page cannot change what is published without a human merging it. |
| **Malicious calendar content** | Event text comes from RWU's public calendar page and is escaped per RFC 5545 when written to `.ics`. |
| **Availability** | GitHub Pages. If it is down, nothing else breaks — subscribers keep their last successful sync. |

### Findings from the 2026-08-16 review

Two injection issues were found and fixed. Both are recorded here rather than
quietly patched, because "low severity" is a judgement someone else should be
able to check.

**1. Stored XSS via the upstream page.** The extractor's text cleaner strips
HTML tags and *then* unescapes entities, so a label written on rwu.edu as
`&lt;img src=x onerror=...&gt;` came back as live markup — and the landing
page interpolated that label into its "what happens next" line without
escaping. Confirmed end to end before fixing. Exploiting it requires control of
RWU's own page, and the extracted text is committed to `data/*.yaml` and
reviewed before it publishes, so there are two barriers in front of it. Fixed
by escaping every non-constant value at the HTML sink; the feeds were never
affected, since JSON and ICS serializers encode their own output.

**2. Self-XSS in the schedule builder.** Described below.

Also hardened in the same pass, none of them exploitable as configured:
dependency ranges given upper bounds (CI installs them with `issues: write`
and Pages deploy rights); the drift workflow's Actions expression moved out of
the `script:` body into `env:`; and the scraped drift report now fenced with
more backticks than it contains, so upstream text cannot inject markdown into
an issue.

### The self-XSS finding, and why it is documented rather than quietly fixed

An early version of the schedule builder interpolated the course name straight
into the preview's `innerHTML`. A course named
`<img src=x onerror="...">` executed. This was **self-XSS** — the only person
who could trigger it was the person typing into their own browser, since
nothing is stored, shared, or reflected from a URL — so its practical severity
was low. It was still a real injection flaw and is fixed: user input is
HTML-escaped before it reaches `innerHTML`, and
`tests/test_index.py` asserts that a name containing markup renders as text.

It is written down here because "low severity" is a judgement someone else
should be able to check, not a reason to leave it out of the record.

## Reporting a vulnerability

Open an issue: <https://github.com/arhyneRWU/rwu-academic-calendar/issues>

Public issues are appropriate here. There is no user data to protect and no
production system to take down, so there is nothing to gain from a private
disclosure window. If you would rather not post publicly, email the address on
the GitHub profile.

Expect a reply within a week or so. This is maintained by one person alongside
other work.

## What this project explicitly does *not* promise

- **It is not an official RWU source.** It is scraped from a public page and is
  not endorsed by the university. Do not use it where being wrong has
  consequences without checking the [official calendar][src].
- **The data can be wrong.** Validation currently reports seven weekday
  inconsistencies on RWU's own page. Run `rwu-calendar validate` to see them.
- **No uptime or freshness guarantee.** A weekly job checks for drift and opens
  an issue; applying it is a manual review step, by design.

[src]: https://www.rwu.edu/academics/resources-units/academic-calendar
