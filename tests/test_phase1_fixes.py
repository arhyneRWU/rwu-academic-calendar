"""Regressions for four live bugs found by adversarial design review.

Each of these was shipped and silently wrong. The tests are written against
the specific real-world data that exposed them, so a future extraction change
that reintroduces one fails loudly.
"""
import datetime as dt
from pathlib import Path

import pytest

from rwu_calendar import emit, serialize, validate
from rwu_calendar.model import AcademicYear, Event, Term, classify

DATA = Path(__file__).resolve().parents[1] / 'data'
TODAY = dt.date(2026, 8, 16)


@pytest.fixture(scope='module')
def years():
    return serialize.load_dir(DATA)


@pytest.fixture(scope='module')
def terms(years):
    return {t.id: t for ay in years for t in ay.terms}


class TestWinterTermWasSilentlyMissing:
    """RWU typed "Lat day of classes" instead of "Last". The term_end regex
    missed it, classes_end was None, meeting_grid skipped the term, and the
    whole January intersession vanished from the builder with no error."""

    def test_the_real_typo_still_classifies_as_a_term_end(self):
        assert 'term_end' in classify('Lat day of classes - All final Exams Held')[0]

    def test_the_correct_spelling_obviously_still_works(self):
        assert 'term_end' in classify('Last day of classes - All final Exams Held')[0]

    def test_last_day_to_drop_is_still_not_a_term_end(self):
        """The looser `las?t` must not start swallowing deadlines."""
        assert 'term_end' not in classify('Last Day to Drop a Course Without a "W"')[0]

    def test_winter_2027_has_both_boundaries(self, terms):
        w = terms['winter-2027']
        assert w.classes_begin == dt.date(2027, 1, 4)
        assert w.classes_end == dt.date(2027, 1, 22)

    def test_every_term_with_events_has_boundaries(self, years):
        missing = [t.id for ay in years for t in ay.terms
                   if t.events and not (t.classes_begin and t.classes_end)]
        assert missing == []

    def test_winter_now_appears_in_the_builder(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        assert 'winter-2027' in emit.meeting_grid(ay)


class TestValidatorCatchesAMissingBoundary:
    """Checking only fall and spring is what let winter slip through."""

    def _term_without_end(self):
        ay = AcademicYear('2026-2027', 'https://x', '2026-08-16')
        t = Term(id='winter-2027', term='winter', academic_year='2026-2027')
        t.events = [Event(date=dt.date(2027, 1, 4), label='First Day of Classes',
                          kinds=['term_start'])]
        ay.terms = [t]
        return ay

    def test_a_winter_term_with_no_end_is_now_an_error(self):
        problems = validate.check_structure([self._term_without_end()])
        assert any('no last day of classes' in p.message for p in validate.errors(problems))

    def test_the_real_data_has_no_structural_errors(self, years):
        assert validate.errors(validate.run_all(years)) == []


class TestSummerSessionsAreNotOneTerm:
    """classes_begin/end take min/max across all six overlapping sessions, so
    the summer 2026 "term" runs 20 May to 14 August. A student in the 4-week
    session would have been handed meetings nine weeks past its end."""

    @pytest.fixture(scope='class')
    @staticmethod
    def summer(years):
        return {t.id: t for ay in years for t in ay.terms}['summer-2026']

    def test_the_union_span_is_still_what_it_was(self, summer):
        assert summer.classes_begin == dt.date(2026, 5, 20)
        assert summer.classes_end == dt.date(2026, 8, 14)

    def test_six_sessions_are_separated(self, summer):
        assert len(summer.sessions()) == 6

    def test_each_session_ends_when_it_actually_ends(self, summer):
        ends = sorted(end for _b, end in summer.sessions().values())
        assert ends == [dt.date(2026, 6, 12), dt.date(2026, 6, 22), dt.date(2026, 7, 10),
                        dt.date(2026, 7, 24), dt.date(2026, 8, 7), dt.date(2026, 8, 14)]

    def test_the_grid_offers_one_entry_per_session(self, years):
        ay = next(a for a in years if a.academic_year == '2025-2026')
        grid = emit.meeting_grid(ay)
        summer = {k: v for k, v in grid.items() if k.startswith('summer-2026')}
        assert len(summer) == 6

    def test_a_four_week_session_stops_at_its_own_end_date(self, years):
        ay = next(a for a in years if a.academic_year == '2025-2026')
        grid = emit.meeting_grid(ay)
        four = next(v for k, v in grid.items()
                    if k.startswith('summer-2026') and '4-week' in k and 'may' in k)
        assert four['end'] == '2026-06-12'
        assert max(four['days']) <= '2026-06-12'

    def test_single_session_terms_keep_their_plain_id(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        assert set(emit.meeting_grid(ay)) == {'fall-2026', 'winter-2027', 'spring-2027'}


class TestOfficesClosedCoverage:
    """`offices_closed` looks like a usable rule input and mostly is not.
    Anything built on it has to handle the unknowns explicitly."""

    def test_singular_office_closed_is_no_longer_missed(self):
        _kinds, extra = classify('Juneteenth Holiday: No Classes - All University office Closed')
        assert extra['offices_closed'] is True

    def test_plural_still_works_both_ways(self):
        assert classify('Labor Day: No Classes - All University Offices Closed')[1]['offices_closed'] is True
        assert classify('Fall Break: No Classes - All University Offices Open')[1]['offices_closed'] is False

    def test_most_no_class_days_never_state_office_status(self, years):
        """Recorded as a number so a future change to the data is visible.
        Spring Break, Reading Day and SASH simply do not say."""
        nc = [e for ay in years for t in ay.terms for e in t.events if e.no_classes]
        unknown = [e for e in nc if e.offices_closed is None]
        assert len(nc) == 92
        assert len(unknown) == 33

    def test_the_gap_is_reported_rather_than_hidden(self, years):
        problems = validate.check_offices_coverage(years)
        assert problems
        assert all(p.level == 'source' for p in problems)


class TestRecurringSeriesContract:
    """What the browser must produce. RRULE expands on the weekday a date FALLS
    ON; the grid knows the weekday it RUNS AS. Every disagreement is a holiday
    or a day swap, so EXDATE/RDATE are set differences and cannot drift."""

    @pytest.fixture(scope='class')
    @staticmethod
    def fall(years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        return emit.meeting_grid(ay)['fall-2026']

    @staticmethod
    def _sets(fall, days):
        code = {'monday': 'M', 'tuesday': 'T', 'wednesday': 'W',
                'thursday': 'R', 'friday': 'F'}
        want = {code[d] for d in days}
        meetings = sorted(d for d, c in fall['days'].items() if c[0] in want)
        first, last = meetings[0], meetings[-1]
        by_rule, d = [], dt.date.fromisoformat(first)
        names = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday',
                 'saturday', 'sunday')
        while d.isoformat() <= last:
            if names[d.weekday()] in days:
                by_rule.append(d.isoformat())
            d += dt.timedelta(days=1)
        return (meetings,
                sorted(set(by_rule) - set(meetings)),
                sorted(set(meetings) - set(by_rule)))

    def test_tuesday_thursday_excludes_the_swap_and_thanksgiving(self, fall):
        meetings, exdate, rdate = self._sets(fall, {'tuesday', 'thursday'})
        assert len(meetings) == 26
        assert exdate == ['2026-10-13', '2026-11-26']
        assert rdate == []

    def test_monday_wednesday_gains_the_swap_day_via_rdate(self, fall):
        meetings, exdate, rdate = self._sets(fall, {'monday', 'wednesday'})
        assert rdate == ['2026-10-13'], 'a Tuesday running a Monday schedule'
        assert exdate == ['2026-09-07', '2026-10-12', '2026-11-11', '2026-11-25']
        assert len(meetings) == 26

    def test_the_swap_day_is_never_in_both_sets(self, fall):
        _m, ex_tt, rd_tt = self._sets(fall, {'tuesday', 'thursday'})
        _m2, ex_mw, rd_mw = self._sets(fall, {'monday', 'wednesday'})
        assert '2026-10-13' in ex_tt and '2026-10-13' in rd_mw
        assert '2026-10-13' not in rd_tt and '2026-10-13' not in ex_mw


class TestGeneratedPageIsSyntacticallySane:
    @pytest.fixture(scope='class')
    @staticmethod
    def page(years):
        return emit.to_index_html(years, TODAY).decode()

    def test_no_raw_carriage_returns(self, page):
        r"""Regression: a rewrite put literal CR/LF bytes inside a JavaScript
        string literal (`out.join('<CR><LF>')`), which is a syntax error that
        silently broke the whole builder. Substring tests all still passed."""
        assert '\r' not in page

    def test_the_ics_line_ending_is_an_escape_not_a_real_newline(self, page):
        assert r"out.map(fold).join('\r\n')" in page

    def test_emits_a_recurring_series(self, page):
        for needle in ("'RRULE:FREQ=WEEKLY'", 'EXDATE:', 'UNTIL='):
            assert needle in page, needle

    def test_it_does_not_use_rdate(self, page):
        """RDATE is legal and expresses the day swap exactly, but Outlook's
        recurrence model cannot represent "and also this one date" -- and
        rather than keep the pattern and drop the extra, it abandons the
        pattern and imports every meeting as a separate appointment. The
        gained date is its own event instead."""
        assert 'RDATE:' not in page

    def test_uid_is_content_derived_not_row_index(self, page):
        """The old scheme keyed on array position, so deleting or reordering a
        row changed every later UID and re-importing appended duplicates."""
        assert 'uid(termId' in page
        assert '${termId}-${ci}-' not in page
