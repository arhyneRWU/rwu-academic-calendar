"""The published JSON is a CONTRACT. Downstream tools already read it.

The RWU wetlab app consumes ``no-class-days.json``. Renaming a key, changing a
date format, or dropping a field breaks it silently -- the consumer keeps
parsing and starts producing wrong schedules, which is worse than a crash.

These tests freeze the shape. **Removing or renaming anything here is a
breaking change**: add new keys freely, but never repurpose or delete an
existing one without publishing the old name alongside the new for at least a
full academic year.
"""
import datetime as dt
import re
from pathlib import Path

import pytest

from rwu_calendar import emit, serialize

DATA = Path(__file__).resolve().parents[1] / 'data'
ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')
WEEKDAYS = {'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
            'saturday', 'sunday'}


@pytest.fixture(scope='module')
def years():
    return serialize.load_dir(DATA)


@pytest.fixture(scope='module')
def ncd(years):
    return emit.to_no_class_json(years)


@pytest.fixture(scope='module')
def full(years):
    return emit.to_json(years)


class TestNoClassDaysContract:
    """``no-class-days.json`` -- the file the wetlab scheduler imports."""

    def test_top_level_keys(self, ncd):
        assert set(ncd) == {'unofficial', 'disclaimer', 'source_url', 'terms'}

    def test_term_keys(self, ncd):
        for t in ncd['terms']:
            assert set(t) == {
                'id', 'term', 'academic_year', 'classes_begin', 'classes_end',
                'no_class_dates', 'day_swaps', 'class_days',
            }, t['id']

    def test_no_class_entry_keys(self, ncd):
        for t in ncd['terms']:
            for e in t['no_class_dates']:
                assert set(e) == {'date', 'label'}

    def test_day_swap_entry_keys(self, ncd):
        for t in ncd['terms']:
            for e in t['day_swaps']:
                assert set(e) == {'date', 'observes_schedule_of', 'label'}

    def test_all_dates_are_iso_yyyy_mm_dd(self, ncd):
        for t in ncd['terms']:
            for key in ('classes_begin', 'classes_end'):
                assert t[key] is None or ISO.match(t[key]), (t['id'], key)
            for d in t['class_days']:
                assert ISO.match(d)
            for e in t['no_class_dates'] + t['day_swaps']:
                assert ISO.match(e['date'])

    def test_observes_schedule_of_is_a_lowercase_weekday(self, ncd):
        for t in ncd['terms']:
            for e in t['day_swaps']:
                assert e['observes_schedule_of'] in WEEKDAYS

    def test_term_is_one_of_four_known_values(self, ncd):
        assert {t['term'] for t in ncd['terms']} <= {'fall', 'winter', 'spring', 'summer'}

    def test_term_ids_are_stable_and_unique(self, ncd):
        ids = [t['id'] for t in ncd['terms']]
        assert len(ids) == len(set(ids))
        # id format is `<term>-<year>`; consumers key off this.
        for i in ids:
            assert re.fullmatch(r'(fall|winter|spring|summer)-\d{4}', i), i

    def test_known_term_ids_are_still_present(self, ncd):
        """A consumer that stored `fall-2026` must keep resolving it."""
        ids = {t['id'] for t in ncd['terms']}
        assert {'fall-2026', 'spring-2027', 'fall-2025', 'spring-2026'} <= ids

    def test_class_days_never_includes_a_no_class_date(self, ncd):
        for t in ncd['terms']:
            assert not set(t['class_days']) & {e['date'] for e in t['no_class_dates']}

    def test_day_swaps_are_not_listed_as_no_class_dates(self, ncd):
        """The whole point of the split. A consumer unioning the two lists
        would drop a day that actually holds classes."""
        for t in ncd['terms']:
            assert not {e['date'] for e in t['day_swaps']} & \
                       {e['date'] for e in t['no_class_dates']}

    def test_class_days_are_weekdays_within_the_teaching_span(self, ncd):
        for t in ncd['terms']:
            if not (t['classes_begin'] and t['classes_end']):
                continue
            a = dt.date.fromisoformat(t['classes_begin'])
            b = dt.date.fromisoformat(t['classes_end'])
            for s in t['class_days']:
                d = dt.date.fromisoformat(s)
                assert a <= d <= b and d.weekday() < 5, (t['id'], s)

    def test_unofficial_flag_and_disclaimer_survive(self, ncd):
        assert ncd['unofficial'] is True
        assert 'UNOFFICIAL' in ncd['disclaimer']


class TestFullCalendarContract:
    def test_top_level_keys(self, full):
        assert set(full) == {'unofficial', 'disclaimer', 'source_url',
                             'generator', 'academic_years'}

    def test_academic_year_keys(self, full):
        for ay in full['academic_years']:
            assert set(ay) == {'academic_year', 'retrieved', 'terms'}

    def test_term_keys(self, full):
        for ay in full['academic_years']:
            for t in ay['terms']:
                assert set(t) == {'id', 'term', 'classes_begin', 'classes_end',
                                  'class_day_count', 'events'}

    def test_event_keys(self, full):
        for ay in full['academic_years']:
            for t in ay['terms']:
                for e in t['events']:
                    assert set(e) == {'date', 'label', 'kinds', 'no_classes',
                                      'observes_schedule_of', 'offices_closed'}

    def test_no_classes_is_always_a_real_boolean(self, full):
        """Not null, not absent -- a consumer doing `if e['no_classes']` must
        never trip over a missing key."""
        for ay in full['academic_years']:
            for t in ay['terms']:
                for e in t['events']:
                    assert isinstance(e['no_classes'], bool)

    def test_kinds_is_always_a_nonempty_list(self, full):
        for ay in full['academic_years']:
            for t in ay['terms']:
                for e in t['events']:
                    assert isinstance(e['kinds'], list) and e['kinds']


def test_landing_page_changes_do_not_touch_the_feeds(years):
    """`to_index_html` is presentation only. If a page change ever alters a
    feed, that is a bug and this catches it."""
    before = (emit.to_json(years), emit.to_no_class_json(years),
              emit.to_ics(years, 'x'))
    emit.to_index_html(years, dt.date(2026, 8, 16))
    emit.to_index_html(years, dt.date(2027, 6, 1))
    after = (emit.to_json(years), emit.to_no_class_json(years),
             emit.to_ics(years, 'x'))
    assert before == after
