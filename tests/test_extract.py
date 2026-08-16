import datetime as dt

import pytest

from rwu_calendar.extract import (ExtractionError, _parse_two_col, _resolve_year,
                                  _sole_term, extract)


def test_sole_term_ignores_a_heading_that_lists_every_term():
    """'Academic Calendar 2025-2026: Fall, Winter, Spring, and Summer Terms'
    names the section, not a table. Taking its first match would stamp every
    table in the section as fall."""
    assert _sole_term('Academic Calendar Winter 2027') == 'winter'
    assert _sole_term('Academic Calendar 2025-2026: Fall, Winter, Spring, and Summer Terms') is None
    assert _sole_term('Academic Calendar 2026-2027') is None


class TestResolveYear:
    """An academic year spans two calendar years. The month alone does not
    say which -- August belongs to the first year in fall and to the second
    in summer."""

    def test_fall_august_takes_the_first_year(self):
        assert _resolve_year(8, 2023, 2024, 'fall') == 2023

    def test_summer_august_takes_the_second_year(self):
        assert _resolve_year(8, 2023, 2024, 'summer') == 2024

    def test_spring_always_takes_the_second_year(self):
        assert _resolve_year(1, 2026, 2027, 'spring') == 2027

    def test_winter_splits_on_december(self):
        assert _resolve_year(12, 2026, 2027, 'winter') == 2026
        assert _resolve_year(1, 2026, 2027, 'winter') == 2027


class TestDateCell:
    def test_single_day(self):
        assert _parse_two_col('Aug. 25, Mon.') == [('one', 'AUG', 25)]

    def test_day_range(self):
        assert _parse_two_col('Nov. 26-28, Wed.-Fri.') == [('span', 'NOV', 26, 28)]

    def test_slash_is_two_discrete_days_not_a_range(self):
        assert _parse_two_col('Jan. 20/21, Mon./Tues.') == [('list', 'JAN', [20, 21])]

    def test_reversed_day_month_format(self):
        """The Winter tables write '22-Jan', which a month-first parser reads
        as a range of days 22..(nothing)."""
        assert _parse_two_col('22-Jan') == [('one', 'JAN', 22)]

    def test_cross_month_range(self):
        assert _parse_two_col('Dec. 30 - Jan. 2') == [('cross', ('DEC', 30), ('JAN', 2))]


def test_extract_rejects_a_page_it_does_not_recognise():
    with pytest.raises(ExtractionError):
        extract('<html><body><p>nothing here</p></body></html>')


PAGE = """
<h3>Academic Calendar 2026-2027</h3>
<table>
<tr><td>Important Fall Term Dates Fall 2026</td><td>Month</td><td>Date</td><td>Day</td></tr>
<tr><td>First Day of Classes</td><td>AUG</td><td>26</td><td>WED</td></tr>
<tr><td>Thanksgiving Break: No Classes - All University Offices Closed</td>
    <td>NOV</td><td>25-27</td><td>WED-FRI</td></tr>
<tr><td>Tuesday - Monday Classes Observed</td><td>OCT</td><td>13</td><td>TUE</td></tr>
<tr><td>Last Day of Fall Classes</td><td>DEC</td><td>2</td><td>WED</td></tr>
</table>
<h3>Academic Calendar Winter 2027</h3>
<table>
<tr><td>January 4, 2027 - January 22, 2027</td><td>DATE</td><td>DAY</td></tr>
<tr><td>First Day of Classes</td><td>4-Jan</td><td>Mon</td></tr>
</table>
"""


SUMMER_PAGE = """
<h3>Academic Calendar 2024-2025</h3>
<table>
<tr><td>Important Summer I term Dates 4 Week Session, May 21, 2025 - June 13, 2025</td>
    <td>Date</td><td>Day</td></tr>
<tr><td>First Day of Classes</td><td>May 21</td><td>Wed.</td></tr>
</table>
<table>
<tr><td>Important Summer I term Dates 5 Week Session, May 21, 2025 - June 20, 2025</td>
    <td>Date</td><td>Day</td></tr>
<tr><td>First Day of Classes</td><td>May 21</td><td>Wed.</td></tr>
</table>
<table>
<tr><td>Important Summer I term Dates 5 Week Session, May 21, 2025 - June 20, 2025</td>
    <td>Date</td><td>Day</td></tr>
<tr><td>First Day of Classes</td><td>May 21</td><td>Wed.</td></tr>
</table>
"""


class TestSummerSessions:
    """Summer is six overlapping sessions, not one term. They share dates and
    labels, so without the session they are indistinguishable -- which shows
    up as colliding ICS UIDs and duplicated events in every subscriber."""

    @pytest.fixture(scope='class')
    def summer(self):
        years = extract(SUMMER_PAGE, retrieved='2026-08-16')
        return next(t for t in years[0].terms if t.term == 'summer')

    def test_august_dates_resolve_to_the_second_calendar_year(self):
        assert _resolve_year(8, 2024, 2025, 'summer') == 2025

    def test_same_date_and_label_in_two_sessions_are_kept_apart(self, summer):
        firsts = [e for e in summer.events if e.label == 'First Day of Classes']
        assert len(firsts) == 2
        assert len({e.session for e in firsts}) == 2

    def test_a_table_repeated_verbatim_is_collapsed(self, summer):
        """RWU lists the Summer I 10-week session twice, as two identical
        tables. That is one event printed twice, not two events."""
        sessions = {e.session for e in summer.events}
        assert len(sessions) == 2, 'the duplicated 5-week table must collapse'


class TestExtractIntegration:
    @pytest.fixture(scope='class')
    def years(self):
        return extract(PAGE, retrieved='2026-08-16')

    def test_one_academic_year(self, years):
        assert len(years) == 1 and years[0].academic_year == '2026-2027'

    def test_winter_table_does_not_leak_into_fall(self, years):
        """The Winter table's header row names no term, so without heading
        anchoring its rows inherit whatever term came before."""
        ids = {t.id for t in years[0].terms}
        assert ids == {'fall-2026', 'winter-2027'}

    def test_multi_day_row_expands_to_one_event_per_day(self, years):
        fall = next(t for t in years[0].terms if t.term == 'fall')
        thanks = [e for e in fall.events if 'Thanksgiving' in e.label]
        assert [e.date for e in thanks] == [dt.date(2026, 11, d) for d in (25, 26, 27)]
        assert len({e.span_id for e in thanks}) == 1, 'expanded days share one span_id'

    def test_term_boundaries(self, years):
        fall = next(t for t in years[0].terms if t.term == 'fall')
        assert fall.classes_begin == dt.date(2026, 8, 26)
        assert fall.classes_end == dt.date(2026, 12, 2)

    def test_class_days_exclude_holidays_but_not_the_swap_day(self, years):
        fall = next(t for t in years[0].terms if t.term == 'fall')
        days = set(fall.class_days())
        assert dt.date(2026, 11, 25) not in days       # Thanksgiving
        assert dt.date(2026, 10, 13) in days           # swap day: classes DO meet

    def test_effective_weekday_folds_swaps_and_holidays(self, years):
        fall = next(t for t in years[0].terms if t.term == 'fall')
        assert fall.effective_weekday(dt.date(2026, 10, 13)) == 'monday'   # a Tuesday
        assert fall.effective_weekday(dt.date(2026, 11, 25)) is None       # holiday
        assert fall.effective_weekday(dt.date(2026, 9, 1)) == 'tuesday'    # ordinary
        assert fall.effective_weekday(dt.date(2026, 8, 29)) is None        # Saturday
