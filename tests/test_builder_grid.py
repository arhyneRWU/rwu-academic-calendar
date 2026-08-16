"""The meeting grid behind the in-browser schedule builder.

The browser does one comparison — "is this date's effective weekday one I
teach?" — so every judgement that could be wrong is made here, in Python,
where it can be tested. These are the tests that decide whether someone's
generated schedule is right.
"""
import datetime as dt
import json
import re
from pathlib import Path

import pytest

from rwu_calendar import emit, serialize

DATA = Path(__file__).resolve().parents[1] / 'data'
TODAY = dt.date(2026, 8, 16)


@pytest.fixture(scope='module')
def years():
    return serialize.load_dir(DATA)


@pytest.fixture(scope='module')
def current(years):
    return emit.pick_current(years, TODAY)


@pytest.fixture(scope='module')
def grid(current):
    return emit.meeting_grid(current)


def meets(grid, term, days):
    return sorted(d for d, eff in grid[term]['days'].items() if eff in days)


class TestGridShape:
    def test_covers_the_teaching_terms(self, grid):
        assert {'fall-2026', 'spring-2027'} <= set(grid)

    def test_each_entry_maps_iso_date_to_lowercase_weekday(self, grid):
        for t in grid.values():
            for d, eff in t['days'].items():
                assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', d)
                assert eff in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')

    def test_holidays_are_absent_entirely(self, grid):
        """A date with no classes has no entry, so no course can land on it."""
        assert '2026-11-25' not in grid['fall-2026']['days']    # Thanksgiving
        assert '2026-09-07' not in grid['fall-2026']['days']    # Labor Day
        assert '2027-03-15' not in grid['spring-2027']['days']  # Spring Break

    def test_weekends_are_absent(self, grid):
        for t in grid.values():
            for d in t['days']:
                assert dt.date.fromisoformat(d).weekday() < 5

    def test_nothing_falls_outside_the_term(self, grid):
        for t in grid.values():
            for d in t['days']:
                assert t['begin'] <= d <= t['end']


class TestDaySwaps:
    """The reason this grid exists rather than a weekday calculation."""

    def test_swap_date_is_labelled_with_the_timetable_it_runs(self, grid):
        assert grid['fall-2026']['days']['2026-10-13'] == 'monday'
        assert grid['spring-2027']['days']['2027-02-16'] == 'monday'

    def test_a_tuesday_thursday_course_skips_the_swap_day(self, grid):
        """Andrew's case: T/Th 11:00-12:20 in Fall 2026."""
        m = meets(grid, 'fall-2026', {'tuesday', 'thursday'})
        assert '2026-10-13' not in m, 'that Tuesday runs a Monday schedule'
        assert '2026-11-26' not in m, 'Thanksgiving'
        assert len(m) == 26

    def test_a_naive_weekday_count_would_be_wrong(self, grid):
        """Two more than reality — the exact error this prevents."""
        t = grid['fall-2026']
        a, b = dt.date.fromisoformat(t['begin']), dt.date.fromisoformat(t['end'])
        naive = sum(1 for i in range((b - a).days + 1)
                    if (a + dt.timedelta(i)).weekday() in (1, 3))
        assert naive == 28
        assert len(meets(grid, 'fall-2026', {'tuesday', 'thursday'})) == 26

    def test_a_monday_wednesday_course_gains_the_swap_day(self, grid):
        """Cuts both ways: a date that is not a Monday or Wednesday at all."""
        m = meets(grid, 'spring-2027', {'monday', 'wednesday'})
        assert '2027-02-16' in m
        assert dt.date.fromisoformat('2027-02-16').weekday() == 1, 'it is a Tuesday'

    def test_swaps_are_listed_so_the_preview_can_explain_them(self, grid):
        assert grid['fall-2026']['swaps'] == {'2026-10-13': 'monday'}


class TestAgainstTheModel:
    """The grid must agree with Term.effective_weekday, which the JSON feeds
    and the published class_days counts also rely on."""

    def test_grid_matches_effective_weekday_for_every_date(self, current, grid):
        for t in current.terms:
            if t.id not in grid:
                continue
            d = t.classes_begin
            while d <= t.classes_end:
                expected = t.effective_weekday(d)
                assert grid[t.id]['days'].get(d.isoformat()) == expected, d
                d += dt.timedelta(days=1)

    def test_grid_dates_equal_published_class_days(self, current, grid):
        for t in current.terms:
            if t.id in grid:
                assert set(grid[t.id]['days']) == {d.isoformat() for d in t.class_days()}


class TestEmbedding:
    @pytest.fixture(scope='class')
    def page(self, years):
        return emit.to_index_html(years, TODAY).decode()

    def test_grid_is_embedded_as_valid_json(self, page, grid):
        raw = page.split('id="grid">')[1].split('</script>')[0]
        assert json.loads(raw) == grid

    def test_no_closing_script_tag_can_break_out_of_the_json(self, page):
        """The grid is machine-generated dates, but assert it anyway -- a
        stray </script> inside embedded JSON ends the block early."""
        raw = page.split('id="grid">')[1].split('</script>')[0]
        assert '</' not in raw

    def test_builder_form_is_present(self, page):
        for needle in ('id="sched"', 'id="courses"', 'id="add"', 'id="term"',
                       'Build your own class schedule'):
            assert needle in page

    def test_builder_offers_every_teaching_term(self, page, grid):
        for tid in grid:
            assert tid in page

    def test_states_it_is_a_download_not_a_subscription(self, page):
        assert 'not a\nsubscription' in page or 'not a subscription' in page
