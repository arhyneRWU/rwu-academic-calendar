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


CODE = {'monday': 'M', 'tuesday': 'T', 'wednesday': 'W',
        'thursday': 'R', 'friday': 'F'}


def meets(grid, term, days):
    """Dates whose *effective* weekday is one of `days`.

    Each grid value is three characters: the weekday the date RUNS AS ('-' if
    no class), whether classes meet, and RWU's stated office status.
    """
    want = {CODE[d] for d in days}
    return sorted(d for d, c in grid[term]['days'].items() if c[0] in want)


def runs_as(grid, term, date):
    c = grid[term]['days'].get(date)
    inv = {v: k for k, v in CODE.items()}
    return inv.get(c[0]) if c else None


class TestGridShape:
    def test_covers_the_teaching_terms(self, grid):
        assert {'fall-2026', 'spring-2027'} <= set(grid)

    def test_each_entry_is_a_three_character_code(self, grid):
        for t in grid.values():
            for d, c in t['days'].items():
                assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', d)
                assert re.fullmatch(r'[MTWRF-][N.][CO.]', c), (d, c)

    def test_holidays_are_present_but_marked_as_no_class(self, grid):
        """They must be in the grid now -- a meeting that does NOT follow the
        academic calendar still needs to know the date exists -- but flagged so
        anything class-shaped skips them."""
        for term, date in [('fall-2026', '2026-11-25'), ('fall-2026', '2026-09-07'),
                           ('spring-2027', '2027-03-15')]:
            c = grid[term]['days'][date]
            assert c[0] == '-' and c[1] == 'N', (date, c)

    def test_office_status_records_unknown_separately_from_open(self, grid):
        """Fall Break says offices are open; Spring Break says nothing. Absent
        must never be read as open."""
        assert grid['fall-2026']['days']['2026-10-12'] == '-NO'   # offices open
        assert grid['fall-2026']['days']['2026-09-07'] == '-NC'   # offices closed
        assert grid['spring-2027']['days']['2027-03-15'] == '-N.'  # page is silent

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
        assert runs_as(grid, 'fall-2026', '2026-10-13') == 'monday'
        assert runs_as(grid, 'spring-2027', '2027-02-16') == 'monday'
        # and it is NOT a no-class day -- classes do meet
        assert grid['fall-2026']['days']['2026-10-13'][1] == '.'

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
                if d.weekday() < 5:
                    assert runs_as(grid, t.id, d.isoformat()) == t.effective_weekday(d), d
                d += dt.timedelta(days=1)

    def test_teaching_dates_equal_published_class_days(self, current, grid):
        for t in current.terms:
            if t.id in grid:
                teaching = {d for d, c in grid[t.id]['days'].items() if c[0] != '-'}
                assert teaching == {d.isoformat() for d in t.class_days()}


class TestEmbedding:
    @pytest.fixture(scope='class')
    @staticmethod
    def page(years):
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
                       'Build your own schedule'):
            assert needle in page

    def test_builder_offers_every_teaching_term(self, page, grid):
        for tid in grid:
            assert tid in page

    def test_states_it_is_a_download_not_a_subscription(self, page):
        assert 'not a\nsubscription' in page or 'not a subscription' in page

    def test_reminder_is_configured_per_course_not_globally(self, page):
        """A lab and a lecture can want different reminders, so the control
        lives on the course row."""
        assert 'name="alarm"' in page
        assert 'id="alarm"' not in page, 'no single global reminder control'

    def test_reminder_options_are_offered(self, page):
        for v in ('PT5M', 'PT10M', 'PT15M', 'PT30M', 'PT1H', 'PT2H', 'P1D'):
            assert f"'{v}'" in page, v
        assert 'No reminder' in page

    def test_reminder_defaults_to_fifteen_minutes(self, page):
        assert "prev?prev.alarm:'PT15M'" in page.replace(' ', '')

    def test_a_new_row_inherits_the_previous_reminder(self, page):
        assert 'addItem(read().pop())' in page

    def test_alarm_trigger_is_negative_and_relative_to_the_event(self, page):
        """A positive or absolute TRIGGER fires after the class, or at a fixed
        wall-clock time that ignores which meeting it belongs to."""
        assert 'TRIGGER:-${c.alarm}' in page
        assert 'BEGIN:VALARM' in page and 'ACTION:DISPLAY' in page


class TestPhase2Controls:
    """Beyond classes: office hours, meetings, clubs. Two plain checkboxes
    instead of a type dropdown, because an adversarial review concluded nobody
    can reliably tell 'academic meeting' from 'staff meeting' and guessing
    wrong fails silently, months later, at an empty room."""

    @pytest.fixture(scope='class')
    @staticmethod
    def page(years):
        return emit.to_index_html(years, TODAY).decode()

    def test_no_event_type_dropdown(self, page):
        for banned in ('Meeting - academic', 'Meeting — academic',
                       'staff/admin', 'Nth weekday'):
            assert banned not in page, banned

    def test_the_two_questions_are_asked_in_plain_language(self, page):
        assert 'Follows the class timetable' in page
        assert 'Skips holidays and breaks' in page

    def test_both_default_to_class_behaviour(self, page):
        assert 'name="swaps" checked' in page
        assert 'name="skip" checked' in page

    @pytest.mark.parametrize('option', ['weekly', 'biweekly', 'dates'])
    def test_recurrence_options(self, page, option):
        assert f"['{option}'," in page

    def test_biweekly_emits_an_interval(self, page):
        assert "';INTERVAL=2'" in page

    def test_pasted_dates_must_be_strict_iso_and_inside_the_term(self, page):
        """`new Date(freeText)` is locale-dependent -- 03/04/2026 is March in
        one browser and April in another -- so only YYYY-MM-DD is accepted,
        and only if the term actually has that date."""
        assert r'/^\d{4}-\d{2}-\d{2}$/' in page
        assert "s in t.days" in page

    def test_a_rule_less_event_lists_every_date_including_the_first(self, page):
        """Without an RRULE, parsers disagree about whether DTSTART is itself
        an occurrence. dateutil drops it, so the first date silently vanished
        until every date was listed explicitly."""
        assert 's.byRule.length ? s.rdate.filter(d => d !== first) : s.rdate' in page

    def test_office_status_is_surfaced_not_acted_on(self, page):
        """RWU states office status on only 59 of 92 no-class days, so the
        tool tells the user where it knows offices were open rather than
        silently deciding for them."""
        assert 'offices are open' in page
        assert 'Untick' in page
