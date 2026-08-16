"""Checks that run in CI over ``data/``.

The most valuable one is :func:`check_weekdays`: RWU prints the weekday next
to each date, which is a free checksum. Comparing it against the real weekday
of that date catches both our transcription errors and theirs. As of the
2026-08-16 extraction it finds seven genuine errors on RWU's own page, so it
reports rather than raises -- a source typo must not break the build.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from .model import KINDS, TERMS, AcademicYear, WEEKDAYS

_DAY_ALIASES = {
    'MON': 0, 'MONDAY': 0, 'TUE': 1, 'TUES': 1, 'TUESDAY': 1,
    'WED': 2, 'WEDS': 2, 'WEDNESDAY': 2, 'THU': 3, 'THUR': 3, 'THURS': 3,
    'THURSDAY': 3, 'FRI': 4, 'FRIDAY': 4, 'SAT': 5, 'SATURDAY': 5,
    'SUN': 6, 'SUNDAY': 6,
}


@dataclass
class Problem:
    level: str      # 'error' (ours) or 'source' (RWU's)
    where: str
    message: str

    def __str__(self) -> str:
        return f'[{self.level}] {self.where}: {self.message}'


def _norm_day(s: str) -> int | None:
    import re
    key = re.sub(r'[^A-Z]', '', s.upper())
    return _DAY_ALIASES.get(key)


def check_weekdays(years: list[AcademicYear]) -> list[Problem]:
    out = []
    for ay in years:
        for t in ay.terms:
            for e in t.events:
                if e.span_id or not e.stated_day:
                    continue    # multi-day rows print a day *range*, not a day
                want = _norm_day(e.stated_day)
                if want is None or want == e.date.weekday():
                    continue
                out.append(Problem(
                    'source', f'{ay.academic_year}/{t.id}',
                    f'{e.date} is a {WEEKDAYS[e.date.weekday()].title()} but the page '
                    f'prints "{e.stated_day}" — {e.label!r}'))
    return out


def check_structure(years: list[AcademicYear]) -> list[Problem]:
    out = []
    for ay in years:
        if not ay.terms:
            out.append(Problem('error', ay.academic_year, 'no terms extracted'))
        for t in ay.terms:
            where = f'{ay.academic_year}/{t.id}'
            if t.term not in TERMS:
                out.append(Problem('error', where, f'unknown term {t.term!r}'))
            if not t.events:
                out.append(Problem('error', where, 'no events'))
            for e in t.events:
                for k in e.kinds:
                    if k not in KINDS:
                        out.append(Problem('error', where, f'unknown kind {k!r} on {e.date}'))
                if e.observes_schedule_of and e.observes_schedule_of not in WEEKDAYS:
                    out.append(Problem('error', where,
                                       f'bad observes_schedule_of {e.observes_schedule_of!r}'))
                # A swap day HAS classes. If both flags are set, classify() is wrong.
                if e.observes_schedule_of and e.no_classes:
                    out.append(Problem('error', where,
                                       f'{e.date} is both a day swap and a no-class day'))
            # Every term with events needs both boundaries, not just fall and
            # spring. Winter 2027 sat in the data for weeks with classes_end
            # None -- RWU typed "Lat day of classes" -- which silently dropped
            # the entire term out of the schedule builder with no error
            # anywhere. Checking only fall/spring is what let that through.
            if t.events:
                if not t.classes_begin:
                    out.append(Problem('error', where, 'no first day of classes found'))
                if not t.classes_end:
                    out.append(Problem('error', where, 'no last day of classes found'))
                if t.classes_begin and t.classes_end and t.classes_begin >= t.classes_end:
                    out.append(Problem('error', where, 'classes end on or before they begin'))
    return out


def check_coverage(years: list[AcademicYear]) -> list[Problem]:
    """Fall and spring have had the same no-class days every year. A term that
    suddenly lacks one is far more likely to be a parser regression than a
    change of policy, so say so."""
    out = []
    expected = {
        'fall': ['labor day', 'thanksgiving', 'reading day'],
        'spring': ['spring break', 'reading day'],
    }
    for ay in years:
        for t in ay.terms:
            for needle in expected.get(t.term, []):
                if not any(needle in e.label.lower() for e in t.events):
                    out.append(Problem('error', f'{ay.academic_year}/{t.id}',
                                       f'expected an event matching {needle!r}, found none'))
    return out


def check_offices_coverage(years: list[AcademicYear]) -> list[Problem]:
    """Report how many no-class days never state whether offices are open.

    Reported, not fatal: RWU simply does not say for Spring Break, Reading Day
    or SASH. It matters because `offices_closed` looks like a usable rule input
    -- "a staff meeting happens on Fall Break" -- and is only trustworthy where
    the page actually said so. Anything built on it must handle the unknowns
    explicitly rather than treating absent as open.
    """
    out = []
    for ay in years:
        for t in ay.terms:
            nc = [e for e in t.events if e.no_classes]
            unknown = [e for e in nc if e.offices_closed is None]
            if unknown:
                out.append(Problem(
                    'source', f'{ay.academic_year}/{t.id}',
                    f'{len(unknown)} of {len(nc)} no-class days do not state office '
                    f'status (e.g. {unknown[0].date} {unknown[0].label[:40]!r})'))
    return out


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    d = _dt.date(year, month, 1)
    d += _dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + _dt.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> _dt.date:
    d = _dt.date(year, month, 28) + _dt.timedelta(days=4)
    d = d.replace(day=1) - _dt.timedelta(days=1)          # last day of month
    return d - _dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: _dt.date) -> _dt.date:
    """A fixed-date holiday on a weekend is observed on the adjacent weekday."""
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def federal_holidays(year: int) -> dict[_dt.date, str]:
    """The ones RWU closes for, as dates rather than as prose."""
    return {
        _nth_weekday(year, 1, 0, 3): 'Martin Luther King Jr. Day',
        _last_weekday(year, 5, 0): 'Memorial Day',
        _observed(_dt.date(year, 6, 19)): 'Juneteenth',
        _observed(_dt.date(year, 7, 4)): 'Independence Day',
        _nth_weekday(year, 9, 0, 1): 'Labor Day',
        _nth_weekday(year, 11, 3, 4): 'Thanksgiving',
    }


def check_federal_holidays(years: list[AcademicYear]) -> list[Problem]:
    """Report teaching weekdays that are federal holidays but not marked.

    ``check_coverage`` only ever looked at fall and spring, matching on label
    text. That is why two real gaps sat in the data unnoticed: MLK Day inside
    the Winter intersession (printed under Spring, so winter never saw it), and
    no Independence Day at all in Summer 2026. Dates are checkable; prose is
    not, so this asks the calendar arithmetic instead of RWU's wording.

    Reported at ``source`` level, never fatal. RWU genuinely may hold classes,
    and a wrong red build teaches people to ignore the build.
    """
    out = []
    for ay in years:
        for t in ay.terms:
            a, b = t.classes_begin, t.classes_end
            if not (a and b):
                continue
            off = set(t.no_class_dates())
            for y in range(a.year, b.year + 1):
                for d, name in sorted(federal_holidays(y).items()):
                    if a <= d <= b and d.weekday() < 5 and d not in off:
                        out.append(Problem(
                            'source', f'{ay.academic_year}/{t.id}',
                            f'{d} is {name} and falls on a {WEEKDAYS[d.weekday()].title()} '
                            f'inside this term, but is not marked as a no-class day'))
    return out


def check_cross_term(years: list[AcademicYear]) -> list[Problem]:
    """Report no-class days a term had to borrow from a sibling.

    RWU prints one table per term, but January belongs to two of them: the MLK
    holiday is printed under Spring, where it falls before classes begin, while
    the date itself lands inside the Winter intersession. Winter therefore held
    no record of it and the builder scheduled a Monday class on the holiday.
    ``Term.inherited_no_class_events`` fixes the answer; this makes the
    borrowing visible, because a *new* one appearing is worth a human look.
    """
    out = []
    for ay in years:
        for t in ay.terms:
            for e in t.inherited_no_class_events():
                out.append(Problem(
                    'source', f'{ay.academic_year}/{t.id}',
                    f'{e.date} {e.label[:50]!r} is printed under another term but '
                    f'falls inside this one; treating it as a no-class day here'))
    return out


def run_all(years: list[AcademicYear]) -> list[Problem]:
    return (check_structure(years) + check_coverage(years)
            + check_weekdays(years) + check_offices_coverage(years)
            + check_cross_term(years) + check_federal_holidays(years))


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == 'error']
