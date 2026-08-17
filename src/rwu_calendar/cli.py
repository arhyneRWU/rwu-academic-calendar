"""``rwu-calendar`` — extract, validate, build, and check for drift."""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

from . import courses as courses_mod
from . import emit, serialize, validate
from .extract import SOURCE_URL, extract, fetch

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
COURSES = DATA / 'courses'
PUBLIC = ROOT / 'public'
CACHE = ROOT / 'cache' / 'academic-calendar.html'


def _page(args) -> str:
    if getattr(args, 'cached', False):
        if not CACHE.exists():
            sys.exit(f'no cached page at {CACHE}; run without --cached first')
        return CACHE.read_text(encoding='utf-8')
    html = fetch(args.url)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(html, encoding='utf-8')
    return html


def cmd_extract(args) -> int:
    years = extract(_page(args), retrieved=args.retrieved or _dt.date.today().isoformat(),
                    source_url=args.url)
    written = serialize.write_dir(years, DATA)
    total = sum(len(t.events) for ay in years for t in ay.terms)
    print(f'wrote {len(written)} files to {DATA.relative_to(ROOT)}/ '
          f'({len(years)} academic years, {total} events)')
    for p in written:
        print(f'  {p.name}')
    return 0


def cmd_validate(args) -> int:
    years = serialize.load_dir(DATA)
    problems = validate.run_all(years)
    errs = validate.errors(problems)
    for p in problems:
        print(p, file=sys.stderr if p.level == 'error' else sys.stdout)
    src = len(problems) - len(errs)
    print(f'\n{len(errs)} error(s), {src} source inconsistenc(ies) in RWU\'s own page')
    return 1 if errs else 0


def cmd_build(args) -> int:
    years = serialize.load_dir(DATA)
    if not years:
        sys.exit(f'no data in {DATA}; run `rwu-calendar extract` first')
    errs = validate.errors(validate.run_all(years))
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit('refusing to build with validation errors')
    written = emit.build(years, PUBLIC)
    print(f'wrote {len(written)} files to {PUBLIC.relative_to(ROOT)}/')
    for p in written:
        print(f'  {p.name}  ({p.stat().st_size:,} bytes)')
    return 0


def cmd_drift(args) -> int:
    """Compare the live page against ``data/`` without touching it.

    Run weekly in CI. The scraper is the *check*, not the pipeline — if the
    page changes shape, this fails loudly instead of silently producing wrong
    dates during a build.
    """
    live = extract(fetch(args.url), source_url=args.url)
    have = {(ay.academic_year, t.id, e.date, e.label)
            for ay in serialize.load_dir(DATA) for t in ay.terms for e in t.events}
    now = {(ay.academic_year, t.id, e.date, e.label)
           for ay in live for t in ay.terms for e in t.events}
    added, removed = sorted(now - have), sorted(have - now)
    if not added and not removed:
        print('no drift: the live page matches data/')
        return 0
    print(f'DRIFT: {len(added)} added, {len(removed)} removed\n')
    for tag, rows in (('+', added), ('-', removed)):
        for ay, tid, d, lbl in rows:
            print(f'{tag} {ay} {tid} {d} {lbl}')
    return 2


def cmd_courses(args) -> int:
    """Pull meeting patterns from Roger Central into data/courses/.

    Deliberately manual-by-default and slow: it is a few thousand requests
    against a production student-services system, so it runs weekly in CI and
    otherwise only when someone asks for it.
    """
    subjects, terms = courses_mod.subjects_and_terms()
    if args.list:
        print('terms RWU currently publishes:')
        for code, label, count in terms:
            print(f'  {code}  {label:22s} {count:>5} courses')
        print(f'\n{len(subjects)} subjects: {", ".join(subjects)}')
        return 0

    if not args.term:
        sys.exit('--term is required; run `rwu-calendar courses --list` to see them')
    known = {c for c, _l, _n in terms}
    if args.term not in known:
        sys.exit(f'unknown term {args.term!r}; RWU currently publishes: '
                 f'{", ".join(sorted(known))}')
    want = [s.strip().upper() for s in args.subjects.split(',')] if args.subjects \
        else subjects
    unknown = [s for s in want if s not in subjects]
    if unknown:
        sys.exit(f'unknown subject(s): {", ".join(unknown)}')

    print(f'pulling {args.term} for {len(want)} subject(s) at '
          f'{args.delay}s/request — this is slow on purpose', flush=True)

    written: list[Path] = []

    def save(subject, sections):
        # Write as each subject completes, not at the end: a full term is a
        # quarter of an hour of requests, and a run that saved only on success
        # would discard everything on a timeout near the finish.
        if sections:
            written.extend(courses_mod.write_dir(
                args.term, {subject: sections}, COURSES, retrieved=args.retrieved))

    data = courses_mod.pull(args.term, want, delay=args.delay,
                            progress=lambda m: print(m, flush=True),
                            on_subject=save)
    total = sum(len(v) for v in data.values())
    print(f'\nwrote {len(written)} files, {total} meeting patterns to '
          f'{COURSES.relative_to(ROOT)}/{courses_mod.term_slug(args.term)}/')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='rwu-calendar', description=__doc__)
    ap.add_argument('--url', default=SOURCE_URL)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('extract', help='scrape the page into data/*.yaml')
    p.add_argument('--cached', action='store_true', help='use cache/ instead of the network')
    p.add_argument('--retrieved', help='override the recorded retrieval date (YYYY-MM-DD)')
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser('validate', help='check data/ for structural and source errors')
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser('build', help='emit ICS + JSON into public/')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('drift', help='compare the live page against data/ (exit 2 on drift)')
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser('courses', help='pull course meeting patterns from Roger Central')
    p.add_argument('--term', help="term code, e.g. 26/FA (see --list)")
    p.add_argument('--subjects', help='comma-separated subject codes; default all')
    p.add_argument('--delay', type=float, default=courses_mod.DELAY,
                   help='seconds between requests (default %(default)s)')
    p.add_argument('--retrieved', help='override the recorded date (YYYY-MM-DD)')
    p.add_argument('--list', action='store_true', help='show terms and subjects, pull nothing')
    p.set_defaults(func=cmd_courses)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
