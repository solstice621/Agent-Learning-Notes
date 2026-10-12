#!/usr/bin/env python3
"""Render readable notes from research/decisions without rearranging their bodies.

The authoring files contain the complete lesson, including inline source excerpts.
This checks generation and indexing, not the correctness of the explanations.
No previous Git revision or upstream execution is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECTS = {'codex': 'C', 'opencode': 'O', 'dsh': 'D'}
EXCERPT = re.compile(
    r'<!-- (?P<kind>source|annotated-source): (?P<url>https://github\.com/[^\s]+) -->\n'
    r'```(?P<lang>rust|ts)\n(?P<code>.*?)^```[ \t]*$', re.M | re.S,
)
DECISION = re.compile(r'^<!-- decision: ([COD]\d{2}-D[12]) \| ([^\n]+?) -->[ \t]*$', re.M)
SOURCE_MARKER = re.compile(r'<!--\s*(?:annotated-source|source)\s*:')
ANNOTATION = re.compile(r'^[ \t]*// 笔记：(?P<text>[^\r\n]*)$')


def code_line_contexts(code: str, language: str) -> list[bool]:
    """Whether each line (plus EOF) starts outside a string or block comment.

    This is deliberately conservative: template interpolation is protected as
    string content too. It is only used to recognize removable teaching lines,
    never to rewrite expressions or claim that the source program is valid.
    """
    contexts: list[bool] = []
    quote: str | None = None
    raw_end: str | None = None
    block_depth = 0
    for line in code.replace('\r\n', '\n').splitlines(keepends=True):
        contexts.append(quote is None and raw_end is None and block_depth == 0)
        index = 0
        while index < len(line):
            if raw_end is not None:
                end = line.find(raw_end, index)
                if end < 0:
                    break
                index, raw_end = end + len(raw_end), None
            elif block_depth:
                if line.startswith('*/', index):
                    block_depth -= 1
                    index += 2
                elif language == 'rust' and line.startswith('/*', index):
                    block_depth += 1
                    index += 2
                else:
                    index += 1
            elif quote is not None:
                if line[index] == '\\':
                    index += 2
                elif line[index] == quote:
                    quote = None
                    index += 1
                else:
                    index += 1
            elif line.startswith('//', index):
                break
            elif line.startswith('/*', index):
                block_depth = 1
                index += 2
            elif language == 'rust' and (raw := re.match(r'(?:br|r)(#*)"', line[index:])):
                raw_end = '"' + raw[1]
                index += raw.end()
            elif line[index] in ('"', '`') or (language == 'ts' and line[index] == "'"):
                quote = line[index]
                index += 1
            elif language == 'rust' and line[index] == "'":
                # Rust lifetimes ('a) are not strings; skip only complete chars.
                char = re.match(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\n])'", line[index:])
                index += char.end() if char else 1
            else:
                index += 1
    contexts.append(quote is None and raw_end is None and block_depth == 0)
    return contexts


def source_code(kind: str, language: str, code: str) -> tuple[str, int]:
    """Remove only explicit, standalone teaching comments from annotated blocks."""
    code = code.replace('\r\n', '\n')
    if not code.strip():
        raise ValueError('empty source excerpt')
    if kind == 'source':
        return code, 0
    if kind != 'annotated-source':
        raise ValueError(f'unsupported source marker: {kind}')
    result: list[str] = []
    count = 0
    for line, in_code in zip(code.splitlines(keepends=True), code_line_contexts(code, language)):
        bare = line.removesuffix('\n')
        annotation = ANNOTATION.fullmatch(bare)
        if in_code and annotation:
            if not annotation['text'].strip():
                raise ValueError('empty teaching annotation: // 笔记： requires text')
            count += 1
            continue
        if in_code and re.match(r'^[ \t]*//[ \t]*笔记', bare):
            raise ValueError('malformed teaching annotation; use a standalone // 笔记：text line')
        result.append(line)
    if not count:
        raise ValueError('annotated-source requires at least one standalone // 笔记：text line')
    original = ''.join(result)
    if not original.strip():
        raise ValueError('annotated-source requires nonempty original code')
    return original, count


def excerpt_stats(text: str, relative: str) -> dict[str, int]:
    matches = list(EXCERPT.finditer(text.replace('\r\n', '\n')))
    if len(matches) != len(SOURCE_MARKER.findall(text)):
        raise ValueError(f'{relative}: a source marker has no adjacent rust/ts code block')
    counts = {'source_excerpts': len(matches), 'verbatim_source_excerpts': 0,
              'annotated_source_excerpts': 0, 'annotation_lines': 0}
    for match in matches:
        try:
            _, count = source_code(match['kind'], match['lang'], match['code'])
        except ValueError as error:
            raise ValueError(f'{relative}: {error}') from error
        counts['annotation_lines'] += count
        counts['annotated_source_excerpts' if match['kind'] == 'annotated-source'
               else 'verbatim_source_excerpts'] += 1
    return counts


def outside_fences(text: str) -> str:
    """Hide fenced content when reading metadata; reject unfinished fences."""
    result: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence is None:
            if marker:
                fence = marker[1]
            else:
                result.append(line)
        elif re.fullmatch(r' {0,3}' + re.escape(fence[0]) + r'{' + str(len(fence)) + r',}[ \t]*\n?', line):
            fence = None
    if fence is not None:
        raise ValueError('unclosed code fence')
    return ''.join(result)


def signatures(text: str) -> list[tuple[str, str, str, str]]:
    return [(m['kind'], m['url'], m['lang'], m['code']) for m in EXCERPT.finditer(text)]


def decisions_for(design: str, relative: str) -> list[tuple[str, str]]:
    path = Path(relative)
    directory, number = path.parent.name, path.name.split('-', 1)[0]
    if directory not in PROJECTS or number not in {f'{n:02d}' for n in range(1, 9)}:
        raise ValueError(f'{relative}: unexpected project or topic number')
    prose = outside_fences(design)
    decisions = DECISION.findall(prose)
    if len(decisions) != prose.count('<!-- decision:'):
        raise ValueError(f'{relative}: malformed decision marker')
    expected = {f'{PROJECTS[directory]}{number}-D1', f'{PROJECTS[directory]}{number}-D2'}
    if len(decisions) != 2 or {item[0] for item in decisions} != expected:
        raise ValueError(f'{relative}: requires exactly {", ".join(sorted(expected))}, with no duplicate IDs')
    if any(not title.strip() for _, title in decisions):
        raise ValueError(f'{relative}: empty indexed question')
    return sorted(decisions)


def compose(design: str, relative: str, pin: str, research_date: str = '') -> str:
    design = design.replace('\r\n', '\n')
    title, sep, body = design.partition('\n')
    if not title.startswith('# ') or not title[2:].strip() or not sep:
        raise ValueError(f'{relative}: missing note title')
    decisions_for(design, relative)
    stats = excerpt_stats(design, relative)
    if stats['source_excerpts'] < 2:
        raise ValueError(f'{relative}: requires at least two nonempty source excerpts')
    project = Path(relative).parent.name
    batch = '01-04' if int(Path(relative).name[:2]) <= 4 else '05-08'
    dated = f'｜研究日期：{research_date}' if research_date else ''
    annotation_notice = ('代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。\n\n'
                         if stats['annotated_source_excerpts'] else '')
    # Keep the body intact: explanations and their excerpts stay together.
    return (
        title + '\n\n[总目录](../README.md) · [先读导览](../START_HERE.md) · '
        '[项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)\n\n'
        + annotation_notice + body.strip('\n') + '\n\n---\n\n'
        + f'固定源码：`{pin}`{dated}。\n\n'
        + f'[源码重读记录](../research/reread/{project}-{batch}.md) · '
        + '[研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)\n'
    )


def notes_head(root: Path) -> str | None:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                              text=True, capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build(root: Path, check: bool = False) -> dict:
    lock_path = root / 'source-lock.json'
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    changed: list[str] = []
    inputs = {'source-lock.json': hashlib.sha256(lock_bytes).hexdigest()}
    index = ['# 48 个问题索引\n', '[总目录](README.md) · [先读导览](START_HERE.md)\n',
             '每篇围绕两个具体问题展开；点击项目与专题，进入例子、解释和相邻的源码。编号只用于定位。\n',
             '| 项目 / 专题 | 问题一 | 问题二 |\n|---|---|---|']
    counts = {'source_excerpts': 0, 'verbatim_source_excerpts': 0,
              'annotated_source_excerpts': 0, 'annotation_lines': 0}
    architecture_notes = 0
    architecture_excerpts = 0
    seen: set[str] = set()
    generated: dict[str, str] = {}
    for project in lock['repositories']:
        directory = project['notes_directory']
        if directory not in PROJECTS:
            raise ValueError(f'unexpected project directory: {directory}')
        # Architecture chapters are hand-authored and never overwritten here.
        architecture = root / directory / '00-architecture.md'
        if architecture.exists():
            architecture_notes += 1
            content = architecture.read_bytes()
            relative = architecture.relative_to(root).as_posix()
            inputs[relative] = hashlib.sha256(content).hexdigest()
            stats = excerpt_stats(content.decode('utf-8'), relative)
            architecture_excerpts += stats['source_excerpts']
            for key in counts:
                counts[key] += stats[key]
        for topic in lock['topics']:
            relative = f"{directory}/{topic['id']}-{topic['slug']}.md"
            if relative in generated:
                raise ValueError(f'duplicate note in source-lock.json: {relative}')
            source = root / 'research/decisions' / relative
            content = source.read_bytes()
            inputs[source.relative_to(root).as_posix()] = hashlib.sha256(content).hexdigest()
            design = content.decode('utf-8')
            rendered = compose(design, relative, project['repository'] + '@' + project['commit'],
                               lock.get('research_date', ''))
            decisions = decisions_for(design, relative)
            for decision, _ in decisions:
                if decision in seen:
                    raise ValueError(f'duplicate decision ID: {decision}')
                seen.add(decision)
            stats = excerpt_stats(rendered, relative)
            for key in counts:
                counts[key] += stats[key]
            cells = [f'`{key}` {title.replace("|", "&#124;")}' for key, title in decisions]
            index.append(f"| [{directory} {topic['id']}]({relative}) | {cells[0]} | {cells[1]} |")
            generated[relative] = rendered
    note_count = len(generated)
    if note_count != 24 or len(seen) != 48:
        raise ValueError(f'unexpected coverage: {note_count} notes / {len(seen)} questions (expected 24 / 48)')
    if 'architecture_notes' in lock and architecture_notes != lock['architecture_notes']:
        raise ValueError(f'unexpected architecture coverage: {architecture_notes} '
                         f"(expected {lock['architecture_notes']})")
    generated['DESIGN_INDEX.md'] = '\n'.join(index) + '\n'
    # Validate every source before modifying any generated file.
    for relative, rendered in generated.items():
        destination = root / relative
        if not destination.exists() or destination.read_text(encoding='utf-8') != rendered:
            changed.append(relative)
            if not check:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(rendered, encoding='utf-8')
    return {
        'status': 'FAIL' if check and changed else 'PASS',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'notes_head': notes_head(root),
        'input_sha256': inputs,
        'input_digest_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        'main_notes': note_count, 'indexed_design_decisions': len(seen),
        'topic_notes': note_count, 'architecture_notes': architecture_notes,
        'topic_source_excerpts': counts['source_excerpts'] - architecture_excerpts,
        'architecture_source_excerpts': architecture_excerpts,
        **counts, 'changed_files': changed,
        'upstream_runtime_tests_run': False,
        'scope': ('Generated-text equality, question IDs and annotation syntax; architecture chapters '
                  'are counted but not generated. Source equality, with only marked teaching comment '
                  'lines removed from annotated-source blocks, is checked separately. '
                  'Neither proves explanation or annotation correctness.'),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = build(args.root.resolve(), args.check)
    except (OSError, ValueError, KeyError) as error:
        result = {'status': 'FAIL', 'errors': [str(error)],
                  'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
