from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts/build_design_edition.py'
spec = importlib.util.spec_from_file_location('build_design_edition', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SHA = 'a' * 40
CODE = f'<!-- source: https://github.com/o/r/blob/{SHA}/a.ts#L1-L4 -->\n```ts\nconst x = 1\n```\n'


def lesson(prefix='C01', extra_excerpt=False):
    return (
        '# 两个工具，谁先返回？\n\n先看一个具体例子。\n\n'
        f'<!-- decision: {prefix}-D1 | 为什么要等待？ -->\n'
        '## 先完成的工具\n\n这一段解释紧接它的源码。\n\n' + CODE
        + '\n再解释这段源码的结果。\n\n'
        f'<!-- decision: {prefix}-D2 | 等待会积压什么？ -->\n'
        '## 保存结果\n\n第二段代码有自己的解释。\n\n' + CODE
        + ('\n额外例子：\n\n' + CODE if extra_excerpt else '')
    )


def fixture(root):
    lock = {
        'edition': 'source-reread-readable', 'schema_version': 4,
        'repositories': [{'notes_directory': name, 'repository': 'o/r', 'commit': SHA}
                         for name in module.PROJECTS],
        'topics': [{'id': f'{number:02d}', 'slug': 'topic'} for number in range(1, 9)],
    }
    (root / 'source-lock.json').write_text(json.dumps(lock), encoding='utf-8')
    for project, prefix in module.PROJECTS.items():
        for number in range(1, 9):
            target = root / f'research/decisions/{project}/{number:02d}-topic.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(lesson(f'{prefix}{number:02d}', extra_excerpt=number == 1), encoding='utf-8')


class EditionBuilderTests(unittest.TestCase):
    def test_inline_body_is_not_rearranged_or_expanded(self):
        design = lesson(extra_excerpt=True)
        actual = module.compose(design, 'codex/01-agent-loop.md', 'o/r@' + SHA)
        self.assertIn(design.partition('\n')[2].rstrip('\n'), actual)
        self.assertEqual(module.signatures(actual), module.signatures(design))
        self.assertIn('../research/reread/codex-01-04.md', actual)
        self.assertNotIn('核心源码与逐段核对', actual)

    def test_annotated_excerpt_preserves_body_and_marker_identity(self):
        design = lesson().replace('<!-- source:', '<!-- annotated-source:').replace(
            'const x = 1', '// 笔记：这行保留一个值。\nconst x = 1')
        actual = module.compose(design, 'codex/01-agent-loop.md', 'pin')
        self.assertIn(design.partition('\n')[2].rstrip('\n'), actual)
        self.assertEqual(module.signatures(actual), module.signatures(design))
        self.assertEqual({signature[0] for signature in module.signatures(actual)}, {'annotated-source'})
        self.assertIn('[项目架构](00-architecture.md)', actual)
        self.assertIn('其余保留上游原文', actual)
        self.assertNotIn('其余保留上游原文', module.compose(lesson(), 'codex/01-topic.md', 'pin'))

    def test_malformed_or_empty_annotated_blocks_are_rejected(self):
        for code in ['// 笔记：\nconst x = 1', '// 笔记: 解释\nconst x = 1',
                     'const x = 1', '// 笔记：仅有注释']:
            with self.subTest(code=code), self.assertRaises(ValueError):
                design = lesson().replace('<!-- source:', '<!-- annotated-source:').replace('const x = 1', code)
                module.compose(design, 'codex/01-topic.md', 'pin')

    def test_malformed_annotated_marker_cannot_escape_validation(self):
        design = lesson() + '\n<!-- annotated-source: bad -->\n```ts\nconst z = 3\n```\n'
        with self.assertRaisesRegex(ValueError, 'source marker'):
            module.compose(design, 'codex/01-topic.md', 'pin')

    def test_wrong_project_topic_missing_and_duplicate_ids_are_rejected(self):
        for invalid in [lesson('D01'), lesson('C02'), lesson().replace('C01-D2', 'C01-D1'),
                        lesson().replace('<!-- decision: C01-D2 | 等待会积压什么？ -->', '')]:
            with self.subTest(design=invalid[:100]), self.assertRaises(ValueError):
                module.compose(invalid, 'codex/01-agent-loop.md', 'pin')

    def test_metadata_inside_code_does_not_create_a_question(self):
        design = lesson().replace('const x = 1', '<!-- decision: C01-D1 | fake -->', 1)
        self.assertEqual(len(module.decisions_for(design, 'codex/01-agent-loop.md')), 2)

    def test_unclosed_fence_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unclosed'):
            module.compose(lesson() + '\n```ts\nunclosed\n', 'codex/01-agent-loop.md', 'pin')

    def test_build_without_git_history_and_check_detects_main_note_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            report = module.build(root)
            self.assertEqual(report['status'], 'PASS')
            self.assertEqual(report['source_excerpts'], 51)
            self.assertIsNone(report['notes_head'])
            self.assertEqual(module.build(root, check=True)['changed_files'], [])
            target = root / 'dsh/08-topic.md'
            target.write_text(target.read_text(encoding='utf-8') + '\n未生成的修改\n', encoding='utf-8')
            drift = module.build(root, check=True)
            self.assertEqual(drift['status'], 'FAIL')
            self.assertEqual(drift['changed_files'], ['dsh/08-topic.md'])
            self.assertIn('未生成的修改', target.read_text(encoding='utf-8'))

    def test_duplicate_ids_across_different_filenames_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            lock_path = root / 'source-lock.json'
            lock = json.loads(lock_path.read_text(encoding='utf-8'))
            lock['topics'].append({'id': '01', 'slug': 'duplicate'})
            lock_path.write_text(json.dumps(lock), encoding='utf-8')
            duplicate = root / 'research/decisions/codex/01-duplicate.md'
            duplicate.write_text(lesson(), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate decision ID'):
                module.build(root)
            self.assertFalse((root / 'codex').exists())

    def test_architecture_is_counted_and_hashed_but_never_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            architecture = root / 'codex/00-architecture.md'
            architecture.parent.mkdir()
            content = '# Architecture\n\n' + CODE.replace('<!-- source:', '<!-- annotated-source:').replace(
                'const x = 1', '// 笔记：架构入口。\nconst x = 1')
            architecture.write_text(content, encoding='utf-8')
            report = module.build(root)
            self.assertEqual(report['main_notes'], 24)
            self.assertEqual(report['topic_notes'], 24)
            self.assertEqual(report['architecture_notes'], 1)
            self.assertEqual(report['source_excerpts'], 52)
            self.assertEqual(report['topic_source_excerpts'], 51)
            self.assertEqual(report['architecture_source_excerpts'], 1)
            self.assertEqual(report['verbatim_source_excerpts'], 51)
            self.assertEqual(report['annotated_source_excerpts'], 1)
            self.assertEqual(report['annotation_lines'], 1)
            self.assertIn('codex/00-architecture.md', report['input_sha256'])
            self.assertNotIn('codex/00-architecture.md', report['changed_files'])
            self.assertEqual(architecture.read_text(encoding='utf-8'), content)

    def test_declared_architecture_coverage_is_required_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            lock_path = root / 'source-lock.json'
            lock = json.loads(lock_path.read_text(encoding='utf-8'))
            lock['architecture_notes'] = 3
            lock_path.write_text(json.dumps(lock), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'architecture coverage'):
                module.build(root)
            self.assertFalse((root / 'codex').exists())

    def test_failed_cli_writes_failure_report_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            (root / 'research/decisions/codex/01-topic.md').write_text('# Broken\n', encoding='utf-8')
            report = root / 'result.json'
            result = subprocess.run([sys.executable, str(path), '--root', str(root), '--check',
                                     '--report', str(report)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
