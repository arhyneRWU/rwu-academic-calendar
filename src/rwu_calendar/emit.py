"""Emit ICS and JSON from the committed YAML.

Two audiences, one source:

* **ICS** — humans, phones, anything that subscribes. Built with
  ``collective/icalendar``.
* **JSON** — programs. ``no-class-days.json`` in particular is the small,
  boring file a scheduler imports.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path

from icalendar import Calendar, Event as IcsEvent

from .model import AcademicYear, Event

PRODID = '-//arhyneRWU//RWU Academic Calendar (unofficial)//EN'
_DISCLAIMER = ('UNOFFICIAL. Derived from the public RWU academic calendar page; '
               'not published or endorsed by Roger Williams University. '
               'Verify against the official calendar before relying on it.')


def _uid(ay: str, term: str, e: Event) -> str:
    """Stable per (year, term, date, label).

    A UID that changes between builds makes every subscribed calendar append a
    duplicate on each poll until it is unusable. This is *the* classic ICS bug,
    so the UID is derived from content and never from build time.
    """
    key = f'{ay}|{term}|{e.session or ""}|{e.date.isoformat()}|{e.label}'
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    return f'{h}@rwu-academic-calendar.arhyneRWU.github.io'


def _summary(e: Event) -> str:
    if e.observes_schedule_of:
        return f'{e.label} [{e.observes_schedule_of.title()} schedule]'
    return e.label


def to_ics(years: list[AcademicYear], name: str,
           predicate=None, dtstamp: _dt.datetime | None = None) -> bytes:
    cal = Calendar()
    cal.add('prodid', PRODID)
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', name)
    cal.add('x-wr-caldesc', _DISCLAIMER)
    # Deterministic by default: a build that changes DTSTAMP on every run makes
    # every rebuild look like a content change in git.
    stamp = dtstamp or _dt.datetime(2000, 1, 1, tzinfo=_dt.timezone.utc)

    for ay in years:
        for t in ay.terms:
            for e in t.events:
                if predicate and not predicate(e):
                    continue
                ev = IcsEvent()
                ev.add('uid', _uid(ay.academic_year, t.id, e))
                ev.add('dtstamp', stamp)
                ev.add('dtstart', e.date)                       # all-day
                ev.add('dtend', e.date + _dt.timedelta(days=1))  # DTEND is exclusive
                ev.add('summary', _summary(e))
                ev.add('transp', 'TRANSPARENT')
                desc = [f'Term: {t.id}', f'Academic year: {ay.academic_year}',
                        f'Categories: {", ".join(e.kinds)}']
                if e.session:
                    desc.append(f'Session: {e.session}')
                if e.no_classes:
                    desc.append('No classes.')
                if e.observes_schedule_of:
                    desc.append(f'Classes meet on a {e.observes_schedule_of.title()} schedule.')
                if e.offices_closed is not None:
                    desc.append('University offices closed.' if e.offices_closed
                                else 'University offices open.')
                desc += ['', _DISCLAIMER, ay.source_url]
                ev.add('description', '\n'.join(desc))
                ev.add('categories', e.kinds)
                ev.add('url', ay.source_url)
                cal.add_component(ev)
    return cal.to_ical()


def to_json(years: list[AcademicYear]) -> dict:
    return {
        'unofficial': True,
        'disclaimer': _DISCLAIMER,
        'source_url': years[0].source_url if years else None,
        'generator': 'https://github.com/arhyneRWU/rwu-academic-calendar',
        'academic_years': [
            {
                'academic_year': ay.academic_year,
                'retrieved': ay.retrieved,
                'terms': [
                    {
                        'id': t.id,
                        'term': t.term,
                        'classes_begin': t.classes_begin.isoformat() if t.classes_begin else None,
                        'classes_end': t.classes_end.isoformat() if t.classes_end else None,
                        'class_day_count': len(t.class_days()),
                        'events': [
                            {
                                'date': e.date.isoformat(),
                                'label': e.label,
                                'kinds': e.kinds,
                                'no_classes': e.no_classes,
                                'observes_schedule_of': e.observes_schedule_of,
                                'offices_closed': e.offices_closed,
                            }
                            for e in t.events
                        ],
                    }
                    for t in ay.terms
                ],
            }
            for ay in years
        ],
    }


def to_no_class_json(years: list[AcademicYear]) -> dict:
    """The small file a scheduler imports.

    Day swaps are listed separately from no-class days on purpose: a swap day
    is not a day off, it is a day running a different timetable. Collapsing the
    two is the mistake this file exists to prevent.
    """
    terms = []
    for ay in years:
        for t in ay.terms:
            terms.append({
                'id': t.id,
                'term': t.term,
                'academic_year': ay.academic_year,
                'classes_begin': t.classes_begin.isoformat() if t.classes_begin else None,
                'classes_end': t.classes_end.isoformat() if t.classes_end else None,
                'no_class_dates': [
                    {'date': e.date.isoformat(), 'label': e.label}
                    for e in sorted(t.events, key=lambda x: x.date) if e.no_classes
                ],
                'day_swaps': [
                    {'date': e.date.isoformat(), 'observes_schedule_of': e.observes_schedule_of,
                     'label': e.label}
                    for e in sorted(t.day_swaps(), key=lambda x: x.date)
                ],
                'class_days': [d.isoformat() for d in t.class_days()],
            })
    return {
        'unofficial': True,
        'disclaimer': _DISCLAIMER,
        'source_url': years[0].source_url if years else None,
        'terms': terms,
    }


SITE_HOST = 'arhynerwu.github.io'
SITE_PATH = '/rwu-academic-calendar'
SITE_URL = f'https://{SITE_HOST}{SITE_PATH}'
REPO_URL = 'https://github.com/arhyneRWU/rwu-academic-calendar'

#: The feed to lead with. The full calendar carries every add/drop and
#: grades-due deadline, which buries a phone; this one is holidays, breaks
#: and day swaps.
PRIMARY_FEED = 'rwu-no-class-days.ics'


def webcal(name: str) -> str:
    """A ``webcal://`` URL, which phones open in the subscribe dialog directly
    rather than downloading the file and leaving the user to find it."""
    return f'webcal://{SITE_HOST}{SITE_PATH}/{name}'


def _teaching_span(ay: AcademicYear):
    starts = [t.classes_begin for t in ay.terms if t.term in ('fall', 'spring') and t.classes_begin]
    ends = [t.classes_end for t in ay.terms if t.term in ('fall', 'spring') and t.classes_end]
    return (min(starts), max(ends)) if starts and ends else (None, None)


def retires_on(ay: AcademicYear) -> _dt.date | None:
    """The date an academic year stops being the one to plan against.

    **A year retires when its spring term ends.** That is the moment it stops
    being useful for planning, and it is a date already in the data rather than
    a guess. Its summer sessions run on past that date and keep working -- and
    the feeds keep serving retired years forever, because reconstructing what
    the calendar said in a past term is exactly the question worth answering
    later. Retirement only decides what the page leads with.
    """
    return _teaching_span(ay)[1]


def is_retired(ay: AcademicYear, today: _dt.date) -> bool:
    end = retires_on(ay)
    return bool(end and today > end)


def pick_current(years: list[AcademicYear], today: _dt.date) -> AcademicYear | None:
    """The academic year to feature: the earliest one not yet retired.

    Derived from the data rather than hardcoded, so extracting a new year next
    summer promotes it without a code change.
    """
    live = sorted((ay for ay in years if not is_retired(ay, today)),
                  key=lambda ay: _teaching_span(ay)[0] or _dt.date.max)
    if live:
        return live[0]
    return max(years, key=lambda ay: retires_on(ay) or _dt.date.min) if years else None


def _next_milestone(ay: AcademicYear, today: _dt.date) -> str:
    """One line of 'what happens next', so the page is useful at a glance."""
    best = None
    for t in ay.terms:
        if t.term not in ('fall', 'spring'):
            continue
        for e in t.events:
            if e.date < today:
                continue
            if 'term_start' in e.kinds or e.no_classes or e.observes_schedule_of:
                if best is None or e.date < best[0]:
                    best = (e.date, e, t)
    if not best:
        return ''
    d, e, _t = best
    away = (d - today).days
    when = 'today' if away == 0 else 'tomorrow' if away == 1 else f'in {away} days'
    what = (f'runs a {e.observes_schedule_of.title()} schedule'
            if e.observes_schedule_of else e.label)
    return (f'<p class="next"><strong>Next:</strong> {d:%A %-d %B %Y} ({when}) — {what}</p>')


def _term_cards(ay: AcademicYear, today: _dt.date) -> str:
    """Term dates at a glance. These are what people come to the page for, so
    they are set large and plain rather than buried in a table."""
    out = []
    for t in ay.terms:
        if t.term not in ('fall', 'spring') or not t.classes_begin:
            continue
        swap = t.day_swaps()
        swap_txt = (f'{swap[0].date:%a %-d %b} runs a '
                    f'{swap[0].observes_schedule_of.title()} schedule'
                    if swap else 'none')
        if today < t.classes_begin:
            away = (t.classes_begin - today).days
            state = f'<span class="pill soon">starts in {away} day{"s" * (away != 1)}</span>'
        elif today <= t.classes_end:
            state = '<span class="pill now">in session</span>'
        else:
            state = '<span class="pill done">finished</span>'
        out.append(f"""<div class="card">
<h3>{t.term.title()} {t.classes_begin:%Y} {state}</h3>
<p class="dates">{t.classes_begin:%a %-d %b %Y} <span class="dash">→</span>
{t.classes_end:%a %-d %b %Y}</p>
<dl>
<div><dt>Class days</dt><dd>{len(t.class_days())}</dd></div>
<div><dt>No-class days</dt><dd>{len(t.no_class_dates())}</dd></div>
<div><dt>Day swap</dt><dd>{swap_txt}</dd></div>
</dl></div>""")
    return ''.join(out)


def _retired_rows(years: list[AcademicYear], today: _dt.date) -> str:
    out = []
    for ay in sorted(years, key=lambda a: a.academic_year, reverse=True):
        end = retires_on(ay)
        out.append(
            f'<tr><td><strong>{ay.academic_year}</strong></td>'
            f'<td>{end:%-d %b %Y}</td>'
            f'<td><a href="{ay.academic_year}.ics">.ics</a></td>'
            f'<td><a href="{webcal(ay.academic_year + ".ics")}">subscribe</a></td>'
            f'<td><a href="{ay.academic_year}.json">.json</a></td></tr>')
    return ''.join(out)


FEED_URL = f'{SITE_URL}/{PRIMARY_FEED}'


def _urlbox(url: str, label: str = 'This is the link to paste:') -> str:
    """Show the literal URL wherever we tell someone to paste one.

    Saying "paste the link" and leaving them to work out *which* link is the
    fastest way to lose a non-technical user, so every step that needs a URL
    carries the whole thing, selectable, with a copy button.
    """
    return (f'<div class="urlbox"><span class="urllabel">{label}</span>'
            f'<code class="url">{url}</code>'
            f'<button class="copy" type="button" hidden data-url="{url}">Copy</button>'
            f'</div>')


_HOWTO = f"""
<details open><summary><strong>iPhone / iPad</strong></summary>
<ol>
<li>Tap <a href="{webcal(PRIMARY_FEED)}"><strong>Subscribe on this
device</strong></a> — iOS opens the subscribe sheet. Tap
<strong>Subscribe</strong>, then <strong>Add</strong>. That is the whole thing;
you can stop here.</li>
<li>If nothing happens, add it by hand: <em>Settings → Apps → Calendar →
Calendar Accounts → Add Account → Other → Add Subscribed Calendar</em>, then
paste the link below into <em>Server</em>.</li>
</ol>
{_urlbox(FEED_URL)}
<p class="tip">Refresh interval lives in <em>Settings → Apps → Calendar →
Sync</em>.</p>
</details>

<details><summary><strong>Google Calendar (including Android)</strong></summary>
<p><strong>This one has to be done on a computer first.</strong> The Google
Calendar mobile app cannot add a calendar by URL — but once added on the web it
syncs to your phone automatically.</p>
<ol>
<li>Open <a href="https://calendar.google.com">calendar.google.com</a>.</li>
<li>Beside <em>Other calendars</em>, click <strong>+</strong> →
<strong>From URL</strong>.</li>
<li>Paste the link below into <em>URL of calendar</em>, then click
<strong>Add calendar</strong>.</li>
</ol>
{_urlbox(FEED_URL)}
<p class="tip">Google refreshes subscribed calendars on its own schedule —
typically every 8–24 hours — and there is no way to force it sooner.</p>
</details>

<details><summary><strong>Outlook</strong></summary>
<ol>
<li><em>Add calendar → Subscribe from web</em>.</li>
<li>Paste the link below, give it a name, and click <strong>Import</strong>.</li>
</ol>
{_urlbox(FEED_URL)}
</details>

<details><summary><strong>Something else (Thunderbird, Fantastical, code)</strong></summary>
<p>Any client that speaks iCalendar can subscribe to this link:</p>
{_urlbox(FEED_URL)}
<p>Writing code? Use the JSON instead — see
<a href="{REPO_URL}#consume-as-json">the README</a>.</p>
{_urlbox(f'{SITE_URL}/no-class-days.json', 'JSON for programs:')}
</details>

<details><summary><strong>I want a different feed</strong></summary>
<p>The links above are the recommended feed: holidays, breaks and day swaps for
every year. These are the alternatives — paste them the same way.</p>
{_urlbox(f'{SITE_URL}/rwu-academic-calendar.ics',
         'Everything, including add/drop and grades deadlines:')}
{_urlbox(f'{SITE_URL}/2026-2027.ics', 'One academic year only (2026-2027):')}
</details>
"""

_COPY_JS = """
<script>
// Progressive enhancement only: the URL above is already visible and
// selectable, so the button stays hidden unless the clipboard API exists.
if (navigator.clipboard) {
  for (const b of document.querySelectorAll('.copy')) {
    b.hidden = false;
    b.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(b.dataset.url);
        const was = b.textContent;
        b.textContent = 'Copied';
        setTimeout(() => { b.textContent = was; }, 1500);
      } catch (e) { /* selection still works */ }
    });
  }
}
</script>
"""


def to_index_html(years: list[AcademicYear], today: _dt.date | None = None) -> bytes:
    """A plain landing page for GitHub Pages. No assets, no external requests."""
    today = today or _dt.date.today()
    current = pick_current(years, today)
    others = [ay for ay in years if ay is not current]
    src = years[0].source_url if years else ''

    cur_ics = f'{current.academic_year}.ics' if current else PRIMARY_FEED
    hero_terms = _term_cards(current, today) if current else ''
    retired = _retired_rows(others, today)

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RWU Academic Calendar — unofficial feeds</title>
<meta name="description" content="Unofficial subscribable calendar feeds (ICS)
and JSON for the Roger Williams University academic calendar.">
<style>
 :root {{ color-scheme: light dark; --line:#8886; --accent:#2563eb; --warn:#c33; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --accent:#7aa2f7; }} }}
 * {{ box-sizing: border-box; }}
 body {{ font: 16px/1.6 system-ui, -apple-system, sans-serif; max-width: 56rem;
        margin: 0 auto; padding: 2rem 1rem 4rem; }}
 h1 {{ margin-bottom: .2rem; }}
 h2 {{ margin-top: 2.5rem; border-bottom: 1px solid var(--line); padding-bottom: .3rem; }}
 .sub {{ color: #8889; margin-top: 0; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border: 1px solid var(--line); padding: .4rem .6rem; text-align: left;
          white-space: nowrap; }}
 code {{ background: #8881; padding: .1em .35em; border-radius: 3px;
        font-size: .9em; word-break: break-all; white-space: normal; }}
 .warn {{ border-left: 4px solid var(--warn); padding: .75rem 1rem;
         background: color-mix(in srgb, var(--warn) 8%, transparent);
         border-radius: 0 4px 4px 0; }}
 .hero {{ border: 1px solid var(--line); border-radius: 10px; padding: 1.25rem 1.5rem;
         margin: 1.5rem 0; }}
 .hero h2 {{ margin: 0 0 .5rem; border: 0; padding: 0; font-size: 1.9rem; }}
 .eyebrow {{ margin: 0; text-transform: uppercase; letter-spacing: .08em;
            font-size: .75rem; font-weight: 700; color: #8889; }}
 .next {{ margin: .25rem 0 1.25rem; }}
 .cards {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }}
 .card {{ border: 1px solid var(--line); border-radius: 8px; padding: .9rem 1.1rem; }}
 .card h3 {{ margin: 0 0 .35rem; font-size: 1.05rem; }}
 .dates {{ margin: 0 0 .75rem; font-size: 1.25rem; font-weight: 700;
          line-height: 1.35; }}
 .dash {{ color: #8889; font-weight: 400; }}
 .card dl {{ margin: 0; font-size: .9rem; }}
 .card dl div {{ display: flex; justify-content: space-between; gap: 1rem;
                border-top: 1px solid var(--line); padding: .3rem 0; }}
 .card dt {{ color: #8889; }}
 .card dd {{ margin: 0; text-align: right; }}
 .pill {{ font-size: .7rem; font-weight: 700; text-transform: uppercase;
         letter-spacing: .05em; padding: .15em .5em; border-radius: 99px;
         vertical-align: middle; white-space: nowrap; }}
 .pill.now {{ background: #16a34a; color: #fff; }}
 .pill.soon {{ background: color-mix(in srgb, var(--accent) 20%, transparent);
              color: var(--accent); }}
 .pill.done {{ background: #8882; color: #8889; }}
 .btns {{ display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0 .5rem; }}
 .btn {{ display: inline-block; padding: .6rem 1.1rem; border-radius: 8px;
        background: var(--accent); color: #fff; text-decoration: none;
        font-weight: 600; }}
 .btn.alt {{ background: transparent; color: inherit; border: 1px solid var(--line); }}
 .wrap {{ overflow-x: auto; }}
 details {{ border: 1px solid var(--line); border-radius: 8px; padding: .6rem 1rem;
           margin: .6rem 0; }}
 summary {{ cursor: pointer; }}
 details[open] summary {{ margin-bottom: .5rem; }}
 .tip {{ color: #8889; font-size: .92em; }}
 .urlbox {{ display: flex; flex-wrap: wrap; align-items: center; gap: .5rem;
           border: 1px dashed var(--line); border-radius: 8px;
           padding: .6rem .8rem; margin: .75rem 0;
           background: color-mix(in srgb, var(--accent) 5%, transparent); }}
 .urllabel {{ flex: 1 0 100%; font-size: .8rem; font-weight: 700; color: #8889;
             text-transform: uppercase; letter-spacing: .04em; }}
 .urlbox .url {{ flex: 1 1 20rem; background: transparent; padding: 0;
                font-size: .95rem; user-select: all; }}
 .copy {{ font: inherit; font-size: .85rem; font-weight: 600; cursor: pointer;
         padding: .3rem .8rem; border-radius: 6px; border: 1px solid var(--line);
         background: transparent; color: inherit; }}
 .copy:hover {{ border-color: var(--accent); color: var(--accent); }}
 ul.feeds {{ padding-left: 1.2rem; }}
 footer {{ margin-top: 3rem; color: #8889; font-size: .92em; }}
</style></head><body>

<h1>RWU Academic Calendar</h1>
<p class="sub">Subscribable calendar feeds and JSON, derived from RWU's public
academic calendar page.</p>

<p class="warn"><strong>Not an official Roger Williams University
publication.</strong> Derived by scraping the
<a href="{src}">public academic calendar page</a>; not endorsed by the
university. Verify against the official calendar before relying on it.</p>

<div class="hero">
<p class="eyebrow">Current academic year</p>
<h2>{current.academic_year if current else 'Calendar'}</h2>
{_next_milestone(current, today) if current else ''}
<div class="cards">{hero_terms}</div>
<div class="btns">
<a class="btn" href="{webcal(PRIMARY_FEED)}">Subscribe on this device</a>
<a class="btn alt" href="{webcal(cur_ics)}">Subscribe: {current.academic_year if current else ''} only</a>
<a class="btn alt" href="{PRIMARY_FEED}">Download .ics</a>
</div>
<p class="tip">Holidays, breaks and day swaps — add once and it stays current.
If a button does nothing, paste this link into your calendar app instead:</p>
{_urlbox(FEED_URL)}
</div>

<h2>Add it to your phone</h2>
{_HOWTO}
<p class="tip">Events are all-day and marked <code>TRANSPARENT</code>, so they
will not make you look busy to anyone checking your availability.</p>

<h2>Day swaps are not days off</h2>
<p>Every fall and spring term has exactly one day that holds classes on a
<em>different weekday's</em> timetable, compensating for a break. The feeds label
these <code>[Monday schedule]</code>, and the JSON gives them a typed
<code>observes_schedule_of</code> field, kept separate from the no-class days.
Software that models only "no classes" will put a Tuesday class on a day that is
actually running Monday's timetable.</p>

<h2>All feeds</h2>
<ul class="feeds">
<li><a href="{PRIMARY_FEED}"><code>{PRIMARY_FEED}</code></a> — no-class days and
day swaps. <em>Recommended for phones.</em></li>
<li><a href="rwu-academic-calendar.ics"><code>rwu-academic-calendar.ics</code></a>
— everything, including add/drop and grades deadlines.</li>
<li><a href="no-class-days.json"><code>no-class-days.json</code></a> — for
software: term boundaries, no-class dates, day swaps, precomputed class days.</li>
<li><a href="rwu-academic-calendar.json"><code>rwu-academic-calendar.json</code></a>
— every event with its classification.</li>
</ul>

<h2>Retired academic years</h2>
<p>A year retires when its spring term ends — the point it stops being the one
to plan against. Retired years stay published and keep working; they are simply
no longer what this page leads with.</p>
<div class="wrap"><table>
<tr><th>Academic year</th><th>Retired</th><th>Download</th><th>Subscribe</th>
<th>JSON</th></tr>
{retired}
</table></div>

<footer>
<a href="{REPO_URL}">Source and documentation on GitHub</a> ·
Last extracted from rwu.edu: {current.retrieved if current else '—'}
</footer>
{_COPY_JS}
</body></html>
"""
    return html.encode()


def build(years: list[AcademicYear], outdir: str | Path,
          today: _dt.date | None = None) -> list[Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def w(name: str, data) -> None:
        p = out / name
        p.write_bytes(data if isinstance(data, bytes)
                      else json.dumps(data, indent=2).encode() + b'\n')
        written.append(p)

    w('rwu-academic-calendar.ics', to_ics(years, 'RWU Academic Calendar (unofficial)'))
    w('rwu-no-class-days.ics', to_ics(years, 'RWU No-Class Days (unofficial)',
                                      predicate=lambda e: e.no_classes or e.observes_schedule_of))
    w('rwu-academic-calendar.json', to_json(years))
    w('no-class-days.json', to_no_class_json(years))

    for ay in years:
        slug = ay.academic_year
        w(f'{slug}.ics', to_ics([ay], f'RWU Academic Calendar {slug} (unofficial)'))
        w(f'{slug}.json', to_json([ay]))
    w('index.html', to_index_html(years, today))
    w('.nojekyll', b'')     # Pages would otherwise skip nothing here, but be explicit
    return written
