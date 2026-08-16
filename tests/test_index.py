"""The landing page: which year it promotes, and the subscribe affordances."""
import datetime as dt
from pathlib import Path

import pytest

from rwu_calendar import emit, serialize

DATA = Path(__file__).resolve().parents[1] / 'data'
TODAY = dt.date(2026, 8, 16)     # frozen: ten days before Fall 2026 begins


@pytest.fixture(scope='module')
def years():
    return serialize.load_dir(DATA)


@pytest.fixture(scope='module')
def page(years):
    return emit.to_index_html(years, TODAY).decode()


class TestCurrentYear:
    """Promotion is derived from the data against the build date, so
    extracting a new academic year features it without a code change."""

    def test_promotes_the_year_in_progress(self, years):
        assert emit.pick_current(years, TODAY).academic_year == '2026-2027'

    def test_mid_term_still_promotes_that_year(self, years):
        assert emit.pick_current(years, dt.date(2026, 10, 1)).academic_year == '2026-2027'

    def test_an_earlier_date_promotes_the_year_then_in_progress(self, years):
        assert emit.pick_current(years, dt.date(2025, 9, 15)).academic_year == '2025-2026'

    def test_the_gap_between_years_promotes_the_next_one(self, years):
        """Between Spring 2026 ending and Fall 2026 starting, the upcoming
        year is the useful one to show."""
        assert emit.pick_current(years, dt.date(2026, 6, 1)).academic_year == '2026-2027'

    def test_past_the_last_known_year_falls_back_to_the_newest(self, years):
        assert emit.pick_current(years, dt.date(2030, 1, 1)).academic_year == '2026-2027'

    def test_current_year_is_named_in_the_hero(self, page):
        hero = page.split('class="hero"')[1].split('</div>')[0]
        assert '2026-2027' in hero
        assert '2023-2024' not in hero

    def test_older_years_are_demoted_not_dropped(self, page):
        assert 'Retired academic years' in page
        for old in ('2023-2024', '2024-2025', '2025-2026'):
            assert f'{old}.ics' in page

    def test_retired_years_sit_below_the_current_one(self, page):
        assert page.index('Current academic year') < page.index('Retired academic years')


class TestRetirement:
    """A year retires when its spring term ends -- the point it stops being
    the one to plan against. A date already in the data, not a guess."""

    def test_retires_on_the_last_day_of_spring_classes(self, years):
        ay = next(a for a in years if a.academic_year == '2025-2026')
        assert emit.retires_on(ay) == dt.date(2026, 5, 6)

    def test_not_retired_on_the_last_day_itself(self, years):
        ay = next(a for a in years if a.academic_year == '2025-2026')
        assert not emit.is_retired(ay, dt.date(2026, 5, 6))
        assert emit.is_retired(ay, dt.date(2026, 5, 7))

    def test_current_year_is_not_retired(self, years):
        ay = next(a for a in years if a.academic_year == '2026-2027')
        assert not emit.is_retired(ay, TODAY)

    def test_summer_sessions_run_past_retirement_and_still_publish(self, years):
        """AY2025-26 retired in May 2026 but its summer sessions ran into
        August. Retirement decides what the page leads with, never what is
        served."""
        ay = next(a for a in years if a.academic_year == '2025-2026')
        last = max(e.date for t in ay.terms for e in t.events)
        assert last > emit.retires_on(ay)

    def test_every_retired_year_is_listed_with_its_retirement_date(self, years, page):
        table = page.split('Retired academic years')[1]
        for ay in years:
            if emit.is_retired(ay, TODAY):
                assert ay.academic_year in table
                assert f'{emit.retires_on(ay):%-d %b %Y}' in table


class TestSubscribeLinks:
    def test_webcal_scheme_for_one_tap_subscribe(self, page):
        assert f'webcal://{emit.SITE_HOST}{emit.SITE_PATH}/{emit.PRIMARY_FEED}' in page

    def test_leads_with_the_no_class_feed_not_the_full_one(self, page):
        """The full feed carries every add/drop deadline and buries a phone."""
        assert emit.PRIMARY_FEED == 'rwu-no-class-days.ics'
        hero = page.split('class="hero"')[1].split('<h2>Add it')[0]
        assert emit.PRIMARY_FEED in hero
        assert 'rwu-academic-calendar.ics' not in hero

    def test_plain_https_link_is_shown_for_copying(self, page):
        assert f'{emit.SITE_URL}/{emit.PRIMARY_FEED}' in page

    def test_webcal_helper_builds_a_subscribe_url(self):
        assert emit.webcal('x.ics') == 'webcal://arhynerwu.github.io/rwu-academic-calendar/x.ics'


class TestInstructions:
    @pytest.mark.parametrize('platform', ['iPhone', 'Google Calendar', 'Outlook'])
    def test_each_platform_has_instructions(self, page, platform):
        assert platform in page

    def test_every_instruction_block_shows_the_literal_url(self, page):
        """"Paste the link" is useless if the link is not right there. Each
        <details> block that tells someone to paste must carry the whole URL,
        not a reference to one somewhere else on the page."""
        howto = page.split('Add it to your phone')[1].split('<h2>')[0]
        blocks = howto.split('<details')[1:]
        assert len(blocks) >= 4
        for b in blocks:
            assert 'class="urlbox"' in b, b[:90]
            assert emit.SITE_URL in b, b[:90]

    def test_no_step_says_paste_the_link_without_showing_one(self, page):
        """Guards the exact regression: prose telling the user to paste,
        inside a block with no URL in it."""
        for b in page.split('<details')[1:]:
            if 'paste' in b.lower():
                assert 'class="urlbox"' in b, b[:120]

    def test_hero_also_shows_the_pasteable_url(self, page):
        hero = page.split('class="hero"')[1].split('<h2>Add it')[0]
        assert f'{emit.SITE_URL}/{emit.PRIMARY_FEED}' in hero

    def test_copy_button_is_hidden_until_javascript_enables_it(self, page):
        """Without a clipboard API the button would do nothing, so it must not
        be visible. The URL itself is always readable and selectable."""
        assert 'class="copy" type="button" hidden' in page
        assert 'navigator.clipboard' in page

    def test_alternative_feeds_are_also_given_as_pasteable_urls(self, page):
        assert f'{emit.SITE_URL}/rwu-academic-calendar.ics' in page
        assert f'{emit.SITE_URL}/no-class-days.json' in page

    def test_warns_that_google_cannot_add_a_url_from_mobile(self, page):
        assert 'cannot add a calendar by URL' in page

    def test_explains_day_swaps(self, page):
        assert 'observes_schedule_of' in page


class TestContent:
    def test_next_milestone_is_shown(self, page):
        """Fall 2026 classes begin 2026-08-26, ten days after the frozen date."""
        assert 'in 10 days' in page
        assert 'First Day of Classes' in page

    def test_unofficial_warning_is_present(self, page):
        assert 'Not an official Roger Williams University' in page

    def test_no_external_asset_requests(self, page):
        """Dependency-free: no CDN, no fonts, no external scripts. The one
        inline script is progressive enhancement for the copy buttons."""
        assert '<script src' not in page.lower()
        assert page.lower().count('<script') == 1
        for bad in ('http://', 'cdn.', 'fonts.googleapis', '<link rel="stylesheet"'):
            assert bad not in page, bad

    def test_is_deterministic_for_a_given_date(self, years):
        assert emit.to_index_html(years, TODAY) == emit.to_index_html(years, TODAY)
