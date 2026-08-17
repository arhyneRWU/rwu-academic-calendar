"""Regressions for the defects found by the 2026-08-16 code review.

See ``LEDGER.md``. Each test names the wrong answer a user would have got,
because the fix is only obvious once you know what it was hiding.
"""
import datetime as dt
import re
from pathlib import Path

import pytest
from icalendar import Calendar

from rwu_calendar import emit, serialize, validate
from rwu_calendar.model import AcademicYear, Event, Term, link

DATA = Path(__file__).resolve().parents[1] / 'data'
TODAY = dt.date(2026, 8, 16)


@pytest.fixture(scope='module')
def years():
    return serialize.load_dir(DATA)


@pytest.fixture(scope='module')
def terms(years):
    return {t.id: t for ay in years for t in ay.terms}


@pytest.fixture(scope='module')
def page(years):
    return emit.to_index_html(years, TODAY).decode()


class TestJanuaryBelongsToTwoTerms:
    """RWU prints "Dr. Martin Luther King, Jr. Holiday, JAN 18 MON" in the
    Spring 2027 table, where spring has not started and it does nothing. The
    date falls inside the Winter intersession, which had no record of it: the
    winter feed carried no holiday and the builder put a Monday class on it."""

    def test_winter_now_knows_about_mlk(self, terms):
        assert dt.date(2027, 1, 18) in terms['winter-2027'].no_class_dates()

    def test_no_monday_class_is_scheduled_on_the_holiday(self, terms):
        w = terms['winter-2027']
        assert w.effective_weekday(dt.date(2027, 1, 18)) is None
        assert dt.date(2027, 1, 18) not in w.class_days()

    def test_the_grid_marks_it_as_no_class(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        assert emit.meeting_grid(ay)['winter-2027']['days']['2027-01-18'][:2] == '-N'

    def test_the_json_contract_lists_it_under_winter(self, years):
        wt = next(t for t in emit.to_no_class_json(years)['terms']
                  if t['id'] == 'winter-2027')
        assert any(d['date'] == '2027-01-18' for d in wt['no_class_dates'])

    def test_spring_keeps_it_too(self, terms):
        """Borrowing must not move the event out of the term that printed it."""
        assert any(e.date == dt.date(2027, 1, 18) for e in terms['spring-2027'].events)

    def test_a_terms_own_events_win_over_a_siblings(self):
        """Inheritance fills gaps; it never overrides a date the term states."""
        ay = AcademicYear('x', 'u', 'r')
        a = Term(id='a', term='winter', academic_year='x', events=[
            Event(date=dt.date(2027, 1, 4), label='First Day of Classes', kinds=['term_start']),
            Event(date=dt.date(2027, 1, 22), label='Last day of classes', kinds=['term_end']),
            Event(date=dt.date(2027, 1, 18), label='Mine', kinds=['no_classes'], no_classes=True)])
        b = Term(id='b', term='spring', academic_year='x', events=[
            Event(date=dt.date(2027, 1, 18), label='Theirs', kinds=['no_classes'], no_classes=True)])
        ay.terms = [a, b]
        link(ay)
        assert a.inherited_no_class_events() == []
        assert [e.label for e in a.no_class_events()] == ['Mine']

    def test_an_unlinked_term_does_not_explode(self):
        """`link()` is easy to forget in a new construction path; returning
        nothing is the safe failure, not an AttributeError."""
        t = Term(id='a', term='winter', academic_year='x')
        assert t.inherited_no_class_events() == []

    def test_the_borrowing_is_reported_rather_than_silent(self, years):
        problems = validate.check_cross_term(years)
        assert len(problems) == 1
        assert 'winter-2027' in problems[0].where
        assert all(p.level == 'source' for p in problems)


class TestOneEventPerCalendarDay:
    """Summer's six sessions repeat every holiday verbatim, so the feed the
    front page recommends showed Memorial Day four times and Juneteenth three
    times on the same date, in every subscriber's calendar."""

    @pytest.fixture(scope='class')
    @staticmethod
    def built(years, tmp_path_factory):
        out = tmp_path_factory.mktemp('public')
        emit.build(years, out, TODAY)
        return out

    @staticmethod
    def _events(path):
        return [(str(c['dtstart'].dt), str(c['summary']), str(c['uid']))
                for c in Calendar.from_ical(path.read_bytes()).walk('VEVENT')]

    @pytest.mark.parametrize('feed', ['rwu-no-class-days.ics', 'rwu-academic-calendar.ics',
                                      'summer-2026.ics', '2025-2026.ics'])
    def test_no_date_and_summary_appears_twice(self, built, feed):
        evs = self._events(built / feed)
        seen = [(d, s) for d, s, _u in evs]
        assert len(set(seen)) == len(seen), feed

    @pytest.mark.parametrize('feed', ['rwu-no-class-days.ics', 'rwu-academic-calendar.ics'])
    def test_every_uid_is_still_unique(self, built, feed):
        uids = [u for _d, _s, u in self._events(built / feed)]
        assert len(set(uids)) == len(uids)

    def test_memorial_day_appears_exactly_once(self, built):
        evs = self._events(built / 'rwu-no-class-days.ics')
        assert sum(1 for d, s, _u in evs
                   if d == '2026-05-25' and 'MEMORIAL' in s) == 1

    def test_the_merged_event_still_names_every_session(self, built):
        cal = Calendar.from_ical((built / 'summer-2026.ics').read_bytes())
        ev = next(c for c in cal.walk('VEVENT')
                  if str(c['dtstart'].dt) == '2026-05-25')
        assert str(ev['description']).count('Session:') == 4

    def test_a_merge_prefers_a_stated_office_status_over_silence(self):
        """RWU wrote "All University office Closed" on one 2024 copy and
        "Offices" on its siblings. Taking the first row made it a coin toss."""
        a = Event(date=dt.date(2026, 6, 19), label='X', kinds=['no_classes'],
                  no_classes=True, session='s1')
        b = Event(date=dt.date(2026, 6, 19), label='X', kinds=['no_classes', 'holiday'],
                  no_classes=True, offices_closed=True, session='s2')
        m = emit._merge([a, b])
        assert m.offices_closed is True
        assert m.kinds == ['no_classes', 'holiday']

    def test_uid_does_not_depend_on_session(self):
        one = emit._uid('2025-2026', 'summer-2026', dt.date(2026, 5, 25), 'X')
        assert one == emit._uid('2025-2026', 'summer-2026', dt.date(2026, 5, 25), 'X')


class TestRetiredTableOnlyListsRetiredYears:
    """`others = everything that is not current` put a newly extracted year
    under "Retired academic years" with a retirement date in the future. It
    fires the first time a new year is added, which is the one moment nobody
    is looking at the retired table."""

    @staticmethod
    def _rows(page, heading):
        if heading not in page:
            return []
        block = page[page.index(heading):]
        return re.findall(r'<td><strong>(\d{4}-\d{4})</strong></td>',
                          block[:block.index('</table>')])

    def test_today_nothing_is_upcoming(self, page):
        assert self._rows(page, '<h2>Retired academic years</h2>') == \
            ['2025-2026', '2024-2025', '2023-2024']
        assert '<h2>Published ahead of time</h2>' not in page

    def test_a_future_year_is_not_called_retired(self, years):
        p = emit.to_index_html(years, dt.date(2025, 9, 1)).decode()
        assert '2026-2027' not in self._rows(p, '<h2>Retired academic years</h2>')
        assert self._rows(p, '<h2>Published ahead of time</h2>') == ['2026-2027']

    def test_the_upcoming_table_is_absent_when_empty(self, page):
        assert 'Published ahead of time' not in page

    def test_a_year_with_no_fall_or_spring_does_not_kill_the_build(self):
        """What a half-extracted year looks like: RWU publishes the summer
        table first. `f'{None:%-d %b %Y}'` used to raise TypeError."""
        ay = AcademicYear('2027-2028', 'u', 'r')
        ay.terms = [Term(id='summer-2027', term='summer', academic_year='2027-2028')]
        assert emit.retires_on(ay) is None
        assert '&mdash;' in emit._year_rows([ay], TODAY)


class TestBuilderAcceptsWeekendDates:
    """The list mode tested membership in the meeting grid, which holds
    weekdays only -- so a Saturday inside the term was rejected as "not inside
    the term". The builder is pitched at clubs and practices."""

    def test_validity_is_the_term_span_not_the_weekday_grid(self, page):
        assert 's >= t.begin && s <= t.end' in page
        assert 'const usable' in page

    def test_impossible_dates_are_still_rejected(self, page):
        assert 'iso(dateOf(s)) === s' in page

    def test_the_error_message_names_the_actual_range(self, page):
        assert 'between ${fmt(t.begin)} and ${fmt(t.end)}' in page
        assert 'only dates inside ${h(t.label)}' not in page


class TestBuilderIcsIsWellFormed:
    def test_backslash_is_escaped_first(self, page):
        r"""A room "C\D" emitted \D, which is not a defined escape. Escaping it
        after ; and , would double-escape what this function just added."""
        assert r"replace(/\\/g, '\\\\')" in page
        assert page.index(r"replace(/\\/g, '\\\\')") < page.index(r"replace(/([;,])/g")

    def test_lines_are_folded(self, page):
        assert 'function fold(line)' in page
        assert 'out.map(fold)' in page

    def test_folding_measures_octets_not_characters(self, page):
        assert 'TextEncoder' in page

    def test_duplicate_rows_get_distinct_uids(self, page):
        """Two rows can honestly agree on name, days and time -- the same
        office hour in two rooms. One UID meant one survived the import."""
        assert 'const used = new Map()' in page
        assert "n > 1 ? '-' + n : ''" in page


class TestFederalHolidaysAreCheckedByDate:
    """`check_coverage` matched label text, and only for fall and spring. Both
    gaps it missed were in the other two terms. Dates are checkable; RWU's
    prose is not."""

    def test_the_arithmetic(self):
        h = validate.federal_holidays(2026)
        assert h[dt.date(2026, 1, 19)] == 'Martin Luther King Jr. Day'
        assert h[dt.date(2026, 5, 25)] == 'Memorial Day'
        assert h[dt.date(2026, 9, 7)] == 'Labor Day'
        assert h[dt.date(2026, 11, 26)] == 'Thanksgiving'

    def test_a_weekend_holiday_moves_to_the_observed_weekday(self):
        """4 July 2026 is a Saturday, observed Friday the 3rd. Checking the
        4th would have found nothing and reported all clear."""
        assert validate.federal_holidays(2026)[dt.date(2026, 7, 3)] == 'Independence Day'
        assert validate.federal_holidays(2027)[dt.date(2027, 7, 5)] == 'Independence Day'
        assert validate.federal_holidays(2025)[dt.date(2025, 7, 4)] == 'Independence Day'

    def test_the_only_gap_left_in_four_years(self, years):
        """RWU's own Summer 2026 table has no Independence Day row -- verified
        against the live page, so this is a source omission, not a parse miss.
        Deliberately not corrected in `data/`: these feeds publish what RWU
        published. See LEDGER.md D1."""
        gaps = validate.check_federal_holidays(years)
        assert [(p.where, p.message[:10]) for p in gaps] == \
            [('2025-2026/summer-2026', '2026-07-03')]

    def test_mlk_is_no_longer_reported_now_that_winter_inherits_it(self, years):
        assert not any('2027-01-18' in p.message
                       for p in validate.check_federal_holidays(years))

    def test_it_is_never_fatal(self, years):
        assert all(p.level == 'source' for p in validate.check_federal_holidays(years))
        assert validate.errors(validate.run_all(years)) == []


class TestTheTrickyControlsAreExplainedOnAPhone:
    """The two checkboxes carry the whole correctness model, and ticking the
    wrong one yields a calendar that looks entirely right. Their explanation
    lived in a `title=` tooltip, which needs a mouse hover -- so on a phone,
    where most students meet this, it did not exist."""

    def test_the_hover_only_tooltip_is_gone(self, page):
        assert 'class="why"' not in page
        assert 'cursor: help' not in page

    def test_a_real_disclosure_replaces_it(self, page):
        assert page.count('<details class="explain" open>') == 1

    def test_it_explains_both_checkboxes_not_just_the_first(self, page):
        """"Skips holidays and breaks" never had an explanation at all."""
        block = page[page.index('<details class="explain"'):]
        block = block[:block.index('</details>')]
        assert 'Follows the class timetable</strong>' in block
        assert 'Skips holidays and breaks</strong>' in block

    def test_it_says_what_to_do_when_unsure(self, page):
        assert 'Leave both ticked' in page

    def test_the_preview_is_announced_as_it_changes(self, page):
        assert 'id="preview" class="preview" aria-live="polite"' in page


class TestTheSiteAdmitsWhenItIsStale:
    """`pick_current` falls back to the most recent year once all have
    retired -- right, but the page then shows a finished year under "Current
    academic year" and looks maintained. A calendar quietly a year out of date
    is worse than one obviously missing."""

    def test_nothing_is_claimed_today(self, page):
        assert 'This calendar is out of date' not in page
        assert 'Current academic year' in page

    def test_it_says_so_once_the_featured_year_has_retired(self, years):
        p = emit.to_index_html(years, dt.date(2028, 1, 1)).decode()
        assert 'This calendar is out of date' in p
        assert 'Most recent academic year' in p
        assert 'do not plan against it' in p

    def test_the_warning_names_the_date_and_points_at_the_official_page(self, years):
        p = emit.to_index_html(years, dt.date(2028, 1, 1)).decode()
        warn = p[p.index('This calendar is out of date'):]
        warn = warn[:warn.index('</p>')]
        assert '5 May 2027' in warn, 'names when the data ran out'
        assert 'rwu.edu' in warn, 'points somewhere useful'

    def test_the_boundary_is_the_day_after_spring_ends(self, years):
        assert 'out of date' not in emit.to_index_html(years, dt.date(2027, 5, 5)).decode()
        assert 'out of date' in emit.to_index_html(years, dt.date(2027, 5, 6)).decode()


class TestUnpublishedTermsAreNamed:
    """RWU releases the four term tables at different times. The picker showed
    three options and no explanation, so someone planning a summer course
    found a silent absence instead of an answer."""

    def test_summer_2027_is_identified_as_missing(self, years):
        ay = emit.pick_current(years, TODAY)
        assert emit.missing_terms(ay) == ['Summer 2027']

    def test_the_page_says_so(self, page):
        assert 'Summer 2027</strong> has not been published by RWU yet' in page
        assert 'Nothing is broken' in page

    def test_the_academic_year_maps_to_the_right_calendar_year(self, years):
        """Fall 2026 and Summer 2027 both live in academic year 2026-2027."""
        ay = AcademicYear('2026-2027', 'u', 'r')
        assert emit.missing_terms(ay) == ['Fall 2026', 'Winter 2027',
                                          'Spring 2027', 'Summer 2027']

    def test_a_complete_year_says_nothing(self, years):
        ay = next(a for a in years if a.academic_year == '2025-2026')
        assert emit.missing_terms(ay) == []
        assert emit._missing_note(ay) == ''

    def test_the_wording_agrees_with_itself_for_one_and_for_many(self, years):
        one = emit._missing_note(emit.pick_current(years, TODAY))
        assert 'has not been published' in one and 'it is not listed' in one
        many = emit._missing_note(AcademicYear('2026-2027', 'u', 'r'))
        assert 'have not been published' in many and 'they are not listed' in many
        assert 'Spring 2027 and Summer 2027' in many


class TestBuilderScriptHasNoDuplicateDeclarations:
    """Adding the catalog picker declared `const stamp` a second time. That is
    a SyntaxError, and it kills the *entire* builder script -- every feature at
    once, silently, with the page still rendering perfectly. Every substring
    test still passed; only opening a browser found it.

    Same family as the literal CR/LF bug in `test_phase1_fixes`. Both are
    "the JS lives inside a Python string and nothing type-checks it"."""

    @staticmethod
    def _top_level_declarations(page):
        body = page[page.index('(() => {'):]
        body = body[:body.index('\n})();')]
        # Declarations at the IIFE's own scope are indented exactly two spaces.
        return re.findall(r'^  (?:const|let)\s+([A-Za-z_$][\w$]*)\s*=', body, re.M)

    def test_no_name_is_declared_twice(self, page):
        names = self._top_level_declarations(page)
        dupes = sorted({n for n in names if names.count(n) > 1})
        assert dupes == [], f'redeclared in one scope, a SyntaxError: {dupes}'

    def test_the_check_can_actually_see_declarations(self, page):
        """Guard the guard: if the indentation convention changes this test
        would pass by finding nothing at all."""
        names = self._top_level_declarations(page)
        assert len(names) > 15
        assert 'stamp' in names and 'catStamp' in names


class TestPageHardening:
    def test_the_grid_cannot_close_its_own_script_block(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        t = next(t for t in ay.terms if t.id == 'fall-2026')
        was = t.events[0].label
        t.events[0].label = 'Nasty </script><img src=x onerror=alert(1)>'
        try:
            p = emit.to_index_html(years, TODAY).decode()
            assert '</script><img' not in p
            assert p.count('<script') == 4
        finally:
            t.events[0].label = was

    def test_a_favicon_is_declared_so_none_is_requested(self, page):
        assert '<link rel="icon" href="data:,">' in page

    def test_the_page_still_fetches_nothing(self, page):
        for bad in ('http://', 'cdn.', '<script src', '<iframe'):
            assert bad not in page, bad
