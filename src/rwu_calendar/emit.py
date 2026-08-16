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
            days, nc = {}, {e.date: e for e in t.events if e.no_classes}
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


def _retired_rows(years: list[AcademicYear], today: _dt.date) -> str:
    out = []
    for ay in sorted(years, key=lambda a: a.academic_year, reverse=True):
        end = retires_on(ay)
        out.append(
            f'<tr><td><strong>{_e(ay.academic_year)}</strong></td>'
            f'<td>{end:%-d %b %Y}</td>'
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

<form id="sched" autocomplete="off">
<p><label><strong>Term</strong> <select id="term"></select></label></p>
<div id="courses"></div>
<p>
<button type="button" id="add" class="btn alt">+ Add another item</button>
<button type="submit" class="btn">Download my schedule</button>
</p>
</form>
<div id="preview" class="preview" hidden></div>
<p class="tip">Times are saved as local wall-clock time, so an 11:00 meeting
stays at 11:00 across the November clock change. This is a one-time download,
not a subscription: it is built from your own entries, which no server here
knows about. For the academic calendar itself, subscribe to a feed above.</p>
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

  function addItem(prev) {
    const row = document.createElement('div');
    row.className = 'course';
    row.innerHTML = `
      <div class="crow">
        <label class="grow">Name<input type="text" name="name" placeholder="e.g. BIO 320 Lecture, Office hours, Dept meeting"></label>
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
        <button type="button" class="rm" title="Remove this item">Remove</button>
      </div>
      <div class="crow rules">
        <label>Repeats<select name="repeat">${
          REPEATS.map(([v,l]) => `<option value="${v}">${l}</option>`).join('')
        }</select></label>
        <label class="chk"><input type="checkbox" name="swaps" checked>
          Follows the class timetable
          <span class="why" title="RWU moves one day each term onto another weekday's timetable. Tick this for classes and office hours; untick it for meetings and clubs, which keep their own day.">?</span></label>
        <label class="chk"><input type="checkbox" name="skip" checked>
          Skips holidays and breaks</label>
      </div>
      <div class="crow datebox" hidden>
        <label class="grow">Dates, one per line as YYYY-MM-DD
          <textarea name="dates" rows="3" placeholder="2026-09-15&#10;2026-10-20"></textarea></label>
      </div>`;
    row.querySelector('.rm').addEventListener('click', () => {
      row.remove(); if (!courses.children.length) addItem(); update();
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

  function badDates(c) {
    if (c.repeat !== 'dates') return [];
    const t = GRID[termSel.value];
    return c.dates.split(/[\s,]+/).filter(Boolean).filter(
      s => !/^\d{4}-\d{2}-\d{2}$/.test(s) || !(s in t.days));
  }

  function occurrences(termId, c) {
    const t = GRID[termId];
    if (c.repeat === 'dates') {
      return c.dates.split(/[\s,]+/).filter(Boolean)
        .filter(s => /^\d{4}-\d{2}-\d{2}$/.test(s) && s in t.days).sort();
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

  function update() {
    const t = GRID[termSel.value];
    const rows = read().filter(c => c.name && (c.repeat === 'dates' || c.days.length));
    if (!rows.length) { preview.hidden = true; return; }
    preview.hidden = false;
    preview.innerHTML = '<h3>What you will get</h3>' + rows.map(c => {
      const bad = badDates(c);
      if (bad.length) return `<div class="pv"><strong>${h(c.name)}</strong>
        <ul class="notes"><li class="lose">Not usable: ${h(bad.slice(0,4).join(', '))}
        — use YYYY-MM-DD, and only dates inside ${h(t.label)}.</li></ul></div>`;
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

  const esc = s => String(s).replace(/([\;,])/g, '\\$1').replace(/\n/g, '\\n');
  const stamp = d => d.replace(/-/g, '');
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
      'X-WR-CALNAME:' + esc('My schedule — ' + GRID[termId].label)];
    for (const c of rows) {
      const s = series(termId, c);
      if (!s) continue;
      const at = d => stamp(d) + 'T' + c.start.replace(':','') + '00';
      const first = s.byRule.length ? s.byRule[0] : s.meetings[0];
      out.push('BEGIN:VEVENT',
        `UID:${uid(termId+'|'+c.name+'|'+c.days.join(',')+'|'+c.start+'|'+c.repeat)}@rwu-academic-calendar`,
        'DTSTAMP:20000101T000000Z',
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
    return out.join('\r\n') + '\r\n';   // RFC 5545 wants CRLF
  }

  document.getElementById('add').addEventListener('click', () => {
    addItem(read().pop()); update();
  });
  termSel.addEventListener('change', update);

  document.getElementById('sched').addEventListener('submit', ev => {
    ev.preventDefault();
    const rows = read().filter(c => c.name && c.start && c.end
                                 && (c.repeat === 'dates' ? c.dates.trim() : c.days.length));
    if (!rows.length) { alert('Add a name, a start and end time, and either meeting days or a list of dates.'); return; }
    const bad = rows.find(c => c.end <= c.start);
    if (bad) { alert(`"${bad.name}" ends at or before it starts.`); return; }
    const wrong = rows.find(c => badDates(c).length);
    if (wrong) { alert(`"${wrong.name}" has dates this tool cannot use. See the preview.`); return; }
    const blob = new Blob([ics(termSel.value, rows)], {type: 'text/calendar'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `my-schedule-${termSel.value}.ics`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });

  addItem(); update();
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


def to_index_html(years: list[AcademicYear], today: _dt.date | None = None) -> bytes:
    """A plain landing page for GitHub Pages. No assets, no external requests."""
    today = today or _dt.date.today()
    current = pick_current(years, today)
    others = [ay for ay in years if ay is not current]
    src = years[0].source_url if years else ''

    cur_ics = f'{current.academic_year}.ics' if current else PRIMARY_FEED
    hero_terms = _term_cards(current, today) if current else ''
    retired = _retired_rows(others, today)
    term_feeds = _term_feed_rows(current, today) if current else ''
    grid = json.dumps(meeting_grid(current) if current else {}, separators=(',', ':'))

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RWU Academic Calendar — unofficial feeds</title>
<meta name="description" content="Unofficial subscribable calendar feeds (ICS) and JSON for the Roger Williams University academic calendar.">
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
 .course {{ border: 1px solid var(--line); border-radius: 8px; padding: .8rem 1rem;
           margin: .75rem 0; }}
 .crow {{ display: flex; flex-wrap: wrap; gap: .75rem; align-items: flex-end;
         margin-bottom: .5rem; }}
 .crow:last-child {{ margin-bottom: 0; }}
 .crow label {{ display: flex; flex-direction: column; gap: .2rem;
               font-size: .8rem; font-weight: 700; color: #8889;
               text-transform: uppercase; letter-spacing: .04em; }}
 .crow label.grow {{ flex: 1 1 16rem; }}
 input[type=text], input[type=time], select {{ font: inherit; padding: .4rem .5rem;
   border: 1px solid var(--line); border-radius: 6px; background: transparent;
   color: inherit; text-transform: none; letter-spacing: normal; }}
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
 .why {{ display: inline-flex; align-items: center; justify-content: center;
        width: 1.1em; height: 1.1em; border-radius: 50%; font-size: .75rem;
        border: 1px solid var(--line); color: #8889; cursor: help; }}
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
<p class="eyebrow">Current academic year</p>
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
</ul>
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

<footer>
<a href="{REPO_URL}">Source and documentation on GitHub</a> ·
Last extracted from rwu.edu: {_e(current.retrieved) if current else '—'}
</footer>
<script type="application/json" id="grid">{grid}</script>
{_BUILDER_JS}
{_COPY_JS}
</body></html>
"""
    return html.encode()


def _term_title(t) -> str:
    year = t.classes_begin.year if t.classes_begin else t.academic_year
    return f'{t.term.title()} {year}'


def _only_term(ay: AcademicYear, term_id: str) -> AcademicYear:
    """A one-term copy of an academic year, for the per-term feeds."""
    out = AcademicYear(ay.academic_year, ay.source_url, ay.retrieved)
    out.terms = [t for t in ay.terms if t.id == term_id]
    return out


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
        # One feed per term as well. A whole-year feed is all or nothing, and
        # someone who does not teach in January should not have to carry the
        # Winter intersession in their calendar to get Fall and Spring.
        for t in ay.terms:
            single = _only_term(ay, t.id)
            w(f'{t.id}.ics', to_ics([single], f'RWU {_term_title(t)} (unofficial)'))
            w(f'{t.id}.json', to_json([single]))
    w('index.html', to_index_html(years, today))
    w('.nojekyll', b'')     # Pages would otherwise skip nothing here, but be explicit
    return written
