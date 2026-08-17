"""The course catalog puller, and the five fields it is allowed to keep.

The fixture is a real, unedited ``/Student/Courses/Sections`` response captured
on 2026-08-16. Parsing is tested against it rather than against something
hand-written, because the whole risk here is that Roger Central's shape is not
what we assumed -- the first draft of this parser read ``PlannedMeetings``,
which does not exist.
"""
import json
from pathlib import Path

import pytest

from rwu_calendar import courses

FIXTURE = Path(__file__).parent / 'fixtures' / 'roger-central-section.json'
DATA = Path(__file__).resolve().parents[1] / 'data' / 'courses'


@pytest.fixture(scope='module')
def payload():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def section(payload):
    return payload['SectionsRetrieved']['TermsAndSections'][0]['Sections'][0]['Section']


class TestParsingARealResponse:
    def test_it_reads_the_meeting(self, section):
        got = courses._read_section(section)
        assert len(got) == 1
        s = got[0]
        assert s.section == 'MATH.421.01'
        assert s.title == 'Senior Seminar in Math'
        assert s.days == ['monday', 'wednesday', 'friday']
        assert (s.start, s.end) == ('14:00', '14:50')
        assert s.room == 'College of Arts and Sciences 162'

    def test_it_reads_formatted_meeting_times_not_meetings(self, section):
        """``Meetings[].StartTime`` is an ISO datetime stamped with *today's*
        date in UTC -- '2026-08-16T18:00:00+00:00' for a 2:00 PM class. Right
        only by accident, and wrong across daylight saving."""
        raw = section['Meetings'][0]['StartTime']
        assert 'T18:00:00+00:00' in raw, 'fixture no longer shows the trap'
        assert courses._read_section(section)[0].start == '14:00'


class TestTimeAndDayParsing:
    @pytest.mark.parametrize('raw,want', [
        ('14:00:00', '14:00'), ('09:05:00', '09:05'), ('8:30', '08:30'),
        ('2:50 PM', '14:50'), ('12:00 PM', '12:00'), ('12:30 AM', '00:30'),
        ('', ''), (None, ''), ('nonsense', ''),
    ])
    def test_hhmm(self, raw, want):
        assert courses._hhmm(raw) == want

    @pytest.mark.parametrize('raw,want', [
        ('M/W/F', ['monday', 'wednesday', 'friday']),
        ('Th', ['thursday']),
        ('T/Th', ['tuesday', 'thursday']),
        ('Sa/Su', ['saturday', 'sunday']),
        ('M, W', ['monday', 'wednesday']),
        ('', []), ('Zz', []),
    ])
    def test_days(self, raw, want):
        assert courses._days(raw) == want

    def test_booleans_arrive_as_strings(self):
        """Colleague sends 'True'/'False'. Both are truthy in Python, so the
        naive check fails open and every TBD section gets scheduled."""
        assert courses._truthy('True') is True
        assert courses._truthy('False') is False
        assert bool('False') is True, 'the trap this guards'

    def test_a_tbd_meeting_is_skipped(self, section):
        import copy
        s = copy.deepcopy(section)
        s['FormattedMeetingTimes'][0]['ShowTBD'] = 'True'
        assert courses._read_section(s) == []

    def test_a_section_with_no_days_is_skipped(self, section):
        import copy
        s = copy.deepcopy(section)
        s['FormattedMeetingTimes'][0]['DaysOfWeekDisplay'] = ''
        assert courses._read_section(s) == [], 'online/async sections have no pattern'

    def test_two_meeting_patterns_become_two_sections(self, section):
        import copy
        s = copy.deepcopy(section)
        lab = copy.deepcopy(s['FormattedMeetingTimes'][0])
        lab.update({'DaysOfWeekDisplay': 'Th', 'StartTime': '13:00:00',
                    'EndTime': '15:50:00'})
        s['FormattedMeetingTimes'].append(lab)
        got = courses._read_section(s)
        assert len(got) == 2
        assert [x.days for x in got] == [['monday', 'wednesday', 'friday'], ['thursday']]


class TestOnlyFiveFieldsAreKept:
    """The section payload carries instructor names, seat counts and enrolment.
    None of it is read, stored or published. A meeting pattern is a fact about
    a room and a clock; the rest are facts about people."""

    def test_the_source_really_does_contain_the_sensitive_fields(self, payload):
        """If this stops being true the test below proves nothing."""
        blob = json.dumps(payload)
        assert 'FacultyDetails' in blob or 'Faculty' in blob
        assert 'Available' in blob or 'Capacity' in blob

    def test_the_dataclass_has_exactly_five_and_a_title(self, section):
        got = courses._read_section(section)[0].to_json()
        assert set(got) == {'section', 'title', 'days', 'start', 'end', 'room'}

    def test_every_published_section_has_exactly_the_six_keys(self):
        """The structural guarantee, and the one that actually matters: a field
        we never store cannot leak. Checked across the real committed data, not
        just one parsed fixture."""
        for p in sorted(DATA.glob('*/*.json')):
            for s in json.loads(p.read_text(encoding='utf-8'))['sections']:
                assert set(s) == {'section', 'title', 'days', 'start', 'end', 'room'}, p.name

    @pytest.mark.parametrize('banned', [
        'faculty', 'instructor', 'seat', 'capacity', 'available', 'waitlist'])
    def test_no_identifier_or_room_names_a_person(self, banned):
        """Titles are excluded on purpose: they are RWU's own prose, and
        'Continuous Enrollment Status' is a real course name. Matching on it
        made this test fail for a reason that had nothing to do with privacy,
        which is how a blunt test gets deleted instead of fixed."""
        for p in sorted(DATA.glob('*/*.json')):
            for s in json.loads(p.read_text(encoding='utf-8'))['sections']:
                for field in ('section', 'room'):
                    assert banned not in s[field].lower(), f'{p.name}: {s[field]!r}'

    def test_no_section_carries_a_seat_count(self):
        """Roger Central renders these as '12 / 24 / 0'. If one ever appears in
        our data, something started reading the enrolment block."""
        import re
        for p in sorted(DATA.glob('*/*.json')):
            for s in json.loads(p.read_text(encoding='utf-8'))['sections']:
                blob = json.dumps(s)
                assert not re.search(r'\d+\s*/\s*\d+\s*/\s*\d+', blob), f'{p.name}: {blob}'

    def test_the_note_states_the_promise(self):
        for p in sorted(DATA.glob('*/*.json')):
            note = json.loads(p.read_text(encoding='utf-8'))['note'].lower()
            assert 'instructor' in note and 'not collected' in note

    def test_no_course_file_carries_dates(self):
        """Roger Central's section range runs through finals week -- Fall 2026
        ends 12-09 there and 12-02 here. Not collecting it at all is the
        cheapest way to guarantee it never becomes a meeting date."""
        for p in sorted(DATA.glob('*/*.json')):
            for s in json.loads(p.read_text(encoding='utf-8'))['sections']:
                assert not any(k in s for k in ('start_date', 'end_date', 'dates'))


class TestTheSectionLookupKey:
    """`courseId` must be the course's numeric `Id`. The obvious
    `SUBJECT_NUMBER` form is accepted for some courses and silently returns an
    empty result for others -- `BIO_101` works, `HIST_100` returns nothing with
    no error. Keying on it collected 417 patterns, looked completely
    successful, and dropped most of the catalog."""

    class _FakeCatalog(courses.Catalog):
        def __init__(self):
            super().__init__(delay=0)
            self.sent = []
            self._token = 'x'

        def _post(self, path, payload):
            self.sent.append((path, payload))
            return {'SectionsRetrieved': {'TermsAndSections': []}}

    def test_it_sends_the_numeric_id(self):
        cat = self._FakeCatalog()
        cat.sections({'Id': 3213, 'SubjectCode': 'HIST', 'Number': '100',
                      'MatchingSectionIds': ['132523']}, '26/FA')
        _path, payload = cat.sent[0]
        assert payload['courseId'] == '3213'
        assert payload['courseId'] != 'HIST_100'

    def test_a_course_with_no_id_is_skipped_rather_than_guessed(self):
        cat = self._FakeCatalog()
        assert cat.sections({'SubjectCode': 'HIST', 'Number': '100',
                             'MatchingSectionIds': ['1']}, '26/FA') == []
        assert cat.sent == []

    def test_no_sections_means_no_request(self):
        cat = self._FakeCatalog()
        assert cat.sections({'Id': 1, 'MatchingSectionIds': []}, '26/FA') == []
        assert cat.sent == []

    def test_a_subject_with_courses_but_no_patterns_is_called_out(self):
        """The warning that would have caught the wrong key on the first run,
        instead of after the data was committed."""
        class Cat(self._FakeCatalog):
            def connect(self): pass
            def courses(self, subject, term):
                yield {'Id': 1, 'Number': '100', 'MatchingSectionIds': ['9']}
        lines = []
        courses.pull('26/FA', ['HIST'], catalog=Cat(), progress=lines.append)
        assert any('NO patterns' in x for x in lines), lines


class TestTermMapping:
    @pytest.mark.parametrize('term_id,want', [
        ('fall-2026', '26FA'), ('spring-2027', '27SP'), ('winter-2027', '27WI'),
        ('fall-2023', '23FA'),
    ])
    def test_our_ids_map_to_roger_central(self, term_id, want):
        assert courses.rc_term_slug(term_id) == want

    @pytest.mark.parametrize('term_id', ['summer-2026', 'summer-2026::4-week', '', 'nonsense'])
    def test_unmappable_terms_return_none(self, term_id):
        """Summer is deliberately unmapped: RWU splits it into Summer I and II,
        which do not line up with the six overlapping sessions we model."""
        assert courses.rc_term_slug(term_id) is None

    def test_term_slug_drops_the_slash(self):
        assert courses.term_slug('26/FA') == '26FA'


class TestStorage:
    def test_round_trip(self, tmp_path, section):
        secs = courses._read_section(section)
        written = courses.write_dir('26/FA', {'MATH': secs}, tmp_path,
                                   retrieved='2026-08-16')
        assert [p.name for p in written] == ['MATH.json']
        doc = json.loads(written[0].read_text(encoding='utf-8'))
        assert doc['term'] == '26/FA' and doc['subject'] == 'MATH'
        assert doc['retrieved'] == '2026-08-16'
        assert doc['unofficial'] is True
        assert doc['sections'][0]['section'] == 'MATH.421.01'

    def test_available_lists_subjects_per_term(self, tmp_path, section):
        courses.write_dir('26/FA', {'MATH': courses._read_section(section)}, tmp_path)
        courses.write_dir('27/SP', {'BIO': courses._read_section(section)}, tmp_path)
        assert courses.available(tmp_path) == {'26FA': ['MATH'], '27SP': ['BIO']}

    def test_available_is_empty_when_nothing_has_been_pulled(self, tmp_path):
        assert courses.available(tmp_path / 'nope') == {}


class TestTransientFailures:
    """A term is ~850 requests over a quarter of an hour, so a dropped
    connection in the middle is ordinary. The first long run died outright on
    `[Errno 60] Operation timed out` at subject six."""

    def _catalog(self, monkeypatch, outcomes):
        monkeypatch.setattr(courses.time, 'sleep', lambda s: None)
        cat = courses.Catalog(delay=0)
        cat._token = 'x'
        calls = []

        class Opener:
            def open(self, req, timeout=None):
                calls.append(1)
                out = outcomes[len(calls) - 1]
                if isinstance(out, Exception):
                    raise out
                class R:
                    def __enter__(self_): return self_
                    def __exit__(self_, *a): return False
                    def read(self_): return out
                return R()
        cat._opener = Opener()
        return cat, calls

    def test_a_timeout_is_retried(self, monkeypatch):
        import urllib.error
        cat, calls = self._catalog(monkeypatch, [
            urllib.error.URLError('timed out'), urllib.error.URLError('again'), b'{"ok":1}'])
        got = cat._open(courses.urllib.request.Request('https://x/'))
        assert got == b'{"ok":1}'
        assert len(calls) == 3

    def test_it_gives_up_eventually_rather_than_looping(self, monkeypatch):
        import urllib.error
        cat, calls = self._catalog(monkeypatch, [urllib.error.URLError('nope')] * 8)
        with pytest.raises(RuntimeError, match='after 4 attempts'):
            cat._open(courses.urllib.request.Request('https://x/'))
        assert len(calls) == 4

    def test_a_4xx_is_not_retried(self, monkeypatch):
        import urllib.error
        err = urllib.error.HTTPError('https://x/', 404, 'gone', {}, None)
        cat, calls = self._catalog(monkeypatch, [err])
        with pytest.raises(urllib.error.HTTPError):
            cat._open(courses.urllib.request.Request('https://x/'))
        assert len(calls) == 1, 'a 404 means the same thing every time'


class TestPoliteness:
    def test_the_user_agent_identifies_the_project(self):
        """A scraper RWU cannot trace back to a person is one they block rather
        than email about."""
        assert 'github.com/arhyneRWU' in courses.USER_AGENT

    def test_the_default_delay_is_a_full_second(self):
        assert courses.DELAY >= 1.0

    def test_requests_are_actually_paced(self, monkeypatch):
        slept = []
        monkeypatch.setattr(courses.time, 'sleep', lambda s: slept.append(s))
        clock = iter([0.0, 0.0, 0.0, 0.0])
        monkeypatch.setattr(courses.time, 'monotonic', lambda: next(clock))
        cat = courses.Catalog(delay=1.0)
        cat._wait()
        cat._wait()
        assert slept and slept[0] > 0, 'second request must wait'
