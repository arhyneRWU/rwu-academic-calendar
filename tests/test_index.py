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
        hero = page.split('class="hero"')[1].split('<h2 id="builder"')[0]
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
        hero = page.split('class="hero"')[1].split('<h2 id="builder"')[0]
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
        # three inline blocks: the embedded meeting grid, the schedule
        # builder, and the copy buttons. All same-origin, none fetched.
        assert page.lower().count('<script') == 3
        for bad in ('http://', 'cdn.', 'fonts.googleapis', '<link rel="stylesheet"'):
            assert bad not in page, bad

    def test_is_deterministic_for_a_given_date(self, years):
        assert emit.to_index_html(years, TODAY) == emit.to_index_html(years, TODAY)


class TestReadmeLinks:
    """The README's quick links deep-link into the page. If an anchor is
    renamed, those links land at the top with no sign anything is wrong."""

    ANCHORS = ('id="builder"', 'id="add-it-to-your-phone"')

    @pytest.mark.parametrize('anchor', ANCHORS)
    def test_anchor_exists(self, page, anchor):
        assert anchor in page

    def test_readme_links_all_resolve_to_a_real_anchor(self, page):
        import re
        from pathlib import Path
        readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text()
        frags = set(re.findall(r'rwu-academic-calendar/#([\w-]+)', readme))
        assert frags, 'README should deep-link into the site'
        for f in frags:
            assert f'id="{f}"' in page, f


class TestSecurity:
    """The builder takes free text and renders it. That is the only untrusted
    input on the whole site, so it gets its own tests."""

    def test_user_input_is_escaped_before_reaching_innerhtml(self, page):
        """Regression: an early version interpolated the course name straight
        into the preview's innerHTML, so a course called
        `<img src=x onerror=...>` executed. Self-inflicted, but a real
        injection flaw."""
        assert '${h(c.name)}' in page
        assert '${c.name}' not in page.split('preview.innerHTML')[1].split('function ics')[0]

    def test_an_escape_helper_exists_and_covers_the_dangerous_characters(self, page):
        helper = page.split('const h = s =>')[1][:260]
        for ch in ('&amp;', '&lt;', '&gt;', '&quot;', '&#39;'):
            assert ch in helper, ch

    def test_ics_output_escapes_per_rfc5545(self, page):
        """Backslash, semicolon, comma and newline are structural in ICS; an
        unescaped comma in a course name splits the field."""
        assert 'const esc =' in page

    def test_page_makes_no_third_party_requests(self, page):
        assert '<script src' not in page.lower()
        assert '<iframe' not in page.lower()
        for bad in ('cdn.', 'fonts.googleapis', 'googletagmanager',
                    'google-analytics', 'plausible', 'http://'):
            assert bad not in page, bad

    def test_no_cookies_or_storage(self, page):
        for api in ('localStorage', 'sessionStorage', 'document.cookie', 'indexedDB'):
            assert api not in page, api

    def test_builder_never_issues_a_network_request(self, page):
        """The claim on the page is that nothing leaves the browser. If a
        fetch ever appears, that claim becomes false."""
        for api in ('fetch(', 'XMLHttpRequest', 'navigator.sendBeacon', 'WebSocket'):
            assert api not in page, api

    def test_privacy_section_and_policy_link_are_present(self, page):
        assert 'id="privacy"' in page
        assert 'SECURITY.md' in page

    def test_security_policy_file_exists(self):
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / 'SECURITY.md'
        assert p.exists()
        text = p.read_text()
        assert 'Reporting a vulnerability' in text


class TestUpstreamContentIsUntrusted:
    """Everything this page renders derives from rwu.edu. `_txt()` strips tags
    and *then* unescapes entities, so a label written upstream as
    `&lt;img src=x onerror=...&gt;` comes back as live markup. The JSON and ICS
    feeds encode it safely; HTML has no such protection, so it is escaped at
    the sink.
    """

    PAYLOAD = '&lt;img src=x onerror=alert(1)&gt;'

    @pytest.fixture(scope='class')
    def poisoned_page(self):
        from rwu_calendar.extract import extract
        page = f"""
<h3>Academic Calendar 2026-2027</h3>
<table>
<tr><td>Important Fall Term Dates Fall 2026</td><td>Month</td><td>Date</td><td>Day</td></tr>
<tr><td>First Day of Classes {self.PAYLOAD}</td><td>AUG</td><td>26</td><td>WED</td></tr>
<tr><td>Last Day of Fall Classes</td><td>DEC</td><td>2</td><td>WED</td></tr>
</table>
"""
        years = extract(page, retrieved='2026-08-16')
        return emit.to_index_html(years, dt.date(2026, 8, 16)).decode()

    def test_entity_encoded_markup_upstream_does_not_become_live_markup(self, poisoned_page):
        assert '<img src=x onerror=alert(1)>' not in poisoned_page

    def test_the_label_still_renders_as_visible_text(self, poisoned_page):
        """Escaped, not dropped -- a label that looks odd should be visible so
        someone notices it, not silently swallowed."""
        assert '&lt;img src=x onerror=alert(1)&gt;' in poisoned_page

    def test_source_url_cannot_break_out_of_its_href(self):
        from rwu_calendar.model import AcademicYear, Term, Event
        ay = AcademicYear('2026-2027', '"><script>alert(1)</script>', '2026-08-16')
        t = Term(id='fall-2026', term='fall', academic_year='2026-2027')
        t.events = [
            Event(date=dt.date(2026, 8, 26), label='First Day of Classes', kinds=['term_start']),
            Event(date=dt.date(2026, 12, 2), label='Last Day of Fall Classes', kinds=['term_end']),
        ]
        ay.terms = [t]
        out = emit.to_index_html([ay], dt.date(2026, 8, 16)).decode()
        assert '<script>alert(1)</script>' not in out
