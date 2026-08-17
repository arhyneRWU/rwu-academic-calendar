"""Pull course meeting patterns from RWU's public course catalog.

Roger Central (Ellucian Colleague Self-Service) publishes the catalog with no
login at all -- the same information anyone can page through by hand at
<https://collselfsrvprod.rwu.edu/Student/Courses>. It is a JSON app behind a
JavaScript front end, so this talks to the JSON directly rather than parsing
rendered HTML.

**Five fields, deliberately.** Section code, title, days, start/end time, room.
The section payload also carries instructor names, seat counts and enrolment
figures; none of that is read, stored or published here. A course's meeting
pattern is a fact about a room and a clock. Who teaches it and how full it is
are facts about people, and this project has no reason to republish them.

**What this is for.** The schedule builder needs days and times to turn "BIO
320" into a calendar. It gets the *dates* from the academic calendar grid, not
from here -- Roger Central's section range runs through finals week, so using
it would hand everyone an extra week of classes that do not exist. This module
supplies the pattern; :mod:`emit` supplies the dates.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

BASE = 'https://collselfsrvprod.rwu.edu'
CATALOG_URL = f'{BASE}/Student/Courses'

#: Identifies the job in RWU's logs. A scraper that cannot be traced back to a
#: person is one that gets blocked rather than emailed about.
USER_AGENT = ('rwu-academic-calendar/1.0 (+https://github.com/arhyneRWU/'
              'rwu-academic-calendar; unofficial, contact via GitHub issues)')

#: One request a second. The catalog is a production student-services system,
#: not a data warehouse; a full term is a few thousand calls and there is no
#: hurry whatsoever, because this runs weekly.
DELAY = 1.0

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')

#: Roger Central prints days as ``M/W/F``. Saturday and Sunday are carried
#: through as-is so the page can say why it cannot use them, rather than
#: silently dropping a weekend section.
DAY_CODES = {'M': 'monday', 'T': 'tuesday', 'W': 'wednesday', 'Th': 'thursday',
             'F': 'friday', 'Sa': 'saturday', 'Su': 'sunday'}


@dataclass(frozen=True)
class Section:
    """One meeting pattern. Five fields and nothing else -- see the module
    docstring for why the other twenty are not here."""
    section: str            # 'BIO.320.01'
    title: str              # 'Ecology'
    days: list[str]         # ['monday', 'wednesday', 'friday']
    start: str              # '14:00', 24-hour, local wall clock
    end: str                # '14:50'
    room: str               # 'College of Arts and Sciences 162', may be ''

    def to_json(self) -> dict:
        return asdict(self)


class Catalog:
    """A session against the catalog: holds the antiforgery token and cookie,
    and paces every request."""

    def __init__(self, delay: float = DELAY, opener=None):
        self.delay = delay
        self._token: Optional[str] = None
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor())
        self._last = 0.0

    # -- plumbing ---------------------------------------------------------
    def _wait(self) -> None:
        gap = self.delay - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()

    def _open(self, req: urllib.request.Request, timeout: int = 45,
              attempts: int = 4) -> bytes:
        """One request, retried on transient failures.

        A full term is a quarter of an hour of requests to a remote host, so a
        dropped connection somewhere in the middle is ordinary rather than
        exceptional -- the first long run died on ``[Errno 60] Operation timed
        out`` at subject six. Backs off rather than hammering, and never
        retries a 4xx, which means the same thing every time.
        """
        req.add_header('User-Agent', USER_AGENT)
        last: Exception | None = None
        for attempt in range(attempts):
            self._wait()
            try:
                with self._opener.open(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    raise
                last = e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
            time.sleep(min(2 ** attempt, 30))
        raise RuntimeError(f'{req.full_url} failed after {attempts} attempts: {last}')

    def connect(self) -> None:
        """Fetch the catalog page for its antiforgery token and cookie.

        Colleague Self-Service rejects every POST without both. They come as a
        pair from one GET, so this is the whole handshake.
        """
        html = self._open(urllib.request.Request(CATALOG_URL)).decode('utf-8', 'replace')
        m = _TOKEN_RE.search(html)
        if not m:
            raise RuntimeError(
                'no __RequestVerificationToken on the catalog page -- Roger '
                'Central has probably been upgraded and this needs rewriting')
        self._token = m.group(1)

    def _post(self, path: str, payload: dict) -> dict:
        if self._token is None:
            self.connect()
        req = urllib.request.Request(
            BASE + path, method='POST',
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json',
                     'X-Requested-With': 'XMLHttpRequest',
                     '__RequestVerificationToken': self._token})
        return json.loads(self._open(req))

    # -- the two calls the catalog actually offers ------------------------
    def facets(self) -> tuple[list[str], list[tuple[str, str, int]]]:
        """Subject codes, and ``(code, label, course_count)`` per term.

        Read from a one-row search rather than the catalog page: the dropdowns
        there are populated by JavaScript, so the served HTML contains no
        options at all. The facets in the search response cover the whole
        catalog regardless of how few rows you asked for.
        """
        d = self._post('/Student/Courses/PostSearchCriteria',
                       {'pageSize': 1, 'pageNumber': 1})
        subjects = sorted(s['Value'] for s in d.get('Subjects') or [])
        terms = sorted(((t['Value'], t.get('Description') or t['Value'], t.get('Count') or 0)
                        for t in d.get('TermFilters') or []),
                       key=lambda t: -t[2])
        return subjects, terms

    def courses(self, subject: str, term: str, page_size: int = 50) -> Iterator[dict]:
        """Every course in a subject for a term, following pagination."""
        page = 1
        while True:
            d = self._post('/Student/Courses/PostSearchCriteria', {
                'subjects': [subject], 'terms': [term],
                'pageSize': page_size, 'pageNumber': page})
            got = d.get('Courses') or []
            yield from got
            total = d.get('TotalPages') or 1
            if page >= total or not got:
                return
            page += 1

    def sections(self, course: dict, term: str) -> list[Section]:
        """Meeting patterns for one course, filtered to one term.

        ``courseId`` is the course's **numeric ``Id``**, which is what the site
        itself sends. The obvious-looking ``SUBJECT_NUMBER`` form -- which the
        catalog view does use -- is accepted for some courses and silently
        returns an empty result for others: ``BIO_101`` works, ``HIST_100``
        gives nothing at all, with no error. A first pass keyed on it collected
        417 meeting patterns and looked entirely successful while dropping most
        of the catalog on the floor.
        """
        ids = course.get('MatchingSectionIds') or []
        if not ids or not course.get('Id'):
            return []
        d = self._post('/Student/Courses/Sections',
                       {'courseId': str(course['Id']), 'sectionIds': ids})
        out = []
        for block in (d.get('SectionsRetrieved') or {}).get('TermsAndSections') or []:
            if (block.get('Term') or {}).get('Code') != term:
                continue
            for entry in block.get('Sections') or []:
                out.extend(_read_section(entry.get('Section') or {}))
        return out


def _hhmm(value) -> str:
    """``'14:00:00'`` or ``'2:00 PM'`` -> ``'14:00'``.

    Read from ``FormattedMeetingTimes``, never from ``Meetings``: the latter's
    ``StartTime`` is an ISO datetime stamped with *today's* date in UTC
    (``2026-08-16T18:00:00+00:00`` for a 2:00 PM class), which is right only by
    accident and wrong across daylight saving.
    """
    if not value:
        return ''
    m = re.match(r'\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$', str(value))
    if m:
        return f'{int(m.group(1)):02d}:{m.group(2)}'
    m = re.match(r'\s*(\d{1,2}):(\d{2})\s*([AaPp])', str(value))
    if not m:
        return ''
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'p' else 0)
    return f'{h:02d}:{m.group(2)}'


def _truthy(v) -> bool:
    """Colleague sends booleans as the strings ``'True'``/``'False'``, which
    are both truthy in Python. That mistake fails open, so it is made once."""
    return str(v).strip().lower() == 'true'


def _days(display: str) -> list[str]:
    """``'M/W/F'`` -> weekday names. Unknown codes are dropped, not guessed."""
    out = []
    for part in re.split(r'[/,]', display or ''):
        name = DAY_CODES.get(part.strip())
        if name and name not in out:
            out.append(name)
    return out


def _read_section(s: dict) -> list[Section]:
    """One :class:`Section` per meeting pattern.

    A section with a lecture and a separately-timed lab yields two, because
    they are two different things in a calendar.
    """
    name = (s.get('SectionNameDisplay') or '').strip()
    title = (s.get('SectionTitleDisplay') or s.get('Title') or '').strip()
    out = []
    for m in s.get('FormattedMeetingTimes') or []:
        if _truthy(m.get('ShowTBD')):
            continue                            # "Meeting Times TBD"
        days = _days(m.get('DaysOfWeekDisplay') or '')
        start, end = _hhmm(m.get('StartTime')), _hhmm(m.get('EndTime'))
        if not (name and days and start and end):
            continue                            # online, async, or unscheduled
        room = ' '.join(str(x).strip() for x in
                        (m.get('BuildingDisplay'), m.get('RoomDisplay')) if x).strip()
        out.append(Section(section=name, title=title, days=days,
                           start=start, end=end, room=room))
    return out


def pull(term: str, subjects: list[str], delay: float = DELAY,
         catalog: Optional[Catalog] = None, progress=None,
         on_subject=None) -> dict[str, list[Section]]:
    """Every section in ``subjects`` for ``term``, keyed by subject.

    ``on_subject(subject, sections)`` fires as each subject finishes, so the
    caller can write incrementally. A full term is ~850 requests over a quarter
    of an hour; a run that only saved at the end would throw away everything on
    a timeout at subject 100.
    """
    cat = catalog or Catalog(delay=delay)
    cat.connect()
    out: dict[str, list[Section]] = {}
    for subject in subjects:
        found: list[Section] = []
        n_courses = 0
        for course in cat.courses(subject, term):
            n_courses += 1
            try:
                found.extend(cat.sections(course, term))
            except (urllib.error.HTTPError, RuntimeError) as e:
                # One unreachable course must not end a fifteen-minute run.
                if progress:
                    progress(f'  ! {subject} {course.get("Number")}: {e}')
        found.sort(key=lambda s: s.section)
        if found:
            out[subject] = found
        if on_subject:
            on_subject(subject, found)
        if progress:
            # A subject with courses but no patterns at all is the shape of a
            # silent lookup failure, not a fact about the timetable. It is how
            # a wrong `courseId` key hid for a whole run: every subject
            # "succeeded" and the total looked plausible. Say it out loud.
            note = ''
            if n_courses and not found:
                note = f'  <-- {n_courses} courses but NO patterns; check the lookup'
            progress(f'  {subject}: {len(found)} meeting patterns '
                     f'from {n_courses} courses{note}')
    return out


def subjects_and_terms() -> tuple[list[str], list[tuple[str, str, int]]]:
    """Convenience wrapper around :meth:`Catalog.facets` for the CLI."""
    return Catalog().facets()


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def term_slug(term: str) -> str:
    """``'26/FA'`` -> ``'26FA'``, because slashes are not filenames."""
    return term.replace('/', '')


def write_dir(term: str, data: dict[str, list[Section]], root: Path,
              retrieved: str | None = None) -> list[Path]:
    """One committed file per subject.

    Committed, like ``data/*.yaml``, so the build never touches the network and
    a broken scrape leaves the last good data serving. One file per subject
    rather than one per term keeps the diffs readable and lets the page load
    only the subject someone picked.
    """
    out = root / term_slug(term)
    out.mkdir(parents=True, exist_ok=True)
    stamp = retrieved or _dt.date.today().isoformat()
    written = []
    for subject, sections in sorted(data.items()):
        p = out / f'{subject}.json'
        p.write_text(json.dumps({
            'unofficial': True,
            'source': CATALOG_URL,
            'term': term,
            'subject': subject,
            'retrieved': stamp,
            'note': ('Meeting patterns only. Instructor names, seat counts and '
                     'enrolment are deliberately not collected.'),
            'sections': [s.to_json() for s in sections],
        }, indent=1, sort_keys=False) + '\n', encoding='utf-8')
        written.append(p)
    return written


#: Our term ids are ``fall-2026``; Roger Central's are ``26/FA``. Summer is
#: absent on purpose: RWU splits it into Summer I and II, which do not line up
#: with the six overlapping sessions our own calendar models.
_RC_SUFFIX = {'fall': 'FA', 'spring': 'SP', 'winter': 'WI'}


def rc_term_slug(term_id: str) -> Optional[str]:
    """``'fall-2026'`` -> ``'26FA'``; ``None`` when there is no clean mapping."""
    m = re.fullmatch(r'([a-z]+)-(\d{4})', term_id or '')
    if not m or m.group(1) not in _RC_SUFFIX:
        return None
    return f'{int(m.group(2)) % 100:02d}{_RC_SUFFIX[m.group(1)]}'


def available(root: Path) -> dict[str, list[str]]:
    """``{'26FA': ['BIO', 'MATH', ...]}`` for whatever has been pulled."""
    out: dict[str, list[str]] = {}
    if not root.exists():
        return out
    for p in sorted(root.glob('*/*.json')):
        if p.name != 'index.json':
            out.setdefault(p.parent.name, []).append(p.stem)
    return out


def load_dir(root: Path) -> dict[str, dict]:
    """Every committed course file, keyed by ``'<termslug>/<SUBJECT>'``."""
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.glob('*/*.json')):
        out[f'{p.parent.name}/{p.stem}'] = json.loads(p.read_text(encoding='utf-8'))
    return out
