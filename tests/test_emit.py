import datetime as dt
from pathlib import Path

import pytest
from icalendar import Calendar

from rwu_calendar import emit, serialize

DATA = Path(__file__).resolve().parents[1] / 'data'


@pytest.fixture(scope='module')
def years():
    return serialize.load_dir(DATA)


@pytest.fixture(scope='module')
def cal(years):
    return Calendar.from_ical(emit.to_ics(years, 'test'))


def test_parses_as_icalendar(cal):
    assert cal['prodid'] == emit.PRODID
    assert cal['version'] == '2.0'


def test_every_uid_is_unique(cal):
    uids = [str(c['uid']) for c in cal.walk('VEVENT')]
    assert len(uids) == len(set(uids))


def test_uids_are_stable_across_builds(years):
    """A UID that changes between builds makes every subscribed calendar
    append a duplicate on each poll until it is unusable -- the classic ICS
    bug. Nothing about the UID may depend on build time."""
    a = [str(c['uid']) for c in Calendar.from_ical(emit.to_ics(years, 'x')).walk('VEVENT')]
    b = [str(c['uid']) for c in Calendar.from_ical(emit.to_ics(years, 'x')).walk('VEVENT')]
    assert a == b


def test_rebuild_is_byte_identical(years):
    """So a rebuild with no data change produces an empty git diff."""
    assert emit.to_ics(years, 'x') == emit.to_ics(years, 'x')


def test_all_day_events_use_an_exclusive_dtend(cal):
    """RFC 5545 DTEND is exclusive for DATE values. Off by one here shows up
    as every holiday appearing a day short, or spilling a day long."""
    for c in cal.walk('VEVENT'):
        start, end = c['dtstart'].dt, c['dtend'].dt
        assert isinstance(start, dt.date) and not isinstance(start, dt.datetime)
        assert end > start
        assert (end - start).days == 1


def test_day_swap_summary_names_the_observed_timetable(cal):
    hits = [c for c in cal.walk('VEVENT')
            if c['dtstart'].dt == dt.date(2026, 10, 13)]
    assert hits and '[Monday schedule]' in str(hits[0]['summary'])


def test_no_class_feed_keeps_swaps_and_drops_deadlines(years):
    sub = Calendar.from_ical(
        emit.to_ics(years, 'x', predicate=lambda e: e.no_classes or e.observes_schedule_of))
    dates = {c['dtstart'].dt for c in sub.walk('VEVENT')}
    assert dt.date(2026, 11, 25) in dates       # Thanksgiving
    assert dt.date(2026, 10, 13) in dates       # the swap day
    assert dt.date(2026, 9, 2) not in dates     # an add/drop deadline


def test_every_event_carries_the_unofficial_disclaimer(cal):
    for c in cal.walk('VEVENT'):
        assert 'UNOFFICIAL' in str(c['description'])


class TestJson:
    def test_no_class_json_separates_swaps_from_days_off(self, years):
        d = emit.to_no_class_json(years)
        t = next(x for x in d['terms'] if x['id'] == 'fall-2026')
        swap_dates = {s['date'] for s in t['day_swaps']}
        off_dates = {s['date'] for s in t['no_class_dates']}
        assert swap_dates == {'2026-10-13'}
        assert not (swap_dates & off_dates), 'a swap day is not a day off'
        assert t['day_swaps'][0]['observes_schedule_of'] == 'monday'

    def test_class_days_are_iso_and_exclude_no_class_dates(self, years):
        d = emit.to_no_class_json(years)
        t = next(x for x in d['terms'] if x['id'] == 'fall-2026')
        assert len(t['class_days']) == 65
        assert not (set(t['class_days']) & {x['date'] for x in t['no_class_dates']})

    def test_full_json_is_marked_unofficial(self, years):
        assert emit.to_json(years)['unofficial'] is True


def test_build_writes_the_expected_file_set(years, tmp_path):
    names = {p.name for p in emit.build(years, tmp_path)}
    assert {'rwu-academic-calendar.ics', 'rwu-no-class-days.ics',
            'rwu-academic-calendar.json', 'no-class-days.json',
            '2026-2027.ics', '2026-2027.json'} <= names
