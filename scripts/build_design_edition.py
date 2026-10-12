#!/usr/bin/env python3
"""Compose the design edition while preserving all prior source excerpts.

Reads only this repository's pinned previous commit; never executes upstream code.
The research/decisions files are authoring inputs, not additional main topic notes.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path

BASE = '69577b8d1dc34b052090b43206faa9fcd2c597b2'
PROJECTS = ('codex', 'opencode', 'dsh')
EXCERPT = re.compile(r'<!-- source: (?P<url>https://github\.com/[^\s]+) -->\n```(?P<lang>rust|ts)\n(?P<code>.*?)^```[ \t]*$', re.M | re.S)
DECISION = re.compile(r'^## [^\n]*决策 ([COD]\d{2}-D[12])：([^\n]+)$', re.M)


def h2_sections(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_code = False
    for line in text.splitlines(keepends=True):
        if not in_code and line.startswith('## '):
            if current:
                parts.append(''.join(current))
            current = []
        current.append(line)
        if line.lstrip().startswith('```'):
            in_code = not in_code
    if in_code:
        raise ValueError('unclosed code fence')
    if current:
        parts.append(''.join(current))
    return parts


def demote_headings(text: str) -> str:
    output: list[str] = []
    in_code = False
    for line in text.splitlines(keepends=True):
        if not in_code and re.match(r'^#{2,5} ', line):
            line = '#' + line
        output.append(line)
        if line.lstrip().startswith('```'):
            in_code = not in_code
    return ''.join(output)


def signatures(text: str) -> list[tuple[str, str, str]]:
    return [(m['url'], m['lang'], m['code']) for m in EXCERPT.finditer(text)]


def compose(original: str, design: str, relative: str, pin: str) -> str:
    original = original.replace('\r\n', '\n')
    design = design.replace('\r\n', '\n')
    title, sep, body = design.partition('\n')
    if not title.startswith('# ') or not sep:
        raise ValueError(f'{relative}: missing design title')
    decisions = DECISION.findall(design)
    if len(decisions) != 2:
        raise ValueError(f'{relative}: requires exactly two indexed decisions')
    if len(re.findall(r'[\u4e00-\u9fff]', design)) < 850:
        raise ValueError(f'{relative}: design text is unexpectedly short')
    selected = [part for part in h2_sections(original) if '<!-- source:' in part]
    if not selected or len(signatures(original)) < 2:
        raise ValueError(f'{relative}: missing original source sections')
    sources = '\n\n'.join(demote_headings(part.strip() + '\n').strip() for part in selected)
    definitions = '\n'.join(line for line in original.splitlines() if re.match(r'^\[[^\]]+\]:\s+https?://', line))
    result = (
        title + '\n\n[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)\n\n'
        + f'**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`{pin}`。** '
        + '下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。\n\n'
        + body.strip() + '\n\n## 6. 核心源码与逐段核对\n\n'
        + '以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。\n\n'
        + sources + '\n\n' + definitions + '\n\n## 7. 记录与验证边界\n\n'
        + '源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。'
        + '自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。'
        + f'完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/{BASE}/{relative})。'
        + '源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。\n'
    )
    if signatures(original) != signatures(result):
        raise ValueError(f'{relative}: source excerpt loss, change, or reordering')
    return result


def read_base(root: Path, relative: str) -> str:
    return subprocess.run(['git', 'show', f'{BASE}:{relative}'], cwd=root,
                          check=True, text=True, encoding='utf-8', capture_output=True).stdout


def build(root: Path, check: bool = False) -> dict:
    lock = json.loads((root / 'source-lock.json').read_text(encoding='utf-8'))
    changed: list[str] = []
    index = ['# 48 项设计决策索引\n', '[总目录](README.md) · [证据与方法](RESEARCH_METHOD.md)\n',
             '24 篇主笔记各研究两项决策；编号不是产品能力评分。表中问题均链接到包含源码和论证的主笔记。\n',
             '| 项目 / 专题 | 决策一 | 决策二 |\n|---|---|---|']
    excerpt_count = 0
    decision_count = 0
    for project in lock['repositories']:
        directory = project['notes_directory']
        if directory not in PROJECTS:
            raise ValueError('unexpected project directory')
        for topic in lock['topics']:
            relative = f"{directory}/{topic['id']}-{topic['slug']}.md"
            source = root / 'research/decisions' / relative
            design = source.read_text(encoding='utf-8')
            original = read_base(root, relative)
            rendered = compose(original, design, relative, project['repository'] + '@' + project['commit'])
            decisions = DECISION.findall(design)
            decision_count += len(decisions)
            excerpt_count += len(signatures(rendered))
            index.append(f"| [{directory} {topic['id']}]({relative}) | `{decisions[0][0]}` {decisions[0][1]} | `{decisions[1][0]}` {decisions[1][1]} |")
            destination = root / relative
            if destination.read_text(encoding='utf-8') != rendered:
                changed.append(relative)
                if not check:
                    destination.write_text(rendered, encoding='utf-8')
    if excerpt_count != 70 or decision_count != 48:
        raise ValueError(f'unexpected coverage: {excerpt_count} excerpts / {decision_count} decisions')
    index_text = '\n'.join(index) + '\n'
    target = root / 'DESIGN_INDEX.md'
    if not target.exists() or target.read_text(encoding='utf-8') != index_text:
        changed.append('DESIGN_INDEX.md')
        if not check:
            target.write_text(index_text, encoding='utf-8')
    report = {'status': 'FAIL' if check and changed else 'PASS', 'base_commit': BASE,
              'main_notes': 24, 'indexed_design_decisions': decision_count,
              'preserved_source_excerpts': excerpt_count, 'changed_files': changed,
              'upstream_runtime_tests_run': False,
              'scope': 'Generated-text equality, decision structure, and verbatim excerpt preservation; not argument correctness'}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = build(args.root.resolve(), args.check)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
