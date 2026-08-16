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


def to_index_html(years: list[AcademicYear]) -> bytes:
    """A plain landing page for GitHub Pages. No assets, no external requests."""
    rows = []
    for ay in years:
        for t in ay.terms:
            if t.term not in ('fall', 'spring') or not t.classes_begin:
                continue
            rows.append(
                f'<tr><td>{t.id}</td><td>{t.classes_begin}</td><td>{t.classes_end}</td>'
                f'<td>{len(t.no_class_dates())}</td><td>{len(t.day_swaps())}</td>'
                f'<td><strong>{len(t.class_days())}</strong></td></tr>')
    feeds = ''.join(
        f'<li><code>{n}</code> — <a href="{n}">{n}</a></li>'
        for n in ['rwu-academic-calendar.ics', 'rwu-no-class-days.ics',
                  'rwu-academic-calendar.json', 'no-class-days.json']
        + [f'{ay.academic_year}.{ext}' for ay in years for ext in ('ics', 'json')])
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RWU Academic Calendar — unofficial feeds</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 60rem; margin: 2rem auto;
        padding: 0 1rem; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border: 1px solid #8888; padding: .35rem .6rem; text-align: left; }}
 code {{ background: #8881; padding: .1em .3em; border-radius: 3px; }}
 .warn {{ border-left: 4px solid #c33; padding: .75rem 1rem; background: #c331; }}
 td, th {{ white-space: nowrap; }}
 .wrap {{ overflow-x: auto; }}
</style></head><body>
<h1>RWU Academic Calendar — unofficial feeds</h1>
<p class="warn"><strong>Not an official Roger Williams University publication.</strong>
Derived by scraping the
<a href="{years[0].source_url if years else ''}">public academic calendar page</a>.
Not endorsed by the university. Verify against the official calendar before
relying on it.</p>
<h2>Feeds</h2><ul>{feeds}</ul>
<h2>Fall &amp; spring terms</h2>
<div class="wrap"><table>
<tr><th>Term</th><th>Classes begin</th><th>Classes end</th><th>No-class</th>
<th>Day swaps</th><th>Class days</th></tr>
{''.join(rows)}
</table></div>
<p><a href="https://github.com/arhyneRWU/rwu-academic-calendar">Source and
documentation on GitHub</a>. Last extracted: {years[0].retrieved if years else '—'}.</p>
</body></html>
"""
    return html.encode()


def build(years: list[AcademicYear], outdir: str | Path) -> list[Path]:
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
    w('index.html', to_index_html(years))
    w('.nojekyll', b'')     # Pages would otherwise skip nothing here, but be explicit
    return written
