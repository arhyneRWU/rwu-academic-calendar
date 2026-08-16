"""The data model, and the rules that turn RWU's prose labels into typed fields.

The whole point of this repo is that a scheduler cannot act on
``"Fall Break: No Classes - All University Offices Open"``. It needs
``no_classes: true``. Everything interesting therefore happens in
:func:`classify` — the rest is plumbing.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

TERMS = ('fall', 'winter', 'spring', 'summer')

#: Every ``kind`` an event may carry. Validated, so a typo in a rule below
#: fails the build rather than silently producing an uncategorised event.
KINDS = (
    'term_start', 'term_end', 'no_classes', 'holiday', 'break', 'day_swap',
    'reading_day', 'finals', 'commencement', 'add_drop', 'registration',
    'advisement', 'grades', 'orientation', 'residence_life', 'other',
)

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday',
            'saturday', 'sunday')
_WD_INDEX = {w: i for i, w in enumerate(WEEKDAYS)}


@dataclass
class Event:
    date: _dt.date
    label: str                      # verbatim from the source page
    kinds: list[str] = field(default_factory=list)
    no_classes: bool = False
    offices_closed: Optional[bool] = None
    observes_schedule_of: Optional[str] = None   # a weekday name, for day swaps
    span_id: Optional[str] = None   # groups days expanded from one source row
    source_text: str = ''           # the raw date cell, e.g. "Nov. 26-28, Wed.-Fri."
    stated_day: str = ''            # weekday as printed, for cross-checking
    #: Summer is not one term but six overlapping sessions ("4 Week Session,
    #: May 20 - June 12"), which share dates *and* labels. Without this,
    #: (date, label) is not unique and ICS UIDs collide.
    session: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d['date'] = self.date.isoformat()
        return {k: v for k, v in d.items() if v not in (None, '', [], False)} | {
            'date': d['date'], 'label': self.label, 'kinds': self.kinds,
            'no_classes': self.no_classes,
        }


@dataclass
class Term:
    id: str
    term: str
    academic_year: str
    events: list[Event] = field(default_factory=list)

    @property
    def classes_begin(self) -> Optional[_dt.date]:
        return min((e.date for e in self.events if 'term_start' in e.kinds), default=None)

    @property
    def classes_end(self) -> Optional[_dt.date]:
        return max((e.date for e in self.events if 'term_end' in e.kinds), default=None)

    def no_class_dates(self) -> list[_dt.date]:
        return sorted({e.date for e in self.events if e.no_classes})

    def class_days(self) -> list[_dt.date]:
        """Weekdays between the first and last day of classes, minus no-class days.

        Reading Day and finals sit *after* the last day of classes, so they
        fall outside this span by construction rather than by exclusion.
        """
        a, b = self.classes_begin, self.classes_end
        if not a or not b:
            return []
        skip = set(self.no_class_dates())
        out, d = [], a
        while d <= b:
            if d.weekday() < 5 and d not in skip:
                out.append(d)
            d += _dt.timedelta(days=1)
        return out

    def day_swaps(self) -> list[Event]:
        return [e for e in self.events if 'day_swap' in e.kinds]

    def effective_weekday(self, d: _dt.date) -> Optional[str]:
        """Which weekday's timetable ``d`` actually runs.

        ``None`` when no class meets. This is the method a scheduler wants:
        it folds holidays and day swaps into one answer.
        """
        for e in self.events:
            if e.date == d and e.observes_schedule_of:
                return e.observes_schedule_of
        if d in set(self.no_class_dates()):
            return None
        a, b = self.classes_begin, self.classes_end
        if a and b and a <= d <= b and d.weekday() < 5:
            return WEEKDAYS[d.weekday()]
        return None


@dataclass
class AcademicYear:
    academic_year: str
    source_url: str
    retrieved: str
    terms: list[Term] = field(default_factory=list)


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

# A day swap is written eight different ways across four years. Each rule
# captures which timetable is *observed*, not which one is cancelled --
# "Monday Classes Meet, Tuesday Courses do not Meet" and "Tuesday - Monday
# Classes Observed" mean the same thing and must not classify differently.
_SWAP_RULES = (
    (re.compile(r'(\w+day)\s+(?:classes|schedule)\s+(?:meet|observed)', re.I), 1),
    (re.compile(r'(\w+day)\s+schedule', re.I), 1),
    (re.compile(r'\w+day\s*-\s*(\w+day)\s+classes\s+observed', re.I), 1),
)

_NO_CLASS = re.compile(
    r'no\s+class'          # "No Classes - ...", "*No classes held"
    r'|\bbreak\b'          # Spring Break / Fall Break / Thanksgiving Break
    r'|\bholiday\b'        # University Holiday, MLK Holiday
    r'|reading\s+day',
    re.I,
)


def classify(label: str) -> tuple[list[str], dict]:
    """Map a source label to ``(kinds, extra_fields)``."""
    low = label.lower()
    kinds: list[str] = []
    extra: dict = {}

    # -- day swap ---------------------------------------------------------
    # Checked first and treated as exclusive: a swap day HAS classes, so it
    # must never also be tagged no_classes even though its label often
    # contains "do not Meet" about the displaced day.
    observed = None
    for rx, grp in _SWAP_RULES:
        m = rx.search(label)
        if m and m.group(grp).lower() in _WD_INDEX:
            observed = m.group(grp).lower()
            break
    if observed:
        kinds.append('day_swap')
        extra['observes_schedule_of'] = observed
        extra['no_classes'] = False
        return kinds, extra

    # -- no-class days ----------------------------------------------------
    if _NO_CLASS.search(low):
        kinds.append('no_classes')
        extra['no_classes'] = True
        if 'holiday' in low or re.search(r'day\b.*no class', low):
            kinds.append('holiday')
        if 'break' in low:
            kinds.append('break')
        if 'reading day' in low:
            kinds.append('reading_day')
        if 'offices closed' in low:
            extra['offices_closed'] = True
        elif 'offices open' in low:
            extra['offices_closed'] = False

    # -- term boundaries --------------------------------------------------
    if re.search(r'first day of class', low):
        kinds.append('term_start')
    # "Last Day of Fall 2023 Classes" -- the year sits inside the phrase
    if re.search(r'last day of\s+(?:fall|spring|winter|summer)?\s*\d{0,4}\s*class', low):
        kinds.append('term_end')

    # -- everything else --------------------------------------------------
    if re.search(r'final exam', low):
        kinds.append('finals')
    if re.search(r'commencement', low):
        kinds.append('commencement')
    if re.search(r'last day to (add|drop)', low):
        kinds.append('add_drop')
    if re.search(r'registration', low):
        kinds.append('registration')
    if re.search(r'advisement', low):
        kinds.append('advisement')
    if re.search(r'grades? (due|convert)|grades due', low):
        kinds.append('grades')
    if re.search(r'orientation|convocation|move-in', low):
        kinds.append('orientation')
    if re.search(r'residence hall', low):
        kinds.append('residence_life')

    if not kinds:
        kinds.append('other')
    return kinds, extra
