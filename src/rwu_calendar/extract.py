"""Scrape rwu.edu's academic calendar page into :mod:`model` objects.

The source page has used **three incompatible date layouts** in four years:

===========  ==============================================================
2026-2027    four columns -- ``Event | Month | Date | Day``
2023..2026   two columns  -- ``Event | "Aug. 21-22, Thurs.-Fri."``
Winter       two columns  -- ``Event | "22-Jan"``  (day first)
===========  ==============================================================

That churn is the reason the extractor's output is committed as data rather
than fetched at read time: the page has already changed shape twice, and it
will again.
"""
from __future__ import annotations

import datetime as _dt
import html
import re
import urllib.request

from .model import AcademicYear, Event, Term, classify, link

SOURCE_URL = 'https://www.rwu.edu/academics/resources-units/academic-calendar'

MONTHS = {
    'JAN': 1, 'JANUARY': 1, 'FEB': 2, 'FEBRUARY': 2, 'MAR': 3, 'MARCH': 3,
    'APR': 4, 'APRIL': 4, 'MAY': 5, 'JUN': 6, 'JUNE': 6, 'JUL': 7, 'JULY': 7,
    'AUG': 8, 'AUGUST': 8, 'SEP': 9, 'SEPT': 9, 'SEPTEMBER': 9,
    'OCT': 10, 'OCTOBER': 10, 'NOV': 11, 'NOVEMBER': 11, 'DEC': 12, 'DECEMBER': 12,
}
TERMS = ('fall', 'winter', 'spring', 'summer')


class ExtractionError(RuntimeError):
    pass


def fetch(url: str = SOURCE_URL, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'rwu-academic-calendar/1.0 (+github.com/arhyneRWU)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def _txt(s: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()


def _mkey(s: str) -> str:
    return re.sub(r'[^A-Z]', '', s.upper())


def _sole_term(heading: str) -> str | None:
    """The term a heading names, or ``None`` if it names zero or several.

    ``"Academic Calendar 2025-2026: Fall, Winter, Spring, and Summer Terms"``
    names the section, not a table, so it must not set a term.
    """
    found = [t for t in TERMS if t in heading.lower()]
    return found[0] if len(found) == 1 else None


def _resolve_year(month: int, y1: int, y2: int, term: str | None) -> int:
    """An academic year spans two calendar years; which one a month lands in
    depends on the *term*, not the month alone. Summer 2024 belongs to
    AY2023-2024 but its August dates are 2024, not 2023."""
    if term in ('spring', 'summer'):
        return y2
    if term == 'winter':
        return y1 if month == 12 else y2
    return y1 if month >= 8 else y2


def _parse_two_col(cell: str) -> list[tuple[str, int]] | list[tuple[str, int, int]]:
    """Parse formats B and C. Returns tagged tuples for the caller to expand."""
    head = cell.split(',')[0] if ',' in cell else cell

    # format C -- "22-Jan"
    m = re.fullmatch(r'\s*(\d{1,2})\s*-\s*([A-Za-z]+)\.?\s*', head)
    if m and _mkey(m.group(2)) in MONTHS:
        return [('one', _mkey(m.group(2)), int(m.group(1)))]

    toks = [(_mkey(a), int(b)) for a, b in re.findall(r'([A-Za-z]+)\.?\s*(\d+)', head)
            if _mkey(a) in MONTHS]
    if not toks:
        return []
    # "Dec. 30 - Jan. 2" -- a range crossing a month boundary
    if len(toks) >= 2 and re.search(r'[-–]', head):
        return [('cross', toks[0], toks[-1])]
    # "Aug. 21-22"
    if re.search(r'\d+\s*[-–]\s*\d+', head):
        a, b = re.findall(r'(\d+)\s*[-–]\s*(\d+)', head)[0]
        return [('span', toks[0][0], int(a), int(b))]
    # "Jan. 20/21" -- two discrete days, not a range
    if re.search(r'\d+\s*/\s*\d+', head):
        return [('list', toks[0][0], [int(n) for n in re.findall(r'\d+', head)])]
    return [('one', toks[0][0], toks[0][1])]


def extract(page_html: str, retrieved: str | None = None,
            source_url: str = SOURCE_URL) -> list[AcademicYear]:
    retrieved = retrieved or _dt.date.today().isoformat()
    heads = [(m.start(), _txt(m.group(2)))
             for m in re.finditer(r'<(h[234])[^>]*>(.*?)</\1>', page_html, re.S | re.I)]

    sections = []
    for i, (pos, t) in enumerate(heads):
        m = re.match(r'Academic Calendar (\d{4})-(\d{4})', t)
        if not m:
            continue
        end = len(page_html)
        for pos2, t2 in heads[i + 1:]:
            if (re.match(r'Academic Calendar \d{4}-\d{4}', t2)
                    or t2.startswith('Past RWU') or t2.startswith('Request Info')):
                end = pos2
                break
        sections.append((int(m.group(1)), int(m.group(2)), pos, end))
    if not sections:
        raise ExtractionError('no "Academic Calendar YYYY-YYYY" headings found — page layout changed')

    years: list[AcademicYear] = []
    for y1, y2, a, b in sections:
        ay = AcademicYear(f'{y1}-{y2}', source_url, retrieved)
        terms: dict[str, Term] = {}
        seg = page_html[a:b]
        local_heads = [(p - a, t) for p, t in heads if a <= p < b]

        for tm in re.finditer(r'<table[^>]*>(.*?)</table>', seg, re.S | re.I):
            # A table's term comes from the nearest heading above it that names
            # exactly one. The Winter table's own header row names no term, so
            # row-level detection alone leaks it into Spring.
            term, session = None, None
            above = list(reversed([h for h in local_heads if h[0] < tm.start()]))
            # Summer's six sessions each get their own table under an h4 like
            # "4 Week Session, May 20, 2026 - June 12, 2026". They share dates
            # and labels, so the session is what makes an event identifiable.
            for hp, ht in above:
                if re.search(r'\bsession\b', ht, re.I):
                    session = ht
                    break
            for hp, ht in above:
                if _sole_term(ht):
                    term = _sole_term(ht)
                    break
            seq = 0
            for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tm.group(1), re.S | re.I):
                cells = [c for c in (_txt(x) for x in
                         re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S | re.I)) if c]
                if not cells:
                    continue
                label = cells[0]

                if (re.match(r'important', label, re.I)
                        or (len(cells) > 1 and cells[1].lower() in ('month', 'date/day', 'date'))):
                    term = (_sole_term(label)
                            or (_sole_term(cells[1]) if len(cells) > 1 else None)
                            or term)
                    # In the older years the session is named in the table's own
                    # header row rather than an h4 above it, e.g. "Important
                    # Summer I term Dates 4 Week Session, May 21 - June 13".
                    if re.search(r'\bsession\b', label, re.I):
                        session = label
                    continue
                if len(cells) == 1:
                    if len(label) < 60 and _sole_term(label):
                        term = _sole_term(label)
                    continue

                pieces: list[tuple[int, int]] = []
                if len(cells) >= 4 and _mkey(cells[1]) in MONTHS:      # format A
                    month = MONTHS[_mkey(cells[1])]
                    datefield, stated = cells[2], cells[3]
                    nums = [int(n) for n in re.findall(r'\d+', datefield)]
                    if not nums:
                        continue
                    days = (list(range(nums[0], nums[1] + 1))
                            if re.search(r'\d\s*[-–]\s*\d', datefield) and len(nums) == 2
                            else nums)
                    pieces = [(month, d) for d in days]
                    raw = f'{cells[1]} {datefield}'
                else:                                                   # formats B / C
                    datefield = cells[1]
                    stated = datefield.split(',', 1)[1].strip() if ',' in datefield else ''
                    raw = datefield
                    for p in _parse_two_col(datefield):
                        if p[0] == 'one':
                            pieces.append((MONTHS[p[1]], p[2]))
                        elif p[0] == 'span':
                            pieces += [(MONTHS[p[1]], d) for d in range(p[2], p[3] + 1)]
                        elif p[0] == 'list':
                            pieces += [(MONTHS[p[1]], d) for d in p[2]]
                        elif p[0] == 'cross':
                            (m1, d1), (m2, d2) = p[1], p[2]
                            n1, n2 = MONTHS[m1], MONTHS[m2]
                            cur = _dt.date(_resolve_year(n1, y1, y2, term), n1, d1)
                            stop = _dt.date(_resolve_year(n2, y1, y2, term), n2, d2)
                            while cur <= stop and (stop - cur).days < 60:
                                pieces.append((cur.month, cur.day))
                                cur += _dt.timedelta(days=1)
                    if not pieces:
                        if re.search(r'\d', datefield):
                            raise ExtractionError(
                                f'unparsed date {datefield!r} for {label!r} in {y1}-{y2}')
                        continue

                seq += 1
                span = f'{y1}{y2}-{term}-{seq}' if len(pieces) > 1 else None
                kinds, extra = classify(label)
                for month, day in pieces:
                    try:
                        d = _dt.date(_resolve_year(month, y1, y2, term), month, day)
                    except ValueError:
                        continue
                    key = term or 'unknown'
                    if key not in terms:
                        # Fall 2026 belongs to AY2026-2027; spring/winter/summer
                        # take the second year. Derived from the term, never from
                        # whichever event happened to be seen first.
                        label_year = y1 if key == 'fall' else y2
                        terms[key] = Term(id=f'{key}-{label_year}', term=key,
                                          academic_year=ay.academic_year)
                    terms[key].events.append(Event(
                        date=d, label=label, kinds=list(kinds),
                        no_classes=extra.get('no_classes', False),
                        offices_closed=extra.get('offices_closed'),
                        observes_schedule_of=extra.get('observes_schedule_of'),
                        span_id=span, source_text=raw, stated_day=stated,
                        session=session,
                    ))

        for t in terms.values():
            # RWU lists the Summer I 10-week session twice, as two identical
            # tables. Identical on (session, date, label) means genuinely the
            # same event printed twice, not two events that coincide.
            seen, unique = set(), []
            for e in t.events:
                key = (e.session, e.date, e.label)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(e)
            t.events = sorted(unique, key=lambda e: (e.date, e.label))
        ay.terms = [terms[k] for k in TERMS if k in terms] + \
                   [v for k, v in terms.items() if k not in TERMS]
        years.append(link(ay))
    return years
