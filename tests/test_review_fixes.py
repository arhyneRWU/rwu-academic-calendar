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
        assert page.count('<details class="hint">') == 1

    def test_it_sits_beside_the_checkboxes_it_explains(self, page):
        """It was a block open by default *above* the form: four phone-screens
        tall, between the term picker and the course picker, describing two
        controls that live inside an item row the reader had not created yet.
        Now it is in that row, after those two checkboxes, shut."""
        row = page[page.index("<label class=\"chk\"><input type=\"checkbox\" name=\"swaps\""):]
        row = row[:row.index('</details>')]
        assert row.index('name="skip"') < row.index('<details class="hint">')
        assert '<details class="explain"' not in page

    def test_it_explains_both_checkboxes_not_just_the_first(self, page):
        """"Skips holidays and breaks" never had an explanation at all."""
        block = page[page.index('<details class="hint">'):]
        block = block[:block.index('</details>')]
        assert 'Follows the class timetable</strong>' in block
        assert 'Skips holidays and breaks</strong>' in block

    def test_it_says_what_to_do_when_unsure(self, page):
        assert 'Not sure? Leave both.' in page

    def test_it_still_needs_no_mouse_and_no_script(self, page):
        """The whole point of P1: a <details> works on touch and keyboard and
        is read out by screen readers. Moving it must not quietly turn it back
        into something that needs a pointer."""
        block = page[page.index('<details class="hint">'):]
        block = block[:block.index('</details>')]
        assert 'title=' not in block and 'onmouseover' not in block

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


class TestTheFormLooksLikeAFilledInForm:
    """Three CSS bugs that made a working builder read as broken."""

    def test_values_are_not_rendered_in_the_caption_grey(self, page):
        """`color: inherit` on an input inherited the LABEL's grey, so every
        value the user typed came out at about 2.1:1 contrast and looked like
        placeholder text. A filled form was indistinguishable from an empty
        one. CanvasText is the system foreground and follows color-scheme."""
        assert 'color: CanvasText;' in page
        block = page[page.index('input[type=text], input[type=time], select, textarea'):]
        block = block[:block.index('}}') if '}}' in block[:400] else 400]
        assert 'color: inherit' not in block

    def test_inputs_do_not_inherit_the_caption_font_size(self, page):
        """`font: inherit` was picking up the caption's .8rem."""
        block = page[page.index('input[type=text], input[type=time], select, textarea'):][:400]
        assert 'font-size: .95rem' in block

    def test_hidden_actually_hides(self, page):
        """The browser's `[hidden] {{ display: none }}` loses to any author rule
        that sets display, and `.crow` sets `display: flex`. The date-list
        textarea was therefore visible on every row, always, whatever the
        Repeats menu said."""
        assert '[hidden] {' in page and 'display: none !important' in page

    def test_flex_items_can_shrink_below_their_content(self, page):
        """A flex item defaults to `min-width: auto` and refuses to shrink
        below its content. The course picker's longest option is a whole
        section line, so on a phone the select forced itself to 820px and the
        page scrolled sideways -- but only after a subject was chosen, which is
        why an earlier mobile check on the empty form found nothing."""
        block = page[page.index(' .crow label {'):][:420]
        assert 'min-width: 0' in block


class TestTheDownloadedFileImportsElsewhere:
    """It always produced a valid .ics, but iPhone was the only place that
    obviously worked -- because iOS opens the file on tap and every other app
    needs an Import menu nobody was told about."""

    def test_it_declares_publish(self, page):
        assert "'METHOD:PUBLISH'" in page

    def test_it_names_the_timezone_for_the_floating_times(self, page):
        assert "'X-WR-TIMEZONE:America/New_York'" in page

    def test_the_stamp_is_real_and_there_is_a_sequence(self, page):
        """DTSTAMP was frozen at 20000101. The published feeds freeze it so a
        rebuild diffs clean, but this file is a personal download -- and a
        client comparing timestamps reads a re-import as no newer than what it
        already has, which silently breaks updating in place."""
        assert 'DTSTAMP:20000101T000000Z' not in page
        assert 'new Date().toISOString()' in page
        assert "'SEQUENCE:0'" in page

    def test_the_download_declares_utf8(self, page):
        assert "type: 'text/calendar;charset=utf-8'" in page

    @pytest.mark.parametrize('platform', [
        'iPhone', 'Outlook, desktop', 'Outlook on the web', 'Google Calendar',
        'Calendar on a Mac'])
    def test_every_platform_gets_instructions(self, page, platform):
        block = page[page.index('How to import the file'):]
        assert platform in block[:block.index('</details>')], platform

    def test_it_names_the_menu_path_people_miss(self, page):
        assert 'Open &amp; Export' in page and 'Import an iCalendar' in page

    def test_it_warns_against_double_clicking_in_outlook(self, page):
        assert 'double-click' in page

    def test_it_says_google_cannot_import_on_mobile(self, page):
        assert 'mobile app cannot import a file' in page

    def test_it_explains_that_a_download_does_not_follow_changes(self, page):
        assert 'It does not follow' in page


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


class TestTheBuilderDoesNotDefaultToAClass:
    """The blank row used to sit under the catalog picker with no heading, so
    it read as a second way to add a *course*, and "+ Add another item"
    inherited that reading. Now the catalog owns classes and a labelled
    section owns everything else."""

    def test_no_item_is_built_before_the_user_asks_for_one(self, page):
        js = page[page.index('function addItem'):]
        # The load-time call and the re-add on removing the last row are both
        # gone; a row exists only because someone pressed a button. The add
        # button's own `addItem(); update();` is the one legitimate call, so
        # count rather than merely look.
        assert js.count('addItem(); update();') == 1
        assert "getElementById('add').addEventListener" in js[
            js.index('addItem(); update();') - 200:js.index('addItem(); update();')]
        assert 'if (!courses.children.length) addItem()' not in js

    def test_an_empty_list_says_so_instead_of_looking_broken(self, page):
        assert 'id="empty"' in page and 'Nothing added yet' in page
        assert "document.getElementById('empty').hidden = courses.children.length > 0" in page

    def test_the_section_heading_is_what_says_non_classes_belong_here(self, page):
        block = page[page.index('class="manual"'):]
        block = block[:block.index('</div>')]
        assert 'Anything else that repeats' in block
        for example in ('Office hours', 'committee meetings', 'club', 'work'):
            assert example in block, example

    def test_hand_entering_a_class_stays_obviously_available(self, page):
        # Terms with no course data pulled have no catalog picker at all.
        assert "a class the catalog doesn't list" in page

    def test_the_button_no_longer_says_another(self, page):
        assert '+ Add an item' in page and 'Add another item' not in page

    def test_the_name_placeholder_leads_with_something_that_is_not_a_class(self, page):
        ph = page[page.index('placeholder="e.g.'):]
        ph = ph[:ph.index('"', len('placeholder="'))]
        assert 'Office hours' in ph
        assert ph.index('Office hours') < ph.index('BIO')

    def test_submitting_an_empty_builder_explains_both_ways_in(self, page):
        assert 'Nothing to download yet' in page
        assert 'Add a class from the catalog, or add an item of your own' in page


class TestTheBuilderSaysWhatItJustDid:
    """Two silent actions, reported the same day: pressing Add gave no sign
    anything happened (the new row lands below the fold on a phone), and
    pressing Download gave no sign either — which on a platform that declines
    a synthetic anchor click means no file AND no explanation."""

    def test_adding_from_the_catalog_reports_and_resets(self, page):
        js = page[page.index("addBtn.addEventListener"):]
        js = js[:js.index('document.getElementById(\'add\')')]
        assert 'said.textContent' in js and 'said.hidden = false' in js
        assert 'sectSel.selectedIndex = 0' in js and 'addBtn.disabled = true' in js
        assert "row.classList.add('just-added')" in js

    def test_the_confirmation_is_announced_not_only_seen(self, page):
        assert '<p class="said" id="cat-said" role="status" hidden></p>' in page
        assert '<div id="done" class="done" role="status" hidden></div>' in page

    def test_a_stale_confirmation_is_cleared_when_the_subject_changes(self, page):
        block = page[page.index('async function loadSubject'):]
        assert 'said.hidden = true' in block[:block.index('sectSel.disabled = false')]

    def test_the_catalog_no_longer_hijacks_a_row_someone_added_by_hand(self, page):
        # It reused a blank first row back when the builder always made one.
        assert 'const blank = first' not in page

    def test_the_download_link_is_real_and_stays_on_the_page(self, page):
        block = page[page.index('function offer(text, name)'):]
        block = block[:block.index('document.getElementById(\'sched\')')]
        assert "a.download = name" in block and "done.append(a)" in block
        assert "done.hidden = false" in block
        # The automatic click is still attempted; it is just not the only route.
        assert 'a.click()' in block

    def test_only_one_blob_url_is_held_at_a_time(self, page):
        block = page[page.index('function offer(text, name)'):]
        assert 'if (lastUrl) URL.revokeObjectURL(lastUrl)' in block

    def test_outlook_on_a_phone_is_covered(self, page):
        block = page[page.index('How to import the file'):]
        block = block[:block.index('</details>')]
        assert 'Outlook on a phone' in block
        assert 'cannot import a' in block and 'calendar file' in block
        assert 'outlook.office.com' in block


class TestTheReminderIsSettableWithoutExpandingAnything:
    """Reminders never stopped being emitted — VALARM was in every file. But a
    catalog row arrives collapsed, so the only control for it was behind a
    click nobody makes, and the collapsed line did not say what it was set to.
    A setting you cannot see or reach is a setting you have lost."""

    def test_there_is_one_control_for_the_whole_schedule(self, page):
        assert 'id="alarm-all"' in page
        assert "ALARMS.forEach(([v, l]) => alarmAll.add(new Option(l, v," in page

    def test_it_moves_every_row_that_was_not_set_by_hand(self, page):
        block = page[page.index('alarmAll.addEventListener'):]
        block = block[:block.index('});')]
        assert 'if (row.dataset.alarmSet) continue' in block
        assert "row.querySelector('[name=alarm]').value = alarmAll.value" in block

    def test_a_row_set_by_hand_stops_following_it(self, page):
        assert "row.dataset.alarmSet = '1'" in page

    def test_the_collapsed_line_says_what_the_reminder_is(self, page):
        js = page[page.index('function describeItem'):]
        js = js[:js.index('function refreshItems')]
        assert js.count("alarmLabel(c.alarm) : 'no reminder'") == 2   # timed and listed-date rows

    def test_the_alarm_still_reaches_the_file(self, page):
        assert 'BEGIN:VALARM' in page and 'TRIGGER:-${c.alarm}' in page


class TestRwuDatesRideAlongWithAPersonalSchedule:
    """A downloaded schedule used to contain only what you typed, so the dates
    that *change* it — the day swap especially — were visible only if you also
    subscribed to a feed. They now come along, as free time."""

    def test_the_grid_carries_the_terms_own_dates(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        notes = emit.meeting_grid(ay)['fall-2026']['rwu']
        got = {n['s'] for n in notes}
        assert 'RWU: First Day of Classes' in got
        assert 'RWU: Reading Day' in got
        assert 'RWU: Tuesday runs a Monday schedule' in got
        assert any('Thanksgiving' in x for x in got)

    def test_a_day_swap_says_which_day_it_is_and_which_it_runs_as(self, years):
        """RWU has written this eight ways in four years; a line read once, on
        a phone, cannot be one of them."""
        ay = next(a for a in years if a.academic_year == '2026-2027')
        swap = next(n for n in emit.meeting_grid(ay)['fall-2026']['rwu']
                    if 'runs a' in n['s'])
        assert swap['s'] == 'RWU: Tuesday runs a Monday schedule'
        assert swap['x'] == 'Tuesday - Monday Classes Observed'   # RWU's own words kept

    def test_the_uid_is_the_one_the_published_feed_uses(self, years):
        """So subscribing AND downloading gives one Thanksgiving, not two."""
        ay = next(a for a in years if a.academic_year == '2026-2027')
        note = next(n for n in emit.meeting_grid(ay)['fall-2026']['rwu']
                    if 'Thanksgiving' in n['s'])
        feed = emit.to_ics([ay], 'x', predicate=lambda e: e.no_classes).decode()
        assert f"UID:{note['u']}" in feed.replace('\r\n ', '')

    def test_summer_sessions_only_get_their_own_window(self, years):
        ay = next(a for a in years if a.academic_year == '2025-2026')
        grid = emit.meeting_grid(ay)
        sessions = [k for k in grid if k.startswith('summer-')]
        assert sessions, 'summer should be split into sessions'
        for gid in sessions:
            for n in grid[gid]['rwu']:
                assert grid[gid]['begin'] <= n['d'] <= grid[gid]['end'], (gid, n)

    def test_they_are_emitted_all_day_and_never_block(self, page):
        block = page[page.index('for (const n of rwuPicked(GRID[termId]))'):]
        block = block[:block.index("out.push('END:VCALENDAR')")]
        assert 'DTSTART;VALUE=DATE:${stamp(n.d)}' in block
        assert 'DTEND;VALUE=DATE:${stamp(nextDay(n.d))}' in block
        assert 'TRANSP:TRANSPARENT' in block
        assert 'X-MICROSOFT-CDO-BUSYSTATUS:FREE' in block   # what Outlook reads
        # The only alarm here is the deadline one, and it is conditional.
        assert block.count('BEGIN:VALARM') == 1 and 'if (n.a) out.push' in block

    def test_the_published_feeds_do_not_make_subscribers_look_busy(self, tmp_path, years):
        feed = emit.to_ics(years, 'x').decode()
        assert feed.count('TRANSP:TRANSPARENT') == feed.count(
            'X-MICROSOFT-CDO-BUSYSTATUS:FREE') == feed.count('BEGIN:VEVENT')

    def test_closures_are_on_by_default_and_can_be_turned_off(self, page):
        assert '<input type="checkbox" class="rwu-g" value="closures" checked>' in page
        assert "for (const b of rwuBoxes) b.addEventListener('change', update)" in page

    def test_the_preview_accounts_for_them(self, page):
        assert 'function rwuLine(t)' in page
        assert "if (!picked.length) return ''" in page


class TestOutlookCanKeepTheSeriesTogether:
    """Reported from Outlook: an imported schedule arrived as ~39 separate
    appointments per course instead of one editable recurring series. The file
    was already a proper series — one VEVENT, one RRULE — so the loss happened
    inside Outlook's importer, on the two constructs it handles worst."""

    def test_no_rdate_anywhere(self, page):
        """Outlook's recurrence model cannot say "and also this one date". Faced
        with RDATE it abandons the pattern rather than the extra date, and
        expands every meeting into its own appointment."""
        assert 'RDATE:' not in page

    def test_the_gained_day_swap_date_is_its_own_event(self, page):
        block = page[page.index('const extra = s.byRule.length'):]
        block = block[:block.index("// RWU's own dates, last")]
        assert 'BEGIN:VEVENT' in block and 'RRULE' not in block
        assert '-${stamp(d)}@rwu-academic-calendar' in block   # its own stable UID
        assert 'Extra meeting: this date runs a different' in block

    def test_one_exdate_property_per_date(self, page):
        """A comma-joined EXDATE is legal and folds past 75 octets; Outlook is
        reliable with neither."""
        assert 'for (const d of s.exdate) out.push(`EXDATE:${at(d)}`)' in page
        assert "'EXDATE:' + s.exdate.map(at).join(',')" not in page

    def test_the_recurring_part_is_still_one_event(self, page):
        assert "'RRULE:FREQ=WEEKLY'" in page
        assert 'UNTIL=' in page


class TestStudentDeadlinesAreOptInAndRemind:
    """Add/drop and withdrawal dates were in the data and not offered. They
    are the dates on RWU's calendar that cost money to miss."""

    def test_deadlines_are_their_own_group(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        notes = emit.meeting_grid(ay)['fall-2026']['rwu']
        by = {}
        for n in notes:
            by.setdefault(n['g'], []).append(n['s'])
        assert set(by) == {'closures', 'term', 'deadlines'}
        assert any('Drop a Course With the "W"' in x for x in by['deadlines'])
        assert any('Final Examinations' in x for x in by['deadlines'])
        assert any('Registration Begins' in x for x in by['deadlines'])

    def test_only_add_drop_dates_carry_a_reminder(self, years):
        """An alarm on all ten would train people to dismiss the two that
        matter."""
        ay = next(a for a in years if a.academic_year == '2026-2027')
        notes = emit.meeting_grid(ay)['fall-2026']['rwu']
        alarmed = [n['s'] for n in notes if n.get('a')]
        assert len(alarmed) == 4
        assert all('Add a Course' in x or 'Drop a Course' in x for x in alarmed)
        assert not any(n.get('a') for n in notes if n['g'] != 'deadlines')

    def test_grades_and_residence_life_are_not_offered(self, years):
        """They are in the data. Nobody plans around when the Registrar
        receives grades, and a hall closing is not a deadline you can miss."""
        ay = next(a for a in years if a.academic_year == '2026-2027')
        got = {n['s'] for n in emit.meeting_grid(ay)['fall-2026']['rwu']}
        assert not any('Grades' in x for x in got)
        assert not any('Residence Halls' in x for x in got)
        assert not any('Orientation' in x for x in got)

    def test_deadlines_are_off_until_ticked(self, page):
        assert '<input type="checkbox" class="rwu-g" value="deadlines">' in page
        assert 'value="deadlines" checked' not in page

    def test_the_reminder_is_the_afternoon_before_not_midnight(self, page):
        """An all-day event starts at midnight, so -P1D fires at 00:00 the
        previous day -- an alert nobody is awake for."""
        assert "'TRIGGER:-PT9H'" in page
        assert "'TRIGGER:-P1D'" not in page

    def test_a_deadline_still_shows_as_free(self, page):
        block = page[page.index('for (const n of rwuPicked(GRID[termId]))'):]
        block = block[:block.index("out.push('END:VCALENDAR')")]
        # The alarm is added inside the same VEVENT, after the busy status.
        assert block.index('X-MICROSOFT-CDO-BUSYSTATUS:FREE') < block.index('if (n.a)')

    def test_counts_are_per_term_and_an_empty_group_disables_itself(self, page):
        assert 'function rwuCounts(t)' in page
        assert "'(none this term)'" in page
        assert "querySelector('input').disabled = !n" in page


class TestTheExamGridCaveat:
    """A beta tester compared our finals dates against the Registrar's exam
    grid and found a Saturday we do not list. We match the academic calendar
    exactly; the two RWU documents disagree with each other."""

    def test_our_finals_match_the_academic_calendar(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        t = next(t for t in ay.terms if t.id == 'fall-2026')
        finals = sorted(e.date.isoformat() for e in t.events if 'finals' in e.kinds)
        assert finals == ['2026-12-04', '2026-12-07', '2026-12-08', '2026-12-09']

    def test_no_year_claims_a_saturday_exam_day(self, years):
        """RWU's calendar has never listed one. If a future extraction produces
        one, it is worth a human look before it ships."""
        for ay in years:
            for t in ay.terms:
                for e in t.events:
                    if 'finals' in e.kinds:
                        assert e.date.weekday() != 5, (ay.academic_year, e.date)

    def test_the_page_says_the_exam_grid_is_a_different_document(self, page):
        assert 'exam grid' in page
        assert 'This tool reads the academic' in page and 'calendar only' in page

    def test_the_caveat_names_no_specific_term(self, page):
        """It sits beside a term picker; naming Fall 2026's dates would be
        wrong the moment someone chooses Spring."""
        block = page[page.index('Exam days are the ones'):]
        block = block[:block.index('</p>')]
        for stale in ('Fall 2026', 'December', '7–9'):
            assert stale not in block, stale


class TestTheBuilderComesFirst:
    """Measured at 375px: the first control anyone can use sat 3.6 screens
    down, below a complete second feature. Andrew's call, on product grounds:
    most people are here for the builder, not the subscription."""

    def test_the_builder_precedes_the_feed_section(self, page):
        assert page.index('id="builder"') < page.index('id="feeds"')

    def test_the_jump_link_past_the_feeds_is_gone_with_its_reason(self, page):
        """A banner reading "Most people want this →" existed to skip the
        section above the builder. Nothing is above it now."""
        assert 'class="banner"' not in page
        assert 'Most people want this' not in page
        assert '.banner {' not in page and 'banner-kicker' not in page

    def test_only_one_h1_and_no_duplicate_year_heading(self, page):
        assert page.count('<h1') == 1
        # The hero's year was an <h2>; under its own section heading that made
        # two h2s in a row saying different things.
        assert '<p class="hero-year">' in page

    def test_the_step_list_went_with_the_sentence_that_replaced_it(self, page):
        assert 'class="steps"' not in page
        assert '.steps {' not in page          # and its CSS
        assert 'Pick your term, add your classes, download.' in page
