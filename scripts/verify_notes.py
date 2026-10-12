#!/usr/bin/env python3
"""Validate links and original/annotated excerpts against pinned source files.

Default: fetch pinned public files (or reuse their URL-keyed cache).
--upstream-root: read local codex/opencode/dsh snapshots with pin metadata.
--structure-only: explicitly skip source equality. Never execute upstream code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

try:  # Direct CLI execution and import via the repository's test suite.
    from build_design_edition import EXCERPT as MARKER, SOURCE_MARKER, code_line_contexts, source_code
except ModuleNotFoundError:
    from scripts.build_design_edition import EXCERPT as MARKER, SOURCE_MARKER, code_line_contexts, source_code
SOURCE_URL = re.compile(
    r'https://github\.com/(?P<repo>[^/]+/[^/]+)/blob/'
    r'(?P<sha>[0-9a-f]{40})/(?P<path>[^#]+)#L(?P<start>[0-9]+)-L(?P<end>[0-9]+)'
)
LINK = re.compile(r'\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))(?:\s+["\'][^\n]*?["\'])?\s*\)')
REFERENCE = re.compile(r'^ {0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|(\S+))', re.M)
REFERENCE_USE = re.compile(r'\[([^\]\n]+)\]\[([^\]\n]*)\]')
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
    kind: str = 'source'
    language: str = 'ts'
    annotation_lines: int = 0

    @property
    def raw_url(self) -> str:
        return f'https://raw.githubusercontent.com/{self.repo}/{self.sha}/{quote(self.path, safe="/")}'


def parse_excerpts(note: str, text: str, pins: dict[str, str]) -> list[Excerpt]:
    text = text.replace('\r\n', '\n')
    matches = list(MARKER.finditer(text))
    if len(matches) != len(SOURCE_MARKER.findall(text)):
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
        try:
            _, annotations = source_code(item['kind'], item['lang'], item['code'])
        except ValueError as error:
            raise ValueError(f'{note} #{number}: {error}') from error
        result.append(Excerpt(note, number, repo, sha, path, start, end, item['code'],
                              item['kind'], item['lang'], annotations))
    return result


def match_excerpt(excerpt: Excerpt, source: str) -> tuple[int, int]:
    lines = source.replace('\r\n', '\n').splitlines()
    original, _ = source_code(excerpt.kind, excerpt.language, excerpt.code)
    expected = original.splitlines()
    # A locator may include the final source line even when its end exceeds EOF.
    stop = min(excerpt.end, len(lines))
    for offset in range(excerpt.start - 1, stop - len(expected) + 1):
        if lines[offset:offset + len(expected)] == expected:
            # An excerpt may start halfway through a literal in its source file.
            # Refuse annotation stripping there instead of guessing its context.
            if excerpt.kind == 'annotated-source' and not code_line_contexts(source, excerpt.language)[offset]:
                raise ValueError(f'{excerpt.note} #{excerpt.number}: annotated excerpt starts inside '
                                 'a source string or block comment; include its opening context')
            return offset + 1, offset + len(expected)
    raise ValueError(
        f'{excerpt.note} #{excerpt.number}: excerpt differs or falls outside '
        f'{excerpt.path}:L{excerpt.start}-L{excerpt.end}'
    )


def read_source(url: str, cache: Path) -> str:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (hashlib.sha256(url.encode()).hexdigest() + '.txt')
    if target.exists():
        return target.read_bytes().decode('utf-8')
    request = Request(url, headers={'User-Agent': 'Agent-Learning-Notes-source-verifier'})
    with urlopen(request, timeout=30) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f'upstream source exceeds byte limit: {url}')
    text = data.decode('utf-8')
    target.write_bytes(data)
    return text


def local_identity(directory: Path, repository: str, commit: str) -> dict:
    """Check declared snapshot identity; excerpt matching still reads actual files."""
    if (directory / '.git').exists():
        actual = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=directory, check=True,
                                text=True, capture_output=True).stdout.strip()
        method = 'git_head'
    else:
        marker = directory / '.source-pin.json'
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        if metadata.get('repository') != repository:
            raise ValueError(f'{marker}: repository does not match {repository}')
        actual = metadata.get('commit')
        method = 'local_pin_manifest'
    if actual != commit:
        raise ValueError(f'{directory}: local commit {actual} does not match pinned {commit}')
    return {'repository': repository, 'commit': actual, 'identity_method': method}


def read_local_source(directory: Path, source_path: str) -> str:
    target = (directory / source_path).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise ValueError(f'upstream path escapes snapshot: {source_path}')
    with target.open('rb') as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f'upstream source exceeds byte limit: {target}')
    return data.decode('utf-8')


def without_fences(text: str) -> str:
    result: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence is None:
            if marker:
                fence = marker[1]
                result.append('\n')
            else:
                result.append(line)
        elif re.fullmatch(r' {0,3}' + re.escape(fence[0]) + r'{' + str(len(fence)) + r',}[ \t]*\n?', line):
            fence = None
            result.append('\n')
    return ''.join(result)


def heading_anchors(text: str) -> set[str]:
    """Recognize ordinary GitHub Markdown heading IDs and explicit HTML anchors."""
    prose = without_fences(text)
    anchors = set(re.findall(r'<[^>]+\b(?:id|name)=["\']([^"\']+)["\']', prose))
    used: set[str] = set()
    lines = prose.splitlines()
    for index, line in enumerate(lines):
        found = re.match(r'^ {0,3}#{1,6}[ \t]+(.+?)\s*$', line)
        if found:
            title = re.sub(r'[ \t]+#+[ \t]*$', '', found[1])
        elif index and re.fullmatch(r' {0,3}(?:=+|-+)[ \t]*', line) and lines[index - 1].strip():
            title = lines[index - 1].strip()
        else:
            continue
        title = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', title)
        title = re.sub(r'<[^>]+>', '', title)
        slug = re.sub(r'[^\w\-\s]', '', title.lower())
        slug = re.sub(r'\s', '-', slug)
        anchor, suffix = slug, 0
        while anchor in used:
            suffix += 1
            anchor = f'{slug}-{suffix}'
        used.add(anchor)
        anchors.add(anchor)
    return anchors


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory, children, names in os.walk(root):
        children[:] = [name for name in children
                       if not name.startswith('.') and name not in {'node_modules', '_book'}]
        files.extend(Path(directory) / name for name in names
                     if name.endswith('.md') and not name.startswith('.'))
    return sorted(files)


def check_links(root: Path) -> list[str]:
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for file in markdown_files(root):
        relative = file.relative_to(root)
        text = without_fences(file.read_text(encoding='utf-8'))
        text = re.sub(r'(`+)[^\n]*?\1', '', text)
        definitions = {re.sub(r'\s+', ' ', m[1]).strip().casefold(): m[2] or m[3]
                       for m in REFERENCE.finditer(text)}
        links = [found[1] or found[2] for found in LINK.finditer(text)] + list(definitions.values())
        for found in REFERENCE_USE.finditer(text):
            label = re.sub(r'\s+', ' ', found[2] or found[1]).strip().casefold()
            if label not in definitions:
                errors.append(f'{relative}: undefined link reference [{label}]')
        # Authoring bodies are published unchanged in the project directories.
        base = root / Path(*relative.parts[2:]) if relative.parts[:2] == ('research', 'decisions') else file
        for link in links:
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', link) or link.startswith('//'):
                continue
            location, _, fragment = link.partition('#')
            location = unquote(location.split('?', 1)[0])
            target = ((root / location.lstrip('/')) if location.startswith('/') else
                      (base.parent / location)) if location else base
            target = target.resolve()
            if not target.exists():
                errors.append(f'{relative}: missing local link {link}')
                continue
            if fragment and target.suffix.lower() == '.md' and not re.fullmatch(r'L\d+(?:-L\d+)?', fragment):
                if target not in anchor_cache:
                    anchor_cache[target] = heading_anchors(target.read_text(encoding='utf-8'))
                if unquote(fragment) not in anchor_cache[target]:
                    errors.append(f'{relative}: missing local anchor {link}')
    return errors


def notes_head(root: Path) -> str | None:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def verify(root: Path, structure_only: bool = False, upstream_root: Path | None = None) -> dict:
    if structure_only and upstream_root is not None:
        raise ValueError('--structure-only and --upstream-root are mutually exclusive')
    lock = json.loads((root / 'source-lock.json').read_text(encoding='utf-8'))
    pins = {entry['repository']: entry['commit'] for entry in lock['repositories']}
    mode = 'STRUCTURE_ONLY' if structure_only else ('LOCAL_PINNED_SOURCE' if upstream_root else 'ONLINE_PINNED_SOURCE')
    errors = check_links(root)
    excerpts: list[Excerpt] = []
    topic_notes = 0
    architecture_notes = 0
    architecture_excerpts = 0
    for project in lock['repositories']:
        architecture = f"{project['notes_directory']}/00-architecture.md"
        file = root / architecture
        if file.exists():
            architecture_notes += 1
            try:
                selected = parse_excerpts(architecture, file.read_text(encoding='utf-8'), pins)
                architecture_excerpts += len(selected)
                excerpts.extend(selected)
            except ValueError as error:
                errors.append(str(error))
        for topic in lock['topics']:
            relative = f"{project['notes_directory']}/{topic['id']}-{topic['slug']}.md"
            file = root / relative
            if not file.exists():
                errors.append(f'missing required note: {relative}')
                continue
            topic_notes += 1
            try:
                selected = parse_excerpts(relative, file.read_text(encoding='utf-8'), pins)
                if len(selected) < 2:
                    errors.append(f'{relative}: fewer than two source excerpts')
                excerpts.extend(selected)
            except ValueError as error:
                errors.append(str(error))
    if 'architecture_notes' in lock and architecture_notes != lock['architecture_notes']:
        errors.append(f'unexpected architecture coverage: {architecture_notes} '
                      f"(expected {lock['architecture_notes']})")
    checked: list[dict] = []
    unique_sources = {item.raw_url: item for item in excerpts}
    sources: dict[str, str] = {}
    identities: list[dict] = []
    if upstream_root is not None:
        local_roots: dict[str, Path] = {}
        for project in lock['repositories']:
            directory = upstream_root / project['notes_directory']
            try:
                identities.append(local_identity(directory, project['repository'], project['commit']))
                local_roots[project['repository']] = directory
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                errors.append(f'cannot verify local snapshot identity: {error}')
        for url, excerpt in unique_sources.items():
            if excerpt.repo not in local_roots:
                continue
            try:
                sources[url] = read_local_source(local_roots[excerpt.repo], excerpt.path)
            except (OSError, ValueError) as error:
                errors.append(f'cannot read local source {excerpt.repo}/{excerpt.path}: {error}')
    elif not structure_only:
        with ThreadPoolExecutor(max_workers=6) as pool:
            pending = {pool.submit(read_source, url, root / '.source-cache'): url for url in unique_sources}
            for future in as_completed(pending):
                url = pending[future]
                try:
                    sources[url] = future.result()
                except Exception as error:
                    errors.append(f'cannot verify source {url}: {error}')
    if not structure_only:
        for excerpt in excerpts:
            source = sources.get(excerpt.raw_url)
            if source is None:
                continue
            try:
                first, last = match_excerpt(excerpt, source)
                checked.append({'note': excerpt.note, 'excerpt': excerpt.number,
                                'source': excerpt.raw_url, 'actual_start': first, 'actual_end': last,
                                'kind': excerpt.kind, 'annotation_lines': excerpt.annotation_lines,
                                'comparison': ('verbatim' if excerpt.kind == 'source'
                                               else 'original_lines_after_teaching_comments_removed')})
            except ValueError as error:
                errors.append(str(error))
        if len(checked) != len(excerpts) and not errors:
            errors.append('source verification was incomplete')
    inputs = {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
              for file in [root / 'source-lock.json', *markdown_files(root)]}
    return {
        'status': 'FAIL' if errors else ('STRUCTURE_ONLY' if structure_only else 'PASS'),
        'mode': mode, 'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'notes_head': notes_head(root), 'input_sha256': inputs,
        'input_digest_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        'notes': topic_notes + architecture_notes, 'topic_notes': topic_notes,
        'architecture_notes': architecture_notes,
        'excerpts': len(excerpts), 'upstream_files': len(unique_sources),
        'topic_source_excerpts': len(excerpts) - architecture_excerpts,
        'architecture_source_excerpts': architecture_excerpts,
        'verbatim_source_excerpts': sum(item.kind == 'source' for item in excerpts),
        'annotated_source_excerpts': sum(item.kind == 'annotated-source' for item in excerpts),
        'annotation_lines': sum(item.annotation_lines for item in excerpts),
        'verified_excerpts': len(checked), 'local_snapshot_identities': identities,
        'verified_verbatim_excerpts': sum(item['kind'] == 'source' for item in checked),
        'verified_annotated_excerpts': sum(item['kind'] == 'annotated-source' for item in checked),
        'source_files_sha256': {url: hashlib.sha256(value.encode('utf-8')).hexdigest()
                                for url, value in sorted(sources.items())},
        'upstream_agent_tests_run': False, 'errors': errors, 'matches': checked,
        'scope': (('Local file equality; snapshot identity comes from Git HEAD or local .source-pin.json, '
                   'not a fresh remote verification. ' if upstream_root else
                   'Markdown links and pinned source equality (fetched or cached). ')
                  + 'Source blocks match verbatim; annotated-source blocks match after removing only '
                  'standalone // 笔记： teaching comments. No upstream execution, explanation or '
                  'annotation correctness validation.' if not structure_only else
                  'Markdown links, source markers and annotation syntax only; source equality was not checked.'),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    source_mode = parser.add_mutually_exclusive_group()
    source_mode.add_argument('--structure-only', action='store_true')
    source_mode.add_argument('--upstream-root', type=Path,
                             help='Parent of local codex/opencode/dsh snapshots, each with .source-pin.json or .git')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.root.resolve(), args.structure_only,
                        args.upstream_root.resolve() if args.upstream_root else None)
    except (OSError, ValueError, KeyError) as error:
        report = {'status': 'FAIL', 'errors': [str(error)],
                  'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{report['status']} ({report.get('mode', 'setup failed')}): "
          f"{report.get('topic_notes', 0)} topic notes + {report.get('architecture_notes', 0)} architecture notes; "
          f"{report.get('excerpts', 0)} excerpts "
          f"({report.get('verbatim_source_excerpts', 0)} verbatim, "
          f"{report.get('annotated_source_excerpts', 0)} annotated, "
          f"{report.get('annotation_lines', 0)} teaching comment lines); "
          f"{report.get('upstream_files', 0)} source files; "
          f"{report.get('verified_excerpts', 0)} original-code matches")
    if args.structure_only:
        print('Source equality was NOT checked.')
    for error in report['errors']:
        print(f'ERROR: {error}', file=sys.stderr)
    return 1 if report['status'] == 'FAIL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
