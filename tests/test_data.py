"""Golden tests over the committed data in ``data/``.

These are the ones that catch a regression in the extractor after RWU
changes the page again: the numbers below were read off the source by hand
on 2026-08-16.
"""
import datetime as dt
from pathlib import Path

import pytest

from rwu_calendar import serialize, validate

DATA = Path(__file__).resolve().parents[1] / 'data'

# term id -> (classes_begin, classes_end, no-class days, class days)
EXPECTED = {
    'fall-2023':   ('2023-08-30', '2023-12-13', 7, 70),
    'spring-2024': ('2024-01-24', '2024-05-08', 9, 68),
    'fall-2024':   ('2024-08-28', '2024-12-11', 7, 70),
    'spring-2025': ('2025-01-22', '2025-05-07', 9, 68),
    'fall-2025':   ('2025-08-27', '2025-12-10', 7, 70),
    'spring-2026': ('2026-01-21', '2026-05-06', 9, 68),
    'fall-2026':   ('2026-08-26', '2026-12-02', 7, 65),
    'spring-2027': ('2027-01-27', '2027-05-05', 10, 63),
}


@pytest.fixture(scope='module')
def years():
    ys = serialize.load_dir(DATA)
    assert ys, f'no YAML in {DATA}'
    return ys


@pytest.fixture(scope='module')
def terms(years):
    return {t.id: t for ay in years for t in ay.terms}


def test_four_academic_years(years):
    assert {ay.academic_year for ay in years} == {
        '2023-2024', '2024-2025', '2025-2026', '2026-2027'}


def test_no_structural_errors(years):
    assert validate.errors(validate.run_all(years)) == []


@pytest.mark.parametrize('tid,exp', EXPECTED.items())
def test_term_shape(terms, tid, exp):
    begin, end, n_noclass, n_classdays = exp
    t = terms[tid]
    assert t.classes_begin == dt.date.fromisoformat(begin)
    assert t.classes_end == dt.date.fromisoformat(end)
    assert len(t.no_class_dates()) == n_noclass
    assert len(t.class_days()) == n_classdays


def test_every_fall_and_spring_term_has_exactly_one_day_swap(terms):
    for tid in EXPECTED:
        assert len(terms[tid].day_swaps()) == 1, tid


def test_terms_begin_and_end_on_a_wednesday(terms):
    """True for all eight fall/spring terms on the page. If RWU ever changes
    this the test should fail and be updated deliberately -- it is a strong
    signal that a date was misparsed."""
    for tid in EXPECTED:
        assert terms[tid].classes_begin.weekday() == 2, tid
        assert terms[tid].classes_end.weekday() == 2, tid


def test_reading_day_falls_outside_the_teaching_span(terms):
    """Reading Day is a no-class day that sits after the last day of classes,
    so it must not be double-counted as a cancelled class day."""
    for tid in EXPECTED:
        t = terms[tid]
        reading = [e.date for e in t.events if 'reading_day' in e.kinds]
        assert reading, tid
        assert all(d > t.classes_end for d in reading), tid


def test_all_terms_present(years):
    ids = {t.id for ay in years for t in ay.terms}
    assert len(ids) == 15, sorted(ids)


def test_known_source_errors_are_reported_not_swallowed(years):
    """RWU's page prints a weekday beside each date, which is a free checksum.
    Seven of them disagree with the actual weekday as of 2026-08-16."""
    src = [p for p in validate.check_weekdays(years) if p.level == 'source']
    assert len(src) == 7
