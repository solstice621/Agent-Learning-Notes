#!/usr/bin/env python3
"""Validate Markdown navigation and verbatim excerpts against pinned public sources.

Only reads upstream source files; never executes upstream code or uses credentials.
Default mode performs online verification. --structure-only explicitly skips it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

MARKER = re.compile(
    r'<!-- source: (?P<url>https://github\.com/[^\s]+) -->\n'
    r'```(?P<language>rust|ts)\n(?P<code>.*?)^```[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
SOURCE_URL = re.compile(
    r'https://github\.com/(?P<repo>[^/]+/[^/]+)/blob/'
    r'(?P<sha>[0-9a-f]{40})/(?P<path>[^#]+)#L(?P<start>[0-9]+)-L(?P<end>[0-9]+)'
)
FENCE = re.compile(r'^```[^\n]*\n.*?^```[ \t]*$', re.MULTILINE | re.DOTALL)
LINK = re.compile(r'\[[^\]\n]+\]\(([^)\n]+)\)')
MAX_SOURCE_BYTES = 5_000_000


@dataclass(frozen=True)
class Excerpt:
    note: str
    number: int
    repo: str
    sha: str
    path: str
    start: int
    end: int
    code: str

    @property
    def raw_url(self) -> str:
        return f'https://raw.githubusercontent.com/{self.repo}/{self.sha}/{quote(self.path, safe="/")}'


def parse_excerpts(note: str, text: str, pins: dict[str, str]) -> list[Excerpt]:
    text = text.replace('\r\n', '\n')
    matches = list(MARKER.finditer(text))
    if len(matches) != text.count('<!-- source:'):
        raise ValueError(f'{note}: a source marker has no adjacent rust/ts code block')
    result: list[Excerpt] = []
    for number, item in enumerate(matches, 1):
        parsed = SOURCE_URL.fullmatch(item['url'])
        if parsed is None:
            raise ValueError(f'{note} #{number}: invalid pinned source URL')
        repo, sha, path = parsed['repo'], parsed['sha'], unquote(parsed['path'])
        if pins.get(repo) != sha:
            raise ValueError(f'{note} #{number}: commit does not match source-lock.json: {sha}')
        if path.startswith('/') or '..' in Path(path).parts:
            raise ValueError(f'{note} #{number}: invalid upstream path')
        start, end = int(parsed['start']), int(parsed['end'])
        if start < 1 or end < start or not item['code'].strip():
            raise ValueError(f'{note} #{number}: invalid range or empty excerpt')
        result.append(Excerpt(note, number, repo, sha, path, start, end, item['code']))
    return result


def match_excerpt(excerpt: Excerpt, source: str) -> tuple[int, int]:
    lines = source.replace('\r\n', '\n').splitlines()
    expected = excerpt.code.replace('\r\n', '\n').splitlines()
    # A locator may include the final source line even when its end exceeds EOF.
    stop = min(excerpt.end, len(lines))
    for offset in range(excerpt.start - 1, stop - len(expected) + 1):
        if lines[offset:offset + len(expected)] == expected:
            return offset + 1, offset + len(expected)
    raise ValueError(
        f'{excerpt.note} #{excerpt.number}: excerpt differs or falls outside '
        f'{excerpt.path}:L{excerpt.start}-L{excerpt.end}'
    )


def read_source(url: str, cache: Path) -> str:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (hashlib.sha256(url.encode()).hexdigest() + '.txt')
    if target.exists():
        return target.read_text(encoding='utf-8')
    request = Request(url, headers={'User-Agent': 'Agent-Learning-Notes-source-verifier'})
    with urlopen(request, timeout=30) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f'upstream source exceeds byte limit: {url}')
    text = data.decode('utf-8')
    target.write_text(text, encoding='utf-8')
    return text


def check_links(root: Path) -> list[str]:
    errors: list[str] = []
    for file in root.rglob('*.md'):
        if any(part.startswith('.') for part in file.relative_to(root).parts):
            continue
        text = FENCE.sub('', file.read_text(encoding='utf-8'))
        for found in LINK.finditer(text):
            link = found[1]
            if '://' in link or link.startswith(('#', 'mailto:')):
                continue
            location = unquote(link.split('#', 1)[0])
            if location and not (file.parent / location).exists():
                errors.append(f'{file.relative_to(root)}: missing local link {link}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--structure-only', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    lock = json.loads((root / 'source-lock.json').read_text(encoding='utf-8'))
    pins = {entry['repository']: entry['commit'] for entry in lock['repositories']}
    errors = check_links(root)
    excerpts: list[Excerpt] = []
    notes = 0
    for project in lock['repositories']:
        for topic in lock['topics']:
            relative = f"{project['notes_directory']}/{topic['id']}-{topic['slug']}.md"
            file = root / relative
            if not file.exists():
                errors.append(f'missing required note: {relative}')
                continue
            notes += 1
            try:
                selected = parse_excerpts(relative, file.read_text(encoding='utf-8'), pins)
                if len(selected) < 2:
                    errors.append(f'{relative}: fewer than two source excerpts')
                excerpts.extend(selected)
            except ValueError as error:
                errors.append(str(error))
    checked: list[dict] = []
    urls = sorted({item.raw_url for item in excerpts})
    if not args.structure_only and not errors:
        sources: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            pending = {pool.submit(read_source, url, root / '.source-cache'): url for url in urls}
            for future in as_completed(pending):
                url = pending[future]
                try:
                    sources[url] = future.result()
                except Exception as error:
                    errors.append(f'cannot verify source {url}: {error}')
        for excerpt in excerpts:
            source = sources.get(excerpt.raw_url)
            if source is None:
                continue
            try:
                first, last = match_excerpt(excerpt, source)
                checked.append({'note': excerpt.note, 'excerpt': excerpt.number,
                                'source': excerpt.raw_url, 'actual_start': first, 'actual_end': last})
            except ValueError as error:
                errors.append(str(error))
    status = 'FAIL' if errors else ('STRUCTURE_ONLY' if args.structure_only else 'PASS')
    report = {'status': status, 'notes': notes, 'excerpts': len(excerpts),
              'upstream_files': len(urls), 'verified_excerpts': len(checked),
              'upstream_agent_tests_run': False, 'errors': errors, 'matches': checked}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{status}: {notes} notes, {len(excerpts)} excerpts, {len(urls)} source files; {len(checked)} exact matches')
    if args.structure_only:
        print('Online source equality was NOT checked.')
    for error in errors:
        print(f'ERROR: {error}', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
