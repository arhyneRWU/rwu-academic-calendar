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
import html
import json
import re
from pathlib import Path

from icalendar import Calendar, Event as IcsEvent

from . import courses
from .model import TERMS, AcademicYear, Event, Term, link

PRODID = '-//arhyneRWU//RWU Academic Calendar (unofficial)//EN'
_DISCLAIMER = ('UNOFFICIAL. Derived from the public RWU academic calendar page; '
               'not published or endorsed by Roger Williams University. '
               'Verify against the official calendar before relying on it.')


def _uid(ay: str, term: str, date: _dt.date, label: str) -> str:
    """Stable per (year, term, date, label).

    A UID that changes between builds makes every subscribed calendar append a
    duplicate on each poll until it is unusable. This is *the* classic ICS bug,
    so the UID is derived from content and never from build time.

    ``session`` is deliberately *not* part of the key. It once was, to stop
    summer's six overlapping sessions colliding -- but the honest fix is one
    event per calendar day carrying every session that shares it, which is what
    :func:`to_ics` now emits. Keying on session instead put Memorial Day in a
    subscriber's calendar four times over.
    """
    key = f'{ay}|{term}|{date.isoformat()}|{label}'
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    return f'{h}@rwu-academic-calendar.arhyneRWU.github.io'


def _merge(evs: list[Event]) -> Event:
    """Collapse rows that share a date and label into the one day they describe.

    Fields are unioned rather than taken from the first row: RWU's summer table
    repeats each holiday once per session, and in 2024 one of those copies read
    "All University office Closed" (singular) while its siblings read "Offices".
    Taking the first row would have made the office status a coin toss.
    """
    first = evs[0]
    if len(evs) == 1:
        return first
    kinds: list[str] = []
    for e in evs:
        for k in e.kinds:
            if k not in kinds:
                kinds.append(k)
    offices = next((e.offices_closed for e in evs if e.offices_closed is not None), None)
    observes = next((e.observes_schedule_of for e in evs if e.observes_schedule_of), None)
    return Event(date=first.date, label=first.label, kinds=kinds,
                 no_classes=any(e.no_classes for e in evs),
                 offices_closed=offices, observes_schedule_of=observes,
                 span_id=first.span_id, source_text=first.source_text,
                 stated_day=first.stated_day, session=first.session,
                 owner_term=first.owner_term)


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
            # One VEVENT per calendar day, not per source row. Summer's six
            # overlapping sessions each repeat the same holidays verbatim, so
            # emitting a row per event put Memorial Day in every subscriber's
            # calendar four times and Juneteenth three. The sessions that share
            # a date are listed in the description instead.
            groups: dict[tuple, list[Event]] = {}
            for e in t.events:
                if predicate and not predicate(e):
                    continue
                groups.setdefault((e.date, e.label), []).append(e)
            for (date, label), evs in sorted(groups.items(), key=lambda kv: kv[0]):
                e = _merge(evs)
                ev = IcsEvent()
                # Keyed on the term the event was *printed* under, so a holiday
                # that two terms both claim (MLK, in Winter and Spring) has one
                # identity. Subscribe to both feeds and your calendar shows it
                # once.
                ev.add('uid', _uid(ay.academic_year, e.owner_term or t.id, date, label))
                ev.add('dtstamp', stamp)
                ev.add('dtstart', e.date)                       # all-day
                ev.add('dtend', e.date + _dt.timedelta(days=1))  # DTEND is exclusive
                ev.add('summary', _summary(e))
                ev.add('transp', 'TRANSPARENT')
                desc = [f'Term: {t.id}', f'Academic year: {ay.academic_year}',
                        f'Categories: {", ".join(e.kinds)}']
                sessions = sorted({x.session for x in evs if x.session})
                for s in sessions:
                    desc.append(f'Session: {s}')
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
                    for e in t.no_class_events()
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


def _e(v) -> str:
    """Escape a value on its way into HTML.

    Everything the page renders that is not a literal ultimately derives from
    rwu.edu. ``_txt()`` in the extractor strips tags and *then* unescapes
    entities, so a label written upstream as ``&lt;img src=x onerror=...&gt;``
    comes back as live markup. That is correct for the JSON and ICS feeds,
    whose serializers encode it safely -- but HTML has no such protection, so
    it is escaped here, at the sink.
    """
    return html.escape(str(v), quote=True)


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
    what = (f'runs a {_e(e.observes_schedule_of.title())} schedule'
            if e.observes_schedule_of else _e(e.label))
    return (f'<p class="next"><strong>Next:</strong> {d:%A %-d %B %Y} ({when}) — {what}</p>')


_WD_CODE = {'monday': 'M', 'tuesday': 'T', 'wednesday': 'W',
            'thursday': 'R', 'friday': 'F'}


def _slug(session: str | None) -> str:
    if not session:
        return 'main'
    return re.sub(r'[^a-z0-9]+', '-', session.lower()).strip('-')[:40]


def _session_label(session: str | None) -> str:
    """"Important Summer I term Dates 4 Week Session, May 21 - June 13" is not
    a thing to put in a dropdown. Keep the part that identifies the session."""
    if not session:
        return ''
    m = re.search(r'(\d+\s*week\s*session.*)', session, re.I)
    text = m.group(1) if m else session
    return re.sub(r'\s+', ' ', text).strip().rstrip(',')


def meeting_grid(ay: AcademicYear) -> dict:
    """For each term, every teaching date mapped to the weekday it *runs as*.

    This is what makes a personal schedule builder correct without
    reimplementing day-swap rules in JavaScript. The browser only has to ask
    "is this date's effective weekday one I teach?" -- all the reasoning
    happened here, in tested Python.

    A Tuesday that runs Monday's timetable appears as ``monday``, so a T/Th
    course correctly skips it and an M/W course correctly gains it.
    """
    out = {}
    for t in ay.terms:
        sessions = t.sessions()
        multi = len(sessions) > 1
        for key, (begin, end) in sorted(sessions.items(), key=lambda kv: kv[1]):
            days, nc = {}, {e.date: e for e in t.no_class_events()}
            d = begin
            while d <= end:
                if d.weekday() < 5:
                    eff = t.effective_weekday(d)
                    ev = nc.get(d)
                    # Three characters: the weekday this date RUNS AS ('-' if
                    # no class), whether classes meet, and whether RWU said
                    # offices were closed ('.' = the page did not say, which is
                    # 33 of 92 no-class days and must not be read as "open").
                    days[d.isoformat()] = (
                        (_WD_CODE[eff] if eff else '-')
                        + ('N' if ev else '.')
                        + ('.' if ev is None or ev.offices_closed is None
                           else 'C' if ev.offices_closed else 'O'))
                d += _dt.timedelta(days=1)
            if not any(v[0] != '-' for v in days.values()):
                continue
            # One entry per session, so a student in summer's 4-week session is
            # never offered dates from the 10-week one.
            gid = f'{t.id}::{_slug(key)}' if multi else t.id
            label = f'{t.term.title()} {begin:%Y}'
            if multi:
                label += f' \u2014 {_session_label(key)}'
            out[gid] = {
                'label': label,
                'begin': begin.isoformat(),
                'end': end.isoformat(),
                'days': days,
                'swaps': {e.date.isoformat(): e.observes_schedule_of
                          for e in t.day_swaps() if begin <= e.date <= end},
            }
    return out


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
<h3>{_e(t.term.title())} {t.classes_begin:%Y} {state}</h3>
<p class="dates">{t.classes_begin:%a %-d %b %Y} <span class="dash">→</span>
{t.classes_end:%a %-d %b %Y}</p>
<dl>
<div><dt>Class days</dt><dd>{len(t.class_days())}</dd></div>
<div><dt>No-class days</dt><dd>{len(t.no_class_dates())}</dd></div>
<div><dt>Day swap</dt><dd>{swap_txt}</dd></div>
</dl></div>""")
    return ''.join(out)


def missing_terms(ay: AcademicYear) -> list[str]:
    """Terms of this academic year that RWU has not published yet.

    RWU releases the four tables at different times -- Summer 2027 is simply
    not on the page as of August 2026. The term picker and the builder's
    dropdown then show three options and no explanation, and someone planning
    a summer course finds a silent absence rather than an answer.
    """
    y1, y2 = (int(p) for p in ay.academic_year.split('-'))
    have = {t.term for t in ay.terms if t.events}
    return [f'{term.title()} {y1 if term == "fall" else y2}'
            for term in TERMS if term not in have]


def _missing_note(ay: AcademicYear) -> str:
    missing = missing_terms(ay)
    if not missing:
        return ''
    which = ', '.join(missing[:-1]) + ' and ' + missing[-1] if len(missing) > 1 \
        else missing[0]
    verb = 'has' if len(missing) == 1 else 'have'
    return (f'<p class="tip"><strong>{_e(which)}</strong> {verb} not been '
            f'published by RWU yet, so {"it is" if len(missing) == 1 else "they are"} '
            f'not listed above and {"does" if len(missing) == 1 else "do"} not appear '
            f'in the schedule builder. Nothing is broken — the dates do not exist '
            f'anywhere public yet. They appear here within a week of RWU posting '
            f'them.</p>')


def _term_feed_rows(ay: AcademicYear, today: _dt.date) -> str:
    out = []
    for t in ay.terms:
        if not t.classes_begin:
            continue
        state = ('in session' if t.classes_begin <= today <= t.classes_end
                 else 'upcoming' if today < t.classes_begin else 'finished')
        out.append(
            f'<tr><td><strong>{_e(_term_title(t))}</strong><br>'
            f'<span class="tiny">{t.classes_begin:%-d %b} \u2013 '
            f'{t.classes_end:%-d %b %Y} \u00b7 {state}</span></td>'
            f'<td><a class="btn small" href="{_e(webcal(t.id + ".ics"))}">Subscribe</a></td>'
            f'<td><a href="{_e(t.id)}.ics">.ics</a></td>'
            f'<td><a href="{_e(t.id)}.json">.json</a></td></tr>')
    return ''.join(out)


def _year_rows(years: list[AcademicYear], today: _dt.date) -> str:
    out = []
    for ay in sorted(years, key=lambda a: a.academic_year, reverse=True):
        end = retires_on(ay)
        # A year with no fall or spring term -- which is what a half-extracted
        # new year looks like, because RWU publishes the summer table first --
        # has no retirement date at all. Formatting None here used to take the
        # whole build down with a TypeError.
        when = f'{end:%-d %b %Y}' if end else '&mdash;'
        out.append(
            f'<tr><td><strong>{_e(ay.academic_year)}</strong></td>'
            f'<td>{when}</td>'
            f'<td><a href="{_e(ay.academic_year)}.ics">.ics</a></td>'
            f'<td><a href="{_e(webcal(ay.academic_year + ".ics"))}">subscribe</a></td>'
            f'<td><a href="{_e(ay.academic_year)}.json">.json</a></td></tr>')
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

_BUILDER_HTML = """
<h2 id="builder">Build your own schedule</h2>
<p>Classes, office hours, lab or committee meetings, clubs, practices — anything
that repeats. You get one calendar file with every occurrence worked out against
the academic calendar. Nothing is uploaded; the file is made in your browser.</p>

<ol class="steps">
<li>Pick your term</li><li>Add your classes and anything else</li><li>Download and import</li>
</ol>

<form id="sched" autocomplete="off">
<p><label><strong>Term</strong> <select id="term"></select></label></p>

<!-- These two checkboxes carry the whole correctness model, and ticking the
     wrong one produces a calendar that looks entirely right. The explanation
     used to live in a title= tooltip, which needs a mouse hover: on a phone,
     where most people meet this, it did not exist at all. A <details> works on
     touch and keyboard, is read out by screen readers, and needs no script. -->
<details class="explain" open>
<summary>What do “Follows the class timetable” and “Skips holidays” mean?</summary>
<p><strong>Follows the class timetable</strong> — every fall and spring term,
RWU moves one day onto a <em>different weekday's</em> timetable: Tuesday 13
October 2026 runs Monday's schedule. Leave this ticked for <strong>classes and
office hours</strong>, which move with it. Untick it for <strong>meetings,
clubs and practices</strong>, which keep their own day and ignore the swap.</p>
<p><strong>Skips holidays and breaks</strong> — leave it ticked and no
occurrence lands on a no-class day. Untick it if the thing still meets over a
break, as some labs, teams and research groups do.</p>
<p class="tip">Not sure? Leave both ticked — that is right for anything that
follows the university's class schedule. Check the preview below before you
download: it names every date you gain and every date you lose.</p>
</details>

<!-- Only shown for terms whose course data has been pulled; hidden by
     default so the builder is unchanged when there is none. -->
<div id="catalog" class="catalog" hidden>
<p><strong>Your classes</strong> — pick them from RWU's catalog
<span class="tiny" id="catalog-stamp"></span></p>
<div class="crow">
<label>Subject <select id="cat-subject"></select></label>
<label class="grow">Course <select id="cat-section" disabled></select></label>
<button type="button" id="cat-add" class="btn alt" disabled>Add</button>
</div>
<p class="said" id="cat-said" role="status" hidden></p>
<p class="tip" id="cat-note">Days, times and room come from Roger Central.
The <em>dates</em> come from the academic calendar above, so holidays and the
day swap are already handled. Check anything that moved during add/drop.</p>
</div>

<!-- This section exists because the blank row used to sit under the
     catalog picker with no heading, so it read as "the other way to add a
     course" and the button's "another item" inherited that meaning. The
     heading, not the button, is what says office hours and clubs belong
     here. The last clause matters for terms with no course data pulled:
     hand-entering a class has to stay obviously available. -->
<div class="manual">
<p><strong>Anything else that repeats</strong></p>
<p class="tip">Office hours, lab or committee meetings, club practices, work
shifts, a class the catalog doesn't list — anything with days and a time.</p>
<p><button type="button" id="add" class="btn alt">+ Add an item</button></p>
</div>

<h3 class="listhead">Your schedule so far</h3>
<div id="courses"></div>
<p class="tip" id="empty">Nothing added yet — add a class above, or an item of
your own.</p>

<p><button type="submit" class="btn">Download my schedule</button></p>
<div id="done" class="done" role="status" hidden></div>
</form>
<div id="preview" class="preview" aria-live="polite" hidden></div>

<details><summary><strong>How to import the file you just downloaded</strong></summary>
<p>The download is a standard <code>.ics</code> calendar file. Every app below can
read it — but only iPhone opens it by tapping. On a computer you have to
<em>import</em> it, which is a different menu in every app, and the step people
miss.</p>

<p><strong>iPhone / iPad</strong> — tap the downloaded file (Files → Downloads).
Calendar opens and offers <em>Add All</em>. Choose which calendar to add them to.</p>

<p><strong>Outlook, desktop (Windows or Mac)</strong> — do <em>not</em>
double-click the file; that opens one appointment and drops the rest.
<em>File → Open &amp; Export → Import/Export → Import an iCalendar (.ics) or
vCalendar file → </em>pick the file<em> → Import</em>. Choosing
<strong>Import</strong> rather than <em>Open as New</em> puts the classes in
your own calendar.</p>

<p><strong>Outlook on the web</strong> — <em>Calendar → Add calendar → Upload
from file</em>, choose the file, pick which calendar it lands in, then
<em>Import</em>.</p>

<p><strong>Outlook on a phone</strong> — the Outlook app cannot import a
calendar file; it has no Import menu at all. Import once at
<a href="https://outlook.office.com/calendar">outlook.office.com</a> using the
steps above and it syncs down to your phone within a few minutes. (Tapping the
file on a phone will offer to open it in Apple Calendar instead, which works
but puts it in a different calendar from your RWU one.)</p>

<p><strong>Google Calendar</strong> — must be done on a computer;
the mobile app cannot import a file. <em>Settings → Import &amp; export →
Import</em>, choose the file and the destination calendar, then
<em>Import</em>. It syncs to your phone afterwards.</p>

<p><strong>Calendar on a Mac</strong> — <em>File → Import</em>, choose the file,
then pick a calendar.</p>

<p class="tip">Import puts a fixed copy in your calendar. It does not follow
later changes — if your schedule changes, or RWU moves a date, build and import
again. Re-importing updates the same events rather than duplicating them,
because each one carries a name derived from the course itself.</p>
</details>

<p class="tip">Times are saved as local wall-clock time, so an 11:00 class stays
at 11:00 across the November clock change. This is a one-time download, not a
subscription: it is built from your own entries, which no server here knows
about. For the academic calendar itself, subscribe to a feed below.</p>
"""

_BUILDER_JS = r"""
<script>
(() => {
  const GRID = JSON.parse(document.getElementById('grid').textContent);
  const DAYS = [['monday','Mon'],['tuesday','Tue'],['wednesday','Wed'],
                ['thursday','Thu'],['friday','Fri']];
  const CODE = {monday:'M', tuesday:'T', wednesday:'W', thursday:'R', friday:'F'};
  const BYDAY = {monday:'MO', tuesday:'TU', wednesday:'WE', thursday:'TH', friday:'FR'};
  const ALARMS = [['','No reminder'],['PT5M','5 min before'],['PT10M','10 min before'],
    ['PT15M','15 min before'],['PT30M','30 min before'],['PT1H','1 hour before'],
    ['PT2H','2 hours before'],['P1D','1 day before']];
  const REPEATS = [['weekly','Every week'],['biweekly','Every other week'],
                   ['dates','Only on dates I list']];
  const termSel = document.getElementById('term');
  const courses = document.getElementById('courses');
  const preview = document.getElementById('preview');

  for (const [id, t] of Object.entries(GRID)) termSel.add(new Option(t.label, id));

  const pad = v => String(v).padStart(2, '0');
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const dateOf = s => new Date(s + 'T12:00:00');
  const actual = s => 'SMTWRFS'[dateOf(s).getDay()];   // Sun..Sat
  const cap = s => s[0].toUpperCase() + s.slice(1);
  const h = s => String(s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const mondayOf = s => { const d = dateOf(s); d.setDate(d.getDate() - ((d.getDay()+6)%7)); return d; };
  const weeksApart = (a, b) => Math.round((mondayOf(a) - mondayOf(b)) / 604800000);

  // Each item is a <details>: collapsed it is one readable line, expanded it is
  // the full form. Eight controls per course meant two courses filled the
  // screen, and for a course that came from the catalog every one of them
  // re-asked what the registrar had already answered. <details> rather than a
  // JS toggle so it works before any script runs and needs no state of its own.
  function addItem(prev, opts) {
    const fromCatalog = !!(opts && opts.fromCatalog);
    const row = document.createElement('div');
    row.className = 'course';
    row.innerHTML = `
      <details class="item"${fromCatalog ? '' : ' open'}>
      <summary>
        <span class="it-name">Untitled item</span>
        <span class="it-meta">not set up yet</span>
        ${fromCatalog ? '<span class="it-tag">from catalog</span>' : ''}
      </summary>
      <div class="crow">
        <label class="grow">Name<input type="text" name="name" placeholder="e.g. Office hours, Dept meeting, Crew practice, BIO 320 Lab"></label>
        <label>Room<input type="text" name="room" placeholder="optional"></label>
      </div>
      <div class="crow">
        <fieldset class="days"><legend>Meets on</legend>${
          DAYS.map(([v,l]) => `<label class="day"><input type="checkbox" name="day" value="${v}">${l}</label>`).join('')
        }</fieldset>
        <label>Start<input type="time" name="start"></label>
        <label>End<input type="time" name="end"></label>
        <label>Remind<select name="alarm">${
          ALARMS.map(([v,l]) => `<option value="${v}"${v===(prev?prev.alarm:'PT15M')?' selected':''}>${l}</option>`).join('')
        }</select></label>
      </div>
      <div class="crow rules">
        <label>Repeats<select name="repeat">${
          REPEATS.map(([v,l]) => `<option value="${v}">${l}</option>`).join('')
        }</select></label>
        <label class="chk"><input type="checkbox" name="swaps" checked>
          Follows the class timetable</label>
        <label class="chk"><input type="checkbox" name="skip" checked>
          Skips holidays and breaks</label>
      </div>
      <div class="crow datebox" hidden>
        <label class="grow">Dates, one per line as YYYY-MM-DD
          <textarea name="dates" rows="3" placeholder="2026-09-15&#10;2026-10-20"></textarea></label>
      </div>
      </details>
      <button type="button" class="rm" title="Remove this item">Remove</button>`;
    row.querySelector('.rm').addEventListener('click', () => {
      row.remove(); update();
    });
    const rep = row.querySelector('[name=repeat]'), box = row.querySelector('.datebox');
    const sync = () => { box.hidden = rep.value !== 'dates';
                         row.querySelector('.days').disabled = rep.value === 'dates'; };
    rep.addEventListener('change', sync);
    row.addEventListener('input', update);
    row.addEventListener('change', () => { sync(); update(); });
    courses.append(row);
    return row;
  }

  function read() {
    return [...courses.children].map(row => ({
      name: row.querySelector('[name=name]').value.trim(),
      room: row.querySelector('[name=room]').value.trim(),
      days: [...row.querySelectorAll('[name=day]:checked')].map(c => c.value),
      start: row.querySelector('[name=start]').value,
      end: row.querySelector('[name=end]').value,
      alarm: row.querySelector('[name=alarm]').value,
      repeat: row.querySelector('[name=repeat]').value,
      swaps: row.querySelector('[name=swaps]').checked,
      skip: row.querySelector('[name=skip]').checked,
      dates: row.querySelector('[name=dates]').value,
    }));
  }
  const alarmLabel = v => (ALARMS.find(a => a[0] === v) || ALARMS[0])[1];

  // Each grid entry is three characters: the weekday this date RUNS AS ('-' if
  // no class meets), whether classes meet, and RWU's stated office status
  // ('.' means the page did not say -- never read that as "open").
  function keeps(c, date, code) {
    if (c.skip && code[1] === 'N') return false;
    const want = c.days.map(d => CODE[d]);
    if (c.swaps && code[0] !== '-') return want.includes(code[0]);
    return want.includes(actual(date));
  }

  // A listed date is usable if it is a real date inside the term. It does NOT
  // have to appear in t.days: the grid holds weekdays only, so testing
  // membership there rejected every Saturday and Sunday -- and told the user
  // their perfectly valid date was "not inside" a term it was plainly inside.
  // Clubs, practices and weekend labs are half of what this builder is for.
  const usable = (s, t) => /^\d{4}-\d{2}-\d{2}$/.test(s) && iso(dateOf(s)) === s
                           && s >= t.begin && s <= t.end;

  function badDates(c) {
    if (c.repeat !== 'dates') return [];
    const t = GRID[termSel.value];
    return c.dates.split(/[\s,]+/).filter(Boolean).filter(s => !usable(s, t));
  }

  function occurrences(termId, c) {
    const t = GRID[termId];
    if (c.repeat === 'dates') {
      // Listed dates are taken literally, holidays included: naming a date is
      // a stronger statement than any checkbox.
      return c.dates.split(/[\s,]+/).filter(Boolean).filter(s => usable(s, t)).sort();
    }
    let hits = Object.entries(t.days).filter(([d, code]) => keeps(c, d, code))
                     .map(([d]) => d).sort();
    if (c.repeat === 'biweekly' && hits.length) {
      const anchor = hits[0];
      hits = hits.filter(d => weeksApart(d, anchor) % 2 === 0);
    }
    return hits;
  }

  function series(termId, c) {
    const meetings = occurrences(termId, c);
    if (!meetings.length) return null;
    if (c.repeat === 'dates') return {meetings, byRule: [], exdate: [], rdate: meetings};
    const step = c.repeat === 'biweekly' ? 2 : 1;
    const last = meetings[meetings.length - 1], byRule = [];
    for (const d = dateOf(meetings[0]); iso(d) <= last; d.setDate(d.getDate() + 1)) {
      const s = iso(d);
      if (!c.days.map(x => CODE[x]).includes(actual(s))) continue;
      if (step === 2 && weeksApart(s, meetings[0]) % 2 !== 0) continue;
      byRule.push(s);
    }
    const inRule = new Set(byRule), isMeeting = new Set(meetings);
    return {meetings, byRule, step,
            exdate: byRule.filter(d => !isMeeting.has(d)),
            rdate: meetings.filter(d => !inRule.has(d))};
  }

  const fmt = s => dateOf(s).toLocaleDateString(undefined,
      {weekday:'short', day:'numeric', month:'short', year:'numeric'});

  // '09:00' -> '9:00 AM'. The form takes 24-hour input; the summary line reads
  // better in the same clock people say out loud.
  const hm12 = t => {
    if (!t) return '';
    const [H, M] = t.split(':').map(Number);
    return `${((H + 11) % 12) + 1}:${pad(M)} ${H < 12 ? 'AM' : 'PM'}`;
  };

  // The collapsed line. It has to say enough that nobody needs to expand a row
  // to check it, and say what is MISSING when the row is not usable yet --
  // otherwise an incomplete item just silently fails to appear in the preview.
  function describeItem(c) {
    if (!c.name) return 'add a name';
    if (c.repeat === 'dates') {
      if (!c.dates.trim()) return 'no dates listed yet';
      const bad = badDates(c);
      if (bad.length) return `${bad.length} date${bad.length === 1 ? '' : 's'} not usable`;
      const n = occurrences(termSel.value, c).length;
      return `${n} listed date${n === 1 ? '' : 's'}`
             + (c.start ? ` · ${hm12(c.start)}` : '') + (c.room ? ` · ${c.room}` : '');
    }
    if (!c.days.length) return 'pick the days it meets';
    if (!c.start || !c.end) return 'add a start and end time';
    const s = series(termSel.value, c);
    const n = s ? s.meetings.length : 0;
    return `${c.days.map(d => CODE[d]).join('')} ${hm12(c.start)}–${hm12(c.end)}`
           + (c.room ? ` · ${c.room}` : '')
           + ` · ${n} date${n === 1 ? '' : 's'}`;
  }

  function refreshItems(all) {
    [...courses.children].forEach((row, i) => {
      const c = all[i];
      if (!c) return;
      row.querySelector('.it-name').textContent = c.name || 'Untitled item';
      row.querySelector('.it-meta').textContent = describeItem(c);
    });
  }

  function update() {
    const t = GRID[termSel.value];
    const all = read();
    refreshItems(all);
    document.getElementById('empty').hidden = courses.children.length > 0;
    const rows = all.filter(c => c.name && (c.repeat === 'dates' || c.days.length));
    if (!rows.length) { preview.hidden = true; return; }
    preview.hidden = false;
    preview.innerHTML = '<h3>What you will get</h3>' + rows.map(c => {
      const bad = badDates(c);
      if (bad.length) return `<div class="pv"><strong>${h(c.name)}</strong>
        <ul class="notes"><li class="lose">Not usable: ${h(bad.slice(0,4).join(', '))}
        — use YYYY-MM-DD, between ${fmt(t.begin)} and ${fmt(t.end)}.</li></ul></div>`;
      const s = series(termSel.value, c);
      if (!s) return `<div class="pv"><strong>${h(c.name)}</strong>
        <ul class="notes"><li class="lose">No occurrences in ${h(t.label)}.</li></ul></div>`;
      const notes = [];
      for (const [d, eff] of Object.entries(t.swaps)) {
        if (!(d in t.days)) continue;
        const falls = actual(d), want = c.days.map(x => CODE[x]);
        if (!c.swaps) continue;
        if (want.includes(CODE[eff]) && !want.includes(falls))
          notes.push(`<li class="gain">Gains ${fmt(d)} — that ${cap(dateOf(d).toLocaleDateString('en-US',{weekday:'long'}).toLowerCase())} runs a ${cap(eff)} schedule</li>`);
        else if (!want.includes(CODE[eff]) && want.includes(falls))
          notes.push(`<li class="lose">Skips ${fmt(d)} — it runs a ${cap(eff)} schedule</li>`);
      }
      // Where RWU says offices were open on a no-class day, say so: it is the
      // one case where a meeting might legitimately still happen.
      if (c.skip) for (const [d, code] of Object.entries(t.days)) {
        if (code[1] === 'N' && code[2] === 'O' && c.days.map(x => CODE[x]).includes(actual(d)))
          notes.push(`<li>Skips ${fmt(d)} — no classes, but RWU says offices are open. Untick “Skips holidays and breaks” if this still meets.</li>`);
      }
      const rem = c.alarm ? `reminder ${alarmLabel(c.alarm).replace(' before','')} before` : 'no reminder';
      return `<div class="pv"><strong>${h(c.name)}</strong> — <strong>${s.meetings.length}</strong>
        ${s.meetings.length === 1 ? 'date' : 'dates'}, ${fmt(s.meetings[0])} to
        ${fmt(s.meetings[s.meetings.length-1])}, ${rem}
        <ul class="notes">${notes.join('')}</ul></div>`;
    }).join('');
  }

  // Backslash MUST be escaped, and MUST be escaped first -- otherwise a room
  // like "C\D" emits \D, which is not a defined iCalendar escape and is
  // anyone's guess to parse. Doing it after the others would double-escape
  // the backslashes this function just added.
  const esc = s => String(s).replace(/\\/g, '\\\\')
                            .replace(/([;,])/g, '\\$1').replace(/\n/g, '\\n');
  const stamp = d => d.replace(/-/g, '');

  // RFC 5545: no content line over 75 octets. Folded lines continue with a
  // single leading space. Measured in UTF-8 bytes and split on code points, so
  // an em dash in a course name cannot be cut in half.
  const enc = new TextEncoder();
  function fold(line) {
    if (enc.encode(line).length <= 75) return line;
    const parts = [];
    let cur = '', len = 0;
    for (const ch of line) {
      const n = enc.encode(ch).length;
      if (len + n > (parts.length ? 74 : 75)) { parts.push(cur); cur = ''; len = 0; }
      cur += ch; len += n;
    }
    parts.push(cur);
    return parts.join('\r\n ');
  }
  const uid = s => {
    let a = 0x811c9dc5, b = 0x01000193;
    for (let i = 0; i < s.length; i++) {
      a ^= s.charCodeAt(i); a = Math.imul(a, 0x01000193);
      b ^= s.charCodeAt(s.length - 1 - i); b = Math.imul(b, 0x85ebca6b);
    }
    return ((a >>> 0).toString(16) + (b >>> 0).toString(16)).padStart(16, '0');
  };

  function ics(termId, rows) {
    const out = ['BEGIN:VCALENDAR','VERSION:2.0',
      'PRODID:-//arhyneRWU//RWU Academic Calendar (unofficial)//EN','CALSCALE:GREGORIAN',
      // METHOD:PUBLISH is what tells an importer this is a calendar to absorb
      // rather than a meeting invitation to reply to; Outlook in particular is
      // happier with it. X-WR-TIMEZONE tells Google and Outlook which zone to
      // read the floating times in, which is the point of floating times: an
      // 11:00 class stays at 11:00 through the November clock change.
      'METHOD:PUBLISH',
      'X-WR-TIMEZONE:America/New_York',
      'X-WR-CALNAME:' + esc('My schedule — ' + GRID[termId].label)];
    // Two rows can legitimately agree on name, days and start time -- the same
    // office hour held in two rooms, say. They used to hash to one UID, and a
    // calendar app importing two events with one identity keeps one of them.
    // The suffix is applied to later duplicates only, so the ordinary case
    // keeps the stable content-derived UID that makes re-import update in
    // place instead of appending.
    const used = new Map();
    for (const c of rows) {
      const s = series(termId, c);
      if (!s) continue;
      const at = d => stamp(d) + 'T' + c.start.replace(':','') + '00';
      const first = s.byRule.length ? s.byRule[0] : s.meetings[0];
      const key = uid(termId+'|'+c.name+'|'+c.days.join(',')+'|'+c.start+'|'+c.repeat);
      const n = (used.get(key) || 0) + 1;
      used.set(key, n);
      // A real DTSTAMP, and SEQUENCE. The published feeds freeze DTSTAMP so a
      // rebuild produces an empty git diff -- but this file is a personal
      // download, nothing diffs it, and a stamp frozen in the year 2000 breaks
      // the one thing UIDs are for: a client comparing timestamps sees a
      // re-import as no newer than what it already has and declines to update.
      out.push('BEGIN:VEVENT',
        `UID:${key}${n > 1 ? '-' + n : ''}@rwu-academic-calendar`,
        `DTSTAMP:${new Date().toISOString().replace(/[-:]/g,'').replace(/\.\d+/,'')}`,
        'SEQUENCE:0',
        `DTSTART:${at(first)}`,
        `DTEND:${stamp(first)}T${c.end.replace(':','')}00`);
      if (s.byRule.length) {
        out.push('RRULE:FREQ=WEEKLY' + (s.step === 2 ? ';INTERVAL=2' : '')
          + ';BYDAY=' + c.days.map(d => BYDAY[d]).join(',')
          + ';UNTIL=' + at(s.byRule[s.byRule.length-1]));
      }
      if (s.exdate.length) out.push('EXDATE:' + s.exdate.map(at).join(','));
      // With an RRULE, DTSTART is generated by the rule and must not be
      // repeated. With no RRULE it is only implicitly an occurrence, and
      // parsers disagree about that -- so list every date explicitly.
      const extra = s.byRule.length ? s.rdate.filter(d => d !== first) : s.rdate;
      if (extra.length) out.push('RDATE:' + extra.map(at).join(','));
      out.push(`SUMMARY:${esc(c.name)}`);
      if (c.room) out.push(`LOCATION:${esc(c.room)}`);
      out.push('DESCRIPTION:' + esc(
        'Generated from the unofficial RWU academic calendar. Verify against the '
        + 'official calendar.'));
      if (c.alarm) {
        out.push('BEGIN:VALARM','ACTION:DISPLAY',`TRIGGER:-${c.alarm}`,
          `DESCRIPTION:${esc(c.name + (c.room ? ' — ' + c.room : ''))}`,'END:VALARM');
      }
      out.push('END:VEVENT');
    }
    out.push('END:VCALENDAR');
    return out.map(fold).join('\r\n') + '\r\n';   // RFC 5545 wants CRLF
  }

  // ---- catalog picker -------------------------------------------------
  // Course data is fetched from THIS site, one small file per subject, only
  // when a subject is chosen. It supplies days, times and room. It never
  // supplies dates: Roger Central's section range runs through finals week
  // (Fall 2026 ends 12-09 there, 12-02 here), so using it would hand everyone
  // an extra week of classes that do not exist. The grid decides dates.
  const CATALOG = JSON.parse(document.getElementById('catalog-map').textContent);
  const box = document.getElementById('catalog');
  const subjSel = document.getElementById('cat-subject');
  const sectSel = document.getElementById('cat-section');
  const addBtn = document.getElementById('cat-add');
  const said = document.getElementById('cat-said');
  const catStamp = document.getElementById('catalog-stamp');
  const cache = new Map();
  let loaded = [];

  const base = () => `courses/${CATALOG[termSel.value]}`;

  async function loadIndex() {
    const slug = CATALOG[termSel.value];
    box.hidden = !slug;
    if (!slug) return;
    sectSel.innerHTML = ''; sectSel.disabled = true; addBtn.disabled = true;
    subjSel.innerHTML = '<option value="">Choose a subject…</option>';
    try {
      const idx = await (await fetch(`${base()}/index.json`)).json();
      for (const s of idx.subjects)
        subjSel.add(new Option(`${s.code} (${s.count})`, s.code));
      catStamp.textContent = idx.retrieved ? `pulled ${idx.retrieved}` : '';
    } catch (e) { box.hidden = true; }
  }

  async function loadSubject() {
    loaded = []; sectSel.innerHTML = ''; sectSel.disabled = true; addBtn.disabled = true;
    said.hidden = true;
    if (!subjSel.value) return;
    const url = `${base()}/${subjSel.value}.json`;
    try {
      if (!cache.has(url)) cache.set(url, await (await fetch(url)).json());
      loaded = cache.get(url).sections || [];
    } catch (e) { sectSel.add(new Option('could not load', '')); return; }
    sectSel.add(new Option(`Choose one of ${loaded.length}…`, ''));
    // Same shape as the collapsed item line, so what you pick and what you
    // then see listed read identically instead of one saying "wed 14:00-16:50"
    // and the other "W 2:00 PM–4:50 PM".
    loaded.forEach((s, i) => sectSel.add(new Option(
      `${s.section} ${s.title} — ${s.days.map(d => CODE[d] || '?').join('')} `
      + `${hm12(s.start)}–${hm12(s.end)}${s.room ? ' · ' + s.room : ''}`, String(i))));
    sectSel.disabled = false;
  }

  subjSel.addEventListener('change', loadSubject);
  sectSel.addEventListener('change', () => { addBtn.disabled = sectSel.value === ''; });
  addBtn.addEventListener('click', () => {
    const s = loaded[Number(sectSel.value)];
    if (!s) return;
    const row = addItem(read().pop(), {fromCatalog: true});
    row.querySelector('[name=name]').value = `${s.section} ${s.title}`.trim();
    row.querySelector('[name=room]').value = s.room || '';
    row.querySelector('[name=start]').value = s.start;
    row.querySelector('[name=end]').value = s.end;
    for (const cb of row.querySelectorAll('[name=day]')) cb.checked = s.days.includes(cb.value);
    const weekend = s.days.filter(d => d === 'saturday' || d === 'sunday');
    row.querySelector('[name=repeat]').value = 'weekly';
    update();

    // Adding used to be silent: the new row lands below the fold on a phone,
    // so the only evidence was a list you could not see. Say what happened,
    // clear the course picker for the next one, and flash the row itself.
    said.textContent = `Added ${s.section} — it is in “Your schedule so far” below.`;
    said.hidden = false;
    sectSel.selectedIndex = 0; addBtn.disabled = true;
    row.classList.add('just-added');
    setTimeout(() => row.classList.remove('just-added'), 2000);
    if (weekend.length) alert(
      `${s.section} meets on ${weekend.join(' and ')}, which this builder cannot `
      + `schedule yet — the academic calendar grid covers weekdays only. `
      + `The weekday part has been added.`);
  });

  document.getElementById('add').addEventListener('click', () => {
    addItem(read().pop()); update();
  });
  termSel.addEventListener('change', () => { update(); loadIndex(); });
  loadIndex();

  // A synthetic click on a detached anchor is not a reliable way to save a
  // file: iOS Safari and every in-app browser (Outlook's, Teams', Instagram's)
  // may decline it, and when they do nothing at all happens on screen. So the
  // link is REAL and stays on the page for the user to tap. The automatic
  // click is still attempted, because on a desktop it is the whole
  // interaction; it is just no longer the only route to the file.
  let lastUrl = null;
  function offer(text, name) {
    if (lastUrl) URL.revokeObjectURL(lastUrl);
    lastUrl = URL.createObjectURL(new Blob([text],
                {type: 'text/calendar;charset=utf-8'}));
    const done = document.getElementById('done');
    const a = document.createElement('a');
    a.href = lastUrl; a.download = name; a.className = 'btn';
    a.textContent = `Save ${name}`;
    done.innerHTML = '<p><strong>Your file is ready.</strong> If nothing '
      + 'downloaded on its own — phones and in-app browsers often block that '
      + '— use this link:</p>';
    done.append(a);
    const tip = document.createElement('p');
    tip.className = 'tip';
    tip.innerHTML = 'Then open <em>How to import the file you just '
      + 'downloaded</em> below. Outlook on a phone cannot import it; '
      + 'the instructions say what to do instead.';
    done.append(tip);
    done.hidden = false;
    a.click();
    done.scrollIntoView({block: 'nearest'});
  }

  document.getElementById('sched').addEventListener('submit', ev => {
    ev.preventDefault();
    const rows = read().filter(c => c.name && c.start && c.end
                                 && (c.repeat === 'dates' ? c.dates.trim() : c.days.length));
    if (!rows.length) {
      alert(courses.children.length
        ? 'Add a name, a start and end time, and either meeting days or a list of dates.'
        : 'Nothing to download yet. Add a class from the catalog, or add an item of your own.');
      return;
    }
    const bad = rows.find(c => c.end <= c.start);
    if (bad) { alert(`"${bad.name}" ends at or before it starts.`); return; }
    const wrong = rows.find(c => badDates(c).length);
    if (wrong) { alert(`"${wrong.name}" has dates this tool cannot use. See the preview.`); return; }
    offer(ics(termSel.value, rows), `my-schedule-${termSel.value}.ics`);
  });

  update();
})();
</script>
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


def to_index_html(years: list[AcademicYear], today: _dt.date | None = None,
                  catalog: dict[str, list[str]] | None = None) -> bytes:
    """A plain landing page for GitHub Pages. No assets, no external requests."""
    today = today or _dt.date.today()
    catalog = catalog or {}
    current = pick_current(years, today)
    others = [ay for ay in years if ay is not current]
    src = years[0].source_url if years else ''

    cur_ics = f'{current.academic_year}.ics' if current else PRIMARY_FEED
    hero_terms = _term_cards(current, today) if current else ''
    # Split, rather than "everything that is not current". A newly extracted
    # year is not the current one either, and listing next year's calendar
    # under "Retired academic years" -- with a retirement date in the future --
    # is exactly the sort of thing nobody notices until someone trusts it.
    retired = _year_rows([ay for ay in others if is_retired(ay, today)], today)
    ahead = [ay for ay in others if not is_retired(ay, today)]
    upcoming = f"""
<h2>Published ahead of time</h2>
<p>Already extracted, not yet the year to plan against. These become the
featured year once the current one's spring term ends.</p>
<div class="wrap"><table>
<tr><th>Academic year</th><th>Retires</th><th>Download</th><th>Subscribe</th>
<th>JSON</th></tr>
{_year_rows(ahead, today)}
</table></div>""" if ahead else ''
    term_feeds = _term_feed_rows(current, today) if current else ''
    # `json.dumps` does not escape '/', so an upstream label containing
    # "</script>" would close the block it is embedded in and the rest would be
    # parsed as markup. Nothing on RWU's page does today; the labels are still
    # scraped text, and this is the same sink class as the stored XSS in
    # SECURITY.md. < is valid JSON and parses back to '<'.
    grid = (json.dumps(meeting_grid(current) if current else {}, separators=(',', ':'))
            .replace('<', '\\u003c'))

    # When every extracted year has retired, `pick_current` falls back to the
    # most recent one -- correct, but the page then presents a finished year
    # under "Current academic year" and looks maintained when it is not. A
    # calendar that is quietly a year out of date is worse than one that is
    # obviously missing, so say it at the top, above everything.
    # Which of the grid's terms have course data pulled. Only terms RWU has
    # actually published appear, so this grows on its own rather than needing a
    # code change each time they post another term.
    course_terms = {tid: slug for tid, slug in
                    ((t, courses.rc_term_slug(t.split('::')[0]))
                     for t in (meeting_grid(current) if current else {}))
                    if slug and slug in catalog}
    course_map = json.dumps(course_terms, separators=(',', ':')).replace('<', '\\u003c')

    stale = bool(current and is_retired(current, today))
    eyebrow = 'Most recent academic year' if stale else 'Current academic year'
    stale_banner = (f"""
<p class="warn"><strong>This calendar is out of date.</strong> The most recent
data here covers <strong>{_e(current.academic_year)}</strong>, whose spring term
ended {retires_on(current):%-d %B %Y}. Nothing newer has been published to this
site yet, so <strong>do not plan against it</strong> — check the
<a href="{_e(src)}">official calendar</a> instead. (Last extracted from rwu.edu:
{_e(current.retrieved)}.)</p>""" if stale else '')

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">   <!-- an empty icon, declared so no /favicon.ico is requested -->
<title>RWU Academic Calendar — unofficial feeds</title>
<meta name="description" content="Unofficial subscribable calendar feeds (ICS) and JSON for the Roger Williams University academic calendar.">
<style>
 :root {{ color-scheme: light dark; --line:#8886; --accent:#2563eb; --warn:#c33; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --accent:#7aa2f7; }} }}
 * {{ box-sizing: border-box; }}
 /* The browser's own `[hidden] {{ display: none }}` loses to any author rule
    that sets `display`, and `.crow` sets `display: flex`. The date-list
    textarea was therefore visible on every course row, always, however the
    Repeats menu was set. Nothing in the markup looked wrong. */
 [hidden] {{ display: none !important; }}
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
 .banner {{ display: block; text-decoration: none; color: inherit;
           border: 2px solid var(--accent); border-radius: 12px;
           padding: 1.1rem 1.4rem; margin: 1.5rem 0;
           background: color-mix(in srgb, var(--accent) 9%, transparent); }}
 .banner:hover {{ background: color-mix(in srgb, var(--accent) 16%, transparent); }}
 .banner-kicker {{ display: block; text-transform: uppercase; letter-spacing: .08em;
                  font-size: .7rem; font-weight: 700; color: var(--accent); }}
 .banner-title {{ display: block; font-size: 1.45rem; font-weight: 700;
                 margin: .15rem 0 .35rem; }}
 .banner-sub {{ display: block; font-size: .95rem; }}
 .tiny {{ font-size: .8rem; color: #8889; white-space: nowrap; }}
 .btn.small {{ padding: .3rem .8rem; font-size: .85rem; }}
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
 .course {{ border: 1px solid var(--line); border-radius: 8px;
           margin: .75rem 0; display: flex; align-items: flex-start; gap: .5rem;
           padding: .6rem .8rem; }}
 .course .item {{ flex: 1 1 auto; min-width: 0; border: 0; padding: 0; margin: 0; }}
 .course summary {{ cursor: pointer; display: flex; flex-wrap: wrap;
                   align-items: baseline; gap: .5rem; }}
 .it-name {{ font-weight: 700; }}
 .it-meta {{ color: #8889; font-size: .9rem; }}
 .it-tag {{ font-size: .68rem; font-weight: 700; text-transform: uppercase;
           letter-spacing: .05em; padding: .1em .45em; border-radius: 99px;
           background: color-mix(in srgb, var(--accent) 18%, transparent);
           color: var(--accent); white-space: nowrap; }}
 .course details[open] summary {{ margin-bottom: .75rem; }}
 .steps {{ list-style: none; counter-reset: s; padding: 0; margin: 1.25rem 0 .5rem;
          display: flex; flex-wrap: wrap; gap: .4rem 1.5rem; }}
 .steps li {{ counter-increment: s; font-weight: 600; color: #8889; }}
 .steps li::before {{ content: counter(s); display: inline-flex;
   align-items: center; justify-content: center; width: 1.5em; height: 1.5em;
   margin-right: .45em; border-radius: 50%; font-size: .8em;
   background: color-mix(in srgb, var(--accent) 18%, transparent);
   color: var(--accent); }}
 .crow {{ display: flex; flex-wrap: wrap; gap: .75rem; align-items: flex-end;
         margin-bottom: .5rem; }}
 .crow:last-child {{ margin-bottom: 0; }}
 /* `min-width: 0` because a flex item defaults to `min-width: auto`, which
    refuses to shrink below its content. The course picker's longest option is
    a whole section line, so on a phone the select forced itself to 820px and
    the entire page scrolled sideways -- but only once a subject was chosen,
    which is why an earlier mobile check on the empty form found nothing. */
 .crow label {{ display: flex; flex-direction: column; gap: .2rem; min-width: 0;
               font-size: .8rem; font-weight: 700; color: #8889;
               text-transform: uppercase; letter-spacing: .04em; }}
 .crow label.grow {{ flex: 1 1 16rem; min-width: 0; }}
 /* `color: inherit` inherited the CAPTION grey above, so every value the user
    typed rendered at about 2.1:1 contrast and looked like placeholder text --
    a filled form was indistinguishable from an empty one. CanvasText is the
    system foreground and tracks `color-scheme: light dark` on its own. The
    explicit font-size matters for the same reason: `font: inherit` was picking
    up the caption's .8rem. */
 input[type=text], input[type=time], select, textarea {{
   font: inherit; font-size: .95rem; padding: .4rem .5rem;
   border: 1px solid var(--line); border-radius: 6px; background: transparent;
   color: CanvasText; text-transform: none; letter-spacing: normal; }}
 input::placeholder, textarea::placeholder {{ color: #8889; }}
 fieldset.days {{ border: 1px solid var(--line); border-radius: 6px;
                 padding: .2rem .6rem .4rem; margin: 0; display: flex; gap: .6rem; }}
 fieldset.days legend {{ font-size: .8rem; font-weight: 700; color: #8889;
                        text-transform: uppercase; letter-spacing: .04em;
                        padding: 0 .3rem; }}
 label.day {{ flex-direction: row !important; align-items: center; gap: .25rem;
             text-transform: none !important; color: inherit !important;
             font-weight: 600 !important; font-size: .95rem !important; }}
 .rm {{ font: inherit; font-size: .85rem; cursor: pointer; padding: .4rem .7rem;
       border-radius: 6px; border: 1px solid var(--line); background: transparent;
       color: #8889; }}
 .rm:hover {{ color: var(--warn); border-color: var(--warn); }}
 .preview {{ border: 1px solid var(--line); border-left: 4px solid var(--accent);
            border-radius: 0 8px 8px 0; padding: .8rem 1.1rem; margin: 1rem 0; }}
 .preview h3 {{ margin: 0 0 .5rem; font-size: 1rem; }}
 .pv {{ margin: .5rem 0; }}
 .notes {{ margin: .2rem 0 0; padding-left: 1.2rem; font-size: .9rem; }}
 .notes .lose {{ color: #b45309; }}
 .notes .gain {{ color: #16a34a; }}
 .rules {{ align-items: center; }}
 .chk {{ flex-direction: row !important; align-items: center; gap: .35rem;
        text-transform: none !important; color: inherit !important;
        font-weight: 600 !important; font-size: .92rem !important; }}
 .catalog, .manual {{ border: 1px solid var(--line); border-radius: 8px;
            padding: .8rem 1rem; margin: 1rem 0; }}
 .catalog p, .manual p {{ margin: 0 0 .5rem; }}
 .manual p:last-child {{ margin: 0; }}
 .listhead {{ font-size: .95rem; text-transform: uppercase;
              letter-spacing: .04em; color: #8889; margin: 1.5rem 0 .5rem; }}
 .catalog .crow {{ align-items: end; }}
 .catalog select {{ max-width: 100%; width: 100%; }}
 #cat-section {{ min-width: 0; }}
 #cat-note {{ margin: .6rem 0 0; }}
 .said {{ margin: .6rem 0 0; font-weight: 600; font-size: .92rem; }}
 .just-added {{ animation: flash 2s ease-out; }}
 @keyframes flash {{ from {{ background: #4f8cff33; }} to {{ background: transparent; }} }}
 .done {{ border: 1px solid var(--line); border-radius: 8px;
          padding: .8rem 1rem; margin: 1rem 0; }}
 .done p {{ margin: 0 0 .6rem; }}
 .done p:last-child {{ margin: .6rem 0 0; }}
 details.explain {{ margin: 1rem 0; background: #8881; }}
 details.explain summary {{ font-weight: 600; }}
 details.explain p {{ font-size: .93rem; margin: .6rem 0; }}
 details.explain p:last-child {{ margin-bottom: 0; }}
 textarea {{ font: inherit; font-size: .95rem; padding: .4rem .5rem; width: 100%;
            border: 1px solid var(--line); border-radius: 6px;
            background: transparent; color: inherit; text-transform: none;
            letter-spacing: normal; }}
 fieldset.days[disabled] {{ opacity: .4; }}
 ul.feeds {{ padding-left: 1.2rem; }}
 footer {{ margin-top: 3rem; color: #8889; font-size: .92em; }}
</style></head><body>

<h1>RWU Academic Calendar</h1>
<p class="sub">Subscribable calendar feeds and JSON, derived from RWU's public
academic calendar page.</p>
{stale_banner}

<a class="banner" href="#builder">
<span class="banner-kicker">Most people want this</span>
<span class="banner-title">Build your own class schedule &rarr;</span>
<span class="banner-sub">Enter your courses and times, get a calendar with every
meeting already worked out against the academic calendar — holidays removed, day
swaps applied, reminders optional, ending with the term.</span>
</a>

<p class="warn"><strong>Not an official Roger Williams University
publication.</strong> Derived by scraping the
<a href="{_e(src)}">public academic calendar page</a>; not endorsed by the
university. Verify against the official calendar before relying on it.</p>

<div class="hero">
<p class="eyebrow">{eyebrow}</p>
<h2>{_e(current.academic_year) if current else 'Calendar'}</h2>
{_next_milestone(current, today) if current else ''}
<div class="cards">{hero_terms}</div>
<div class="btns">
<a class="btn" href="{webcal(PRIMARY_FEED)}">Subscribe on this device</a>
<a class="btn alt" href="{webcal(cur_ics)}">Subscribe: {current.academic_year if current else ''} only</a>
<a class="btn alt" href="{PRIMARY_FEED}">Download .ics</a>
<a class="btn alt" href="#builder">Build my class schedule</a>
</div>
<p class="tip">Holidays, breaks and day swaps — add once and it stays current.
If a button does nothing, paste this link into your calendar app instead:</p>
{_urlbox(FEED_URL)}
</div>

{_BUILDER_HTML}

<h2 id="add-it-to-your-phone">Add it to your phone</h2>
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

<h2 id="terms">One term at a time</h2>
<p>The whole-year feed carries every term. If you don't teach in January, take
just the terms you want — each one is its own live subscription, so you can
add Fall and Spring and skip Winter entirely.</p>
<div class="wrap"><table>
<tr><th>Term</th><th>Add to calendar</th><th>Download</th><th>Data</th></tr>
{term_feeds}
</table></div>
{_missing_note(current) if current else ''}
<p class="tip">Whole year in one: <code>{SITE_URL}/{current.academic_year if current else ''}.ics</code></p>

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

<h2 id="privacy">Privacy &amp; security</h2>
<p><strong>Nothing you type here leaves your browser.</strong> The schedule
builder runs entirely on this page: your course names, rooms and times are
turned into a calendar file by the browser itself and handed straight to you as
a download. Nothing is uploaded, stored, or sent anywhere.</p>
<ul>
<li>No analytics, telemetry or tracking of any kind.</li>
<li>No cookies, no local storage.</li>
<li>No third-party requests — no CDN, no web fonts, no embedded widgets.
This page loads nothing from any other host.</li>
<li>No form that submits anywhere. There is no server to submit to.</li>
<li>Choosing a subject in the course picker reads one small file
<em>from this site</em> — the published course list. That is a download, not
an upload: nothing you typed is part of the request.</li>
</ul>
<p>The course lists are meeting patterns only — section, title, days, times and
room. Instructor names, seat counts and enrolment are deliberately not
collected, and are not in the published files.</p>
<p>You can check all of this yourself: view the page source, or open your
browser's network tab and watch it stay empty while you use the builder.</p>
<p>The full policy — threat model, dependency posture, and how to report a
problem — is in
<a href="{REPO_URL}/blob/main/SECURITY.md"><code>SECURITY.md</code></a>.</p>

<h2>Retired academic years</h2>
<p>A year retires when its spring term ends — the point it stops being the one
to plan against. Retired years stay published and keep working; they are simply
no longer what this page leads with.</p>
<div class="wrap"><table>
<tr><th>Academic year</th><th>Retired</th><th>Download</th><th>Subscribe</th>
<th>JSON</th></tr>
{retired}
</table></div>
{upcoming}

<footer>
<a href="{REPO_URL}">Source and documentation on GitHub</a> ·
Last extracted from rwu.edu: {_e(current.retrieved) if current else '—'}
</footer>
<script type="application/json" id="grid">{grid}</script>
<script type="application/json" id="catalog-map">{course_map}</script>
{_BUILDER_JS}
{_COPY_JS}
</body></html>
"""
    return html.encode()


def _term_title(t) -> str:
    year = t.classes_begin.year if t.classes_begin else t.academic_year
    return f'{t.term.title()} {year}'


def _only_term(ay: AcademicYear, term_id: str) -> AcademicYear:
    """A one-term copy of an academic year, for the per-term feeds.

    Carries in any no-class day RWU filed under a sibling term but which falls
    inside this one -- MLK Day, printed under Spring and landing in Winter.
    Without this the winter feed is a term with no holiday in it, which is the
    single most useful thing a term feed can tell you.
    """
    out = AcademicYear(ay.academic_year, ay.source_url, ay.retrieved)
    for t in ay.terms:
        if t.id != term_id:
            continue
        copy = Term(id=t.id, term=t.term, academic_year=t.academic_year,
                    events=sorted(t.events + t.inherited_no_class_events(),
                                  key=lambda e: (e.date, e.label)))
        out.terms = [copy]
    return link(out)


def _copy_courses(src: Path, out: Path) -> list[Path]:
    """Publish the committed course files, plus a per-term index.

    One file per subject, fetched only when someone picks that subject, so the
    landing page stays small. Copied rather than regenerated because — exactly
    like ``data/*.yaml`` — what is published is what is in git, and the build
    never touches the network.
    """
    written: list[Path] = []
    if not src.exists():
        return written
    for term_slug, subjects in sorted(courses.available(src).items()):
        dest = out / 'courses' / term_slug
        dest.mkdir(parents=True, exist_ok=True)
        index = {'term': term_slug, 'subjects': [], 'retrieved': None}
        for subject in subjects:
            doc = json.loads((src / term_slug / f'{subject}.json').read_text('utf-8'))
            p = dest / f'{subject}.json'
            p.write_text(json.dumps(doc, separators=(',', ':')) + '\n', encoding='utf-8')
            written.append(p)
            index['subjects'].append({'code': subject,
                                      'count': len(doc.get('sections') or [])})
            index['retrieved'] = doc.get('retrieved') or index['retrieved']
        p = dest / 'index.json'
        p.write_text(json.dumps(index, separators=(',', ':')) + '\n', encoding='utf-8')
        written.append(p)
    return written


def build(years: list[AcademicYear], outdir: str | Path,
          today: _dt.date | None = None,
          course_data: str | Path | None = None) -> list[Path]:
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
        # One feed per term as well. A whole-year feed is all or nothing, and
        # someone who does not teach in January should not have to carry the
        # Winter intersession in their calendar to get Fall and Spring.
        for t in ay.terms:
            single = _only_term(ay, t.id)
            w(f'{t.id}.ics', to_ics([single], f'RWU {_term_title(t)} (unofficial)'))
            w(f'{t.id}.json', to_json([single]))
    src = Path(course_data) if course_data else Path(__file__).resolve().parents[2] / 'data' / 'courses'
    catalog = courses.available(src)
    written += _copy_courses(src, out)
    w('index.html', to_index_html(years, today, catalog=catalog))
    w('.nojekyll', b'')     # Pages would otherwise skip nothing here, but be explicit
    return written
