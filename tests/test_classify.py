"""Every rule here exists because the real page broke a naive version of it."""
import pytest

from rwu_calendar.model import classify

# All eight day-swap phrasings RWU has used across four academic years.
# Same three facts, eight wordings -- this is the single most error-prone
# thing on the page, and a consumer that gets it wrong schedules on the
# wrong timetable rather than merely missing a day off.
SWAPS = [
    ('Friday Classes Meet, Thursday Courses do not Meet', 'friday'),
    ('Monday Schedule Observed - Monday classes Meet-Tuesday Classes do not Meet', 'monday'),
    ('Monday Schedule - Monday classes meet', 'monday'),
    ('Monday Classes Meet, Tuesday Courses do not Meet', 'monday'),
    ('Tuesday - Monday Classes Observed', 'monday'),
]


@pytest.mark.parametrize('label,observed', SWAPS)
def test_day_swap_reports_the_observed_timetable(label, observed):
    kinds, extra = classify(label)
    assert 'day_swap' in kinds
    assert extra['observes_schedule_of'] == observed


@pytest.mark.parametrize('label,_o', SWAPS)
def test_day_swap_is_never_a_no_class_day(label, _o):
    """A swap day HAS classes. Its label says "do not Meet" about the
    *displaced* day, which is exactly the phrase a naive no-class rule
    would latch onto."""
    kinds, extra = classify(label)
    assert extra.get('no_classes') is False
    assert 'no_classes' not in kinds


@pytest.mark.parametrize('label', [
    'Labor Day: No Classes - All University Offices Closed',
    'Fall Break: No Classes - All University Offices Open',
    'Thanksgiving Break: No Classes - All University Offices Closed',
    'Spring Break',                                        # never says "no classes"
    'Student Academic Showcase and Honors (SASH) *No Classes Held',
    'Student Academic Showcase and Honors (SASH) - No classes held*',
    'Dr. Martin Luther King, Jr. Holiday',                 # no "no classes" either
    'University Holiday: No Classes - All University Offices Closed',
    'Reading Day',                                         # no classes, not a holiday
])
def test_no_class_days(label):
    kinds, extra = classify(label)
    assert extra['no_classes'] is True, label
    assert 'no_classes' in kinds


def test_offices_open_and_closed_are_distinguished():
    _, closed = classify('Labor Day: No Classes - All University Offices Closed')
    _, open_ = classify('Fall Break: No Classes - All University Offices Open')
    assert closed['offices_closed'] is True
    assert open_['offices_closed'] is False


@pytest.mark.parametrize('label', [
    'Last Day of Fall Classes',
    'Last Day of Fall 2023 Classes',      # the year sits inside the phrase
    'Last Day of Classes',
])
def test_term_end_survives_a_year_in_the_label(label):
    assert 'term_end' in classify(label)[0]


def test_last_day_to_drop_is_not_the_end_of_term():
    """'Last Day to Drop a Course' is a deadline in week five, not the end
    of classes. Confusing them moves the term end by two months."""
    kinds, _ = classify('Last Day to Drop a Course Without a "W"')
    assert 'term_end' not in kinds
    assert 'add_drop' in kinds


def test_first_day():
    assert 'term_start' in classify('First Day of Classes')[0]


def test_unmatched_label_is_tagged_other_not_dropped():
    assert classify('Senior Rehearsal/BBQ : 12:00pm Fieldhouse')[0] == ['other']
