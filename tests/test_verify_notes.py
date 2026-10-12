import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_notes.py'
spec = importlib.util.spec_from_file_location('verify_notes', script)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SHA = 'a' * 40
PINS = {'owner/repo': SHA}


def document(code='  return value\n', sha=SHA, start=2, end=4, kind='source', language='ts'):
    return f'<!-- {kind}: https://github.com/owner/repo/blob/{sha}/src/x.ts#L{start}-L{end} -->\n```{language}\n{code}```\n'


def fixture(root):
    notes = root / 'notes'
    snapshot = root / 'upstream/codex'
    (notes / 'codex').mkdir(parents=True)
    (snapshot / 'src').mkdir(parents=True)
    (notes / 'source-lock.json').write_text(json.dumps({
        'schema_version': 4, 'edition': 'source-reread-readable',
        'repositories': [{'repository': 'owner/repo', 'commit': SHA, 'notes_directory': 'codex'}],
        'topics': [{'id': '01', 'slug': 'topic'}],
    }), encoding='utf-8')
    (notes / 'codex/01-topic.md').write_text('# Note\n\n' + document() * 2, encoding='utf-8')
    (snapshot / '.source-pin.json').write_text(json.dumps({'repository': 'owner/repo', 'commit': SHA}), encoding='utf-8')
    (snapshot / 'src/x.ts').write_text('first\n  return value\nlast\n', encoding='utf-8')
    return notes, snapshot.parent


class VerifierTests(unittest.TestCase):
    def test_book_output_and_dependencies_are_not_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('node_modules/plugin', '_book', '.cache', 'notes'):
                (root / folder).mkdir(parents=True)
                (root / folder / 'page.md').write_text('[失效链接](missing.md)', encoding='utf-8')
            self.assertEqual(module.markdown_files(root), [root / 'notes/page.md'])
            errors = module.check_links(root)
            self.assertEqual(len(errors), 1)
            self.assertIn('notes/page.md', errors[0])

    def test_exact_match_with_indentation(self):
        item = module.parse_excerpts('note.md', document(), PINS)[0]
        self.assertEqual(module.match_excerpt(item, 'first\n  return value\nlast\n'), (2, 2))

    def test_annotations_are_removed_without_changing_code_or_source_line_range(self):
        item = module.parse_excerpts('note.md', document(
            '  // 笔记：读取结果。\n  return value\n  // 笔记：调用方收到返回值。\n',
            kind='annotated-source'), PINS)[0]
        self.assertEqual(item.annotation_lines, 2)
        self.assertEqual(item.kind, 'annotated-source')
        self.assertEqual(module.match_excerpt(item, 'first\n  return value\nlast\n'), (2, 2))
        with self.assertRaises(ValueError):
            module.match_excerpt(item, 'first\n  return other\nlast\n')

    def test_source_marker_cannot_enable_annotation_stripping(self):
        code = '  // 笔记：新增解释。\n  return value\n'
        item = module.parse_excerpts('note.md', document(code), PINS)[0]
        self.assertEqual(item.annotation_lines, 0)
        with self.assertRaises(ValueError):
            module.match_excerpt(item, 'first\n  return value\nlast\n')
        self.assertEqual(module.match_excerpt(item, 'first\n' + code), (2, 3))

    def test_ordinary_comments_inline_comments_and_strings_are_not_removed(self):
        retained = [
            '  // 原有注释\n  return value\n',
            '  return value // 笔记：行尾解释\n',
            '  const text = "// 笔记：字符串"\n',
            '  const text = `\n// 笔记：模板字符串中的内容\n`\n',
            '  /*\n// 笔记：块注释中的内容\n  */\n  return value\n',
        ]
        for code in retained:
            with self.subTest(code=code):
                item = module.parse_excerpts('note.md', document(
                    '// 笔记：唯一新增的教学注释。\n' + code,
                    kind='annotated-source', end=20), PINS)[0]
                self.assertEqual(item.annotation_lines, 1)
                self.assertEqual(module.match_excerpt(item, 'first\n' + code),
                                 (2, 1 + len(code.splitlines())))
                with self.assertRaises(ValueError):
                    module.match_excerpt(item, 'first\n  return value\n')

    def test_rust_raw_strings_and_nested_block_comments_are_not_stripped(self):
        for code in ['let text = r##"\n// 笔记：原始字符串内容\n"##;\n',
                     '/* outer /* inner */\n// 笔记：仍在块注释里\n*/\n']:
            with self.subTest(code=code):
                item = module.parse_excerpts('note.md', document(
                    '// 笔记：新增解释。\n' + code, language='rust', kind='annotated-source', end=20), PINS)[0]
                self.assertEqual(item.annotation_lines, 1)
                self.assertEqual(module.match_excerpt(item, 'first\n' + code), (2, 4))
                with self.assertRaises(ValueError):
                    module.match_excerpt(item, 'first\n' + code.replace('// 笔记：原始字符串内容\n', '').replace(
                        '// 笔记：仍在块注释里\n', ''))

    def test_excerpt_cannot_hide_that_it_starts_inside_a_source_literal(self):
        source = 'const text = `\n// 笔记：这实际是字符串内容\nretained\n`\n'
        item = module.parse_excerpts('note.md', document(
            '// 笔记：这实际是字符串内容\nretained\n', kind='annotated-source'), PINS)[0]
        with self.assertRaisesRegex(ValueError, 'starts inside'):
            module.match_excerpt(item, source)

    def test_empty_malformed_and_annotation_only_blocks_are_rejected(self):
        for code in ['// 笔记：\n  return value\n', '// 笔记：  \t\n  return value\n',
                     '// 笔记: 错误冒号\n  return value\n', '//笔记：缺少空格\n  return value\n',
                     '  return value\n', '// 笔记：只剩说明。\n']:
            with self.subTest(code=code), self.assertRaises(ValueError):
                module.parse_excerpts('note.md', document(code, kind='annotated-source'), PINS)

    def test_annotated_marker_still_requires_pin_range_and_adjacent_fence(self):
        base = document('// 笔记：解释。\n  return value\n', kind='annotated-source')
        for invalid in [base.replace(SHA, 'b' * 40), base.replace('#L2-L4', '#L0-L4'),
                        base.replace('```ts', '```python'), base.replace('annotated-source:', 'annotated-source :')]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                module.parse_excerpts('note.md', invalid, PINS)

    def test_wrong_commit_rejected(self):
        with self.assertRaises(ValueError):
            module.parse_excerpts('note.md', document(sha='b' * 40), PINS)

    def test_modified_code_rejected(self):
        item = module.parse_excerpts('note.md', document(), PINS)[0]
        with self.assertRaises(ValueError):
            module.match_excerpt(item, 'first\n  return other\nlast\n')

    def test_outside_range_rejected(self):
        item = module.parse_excerpts('note.md', document(start=3, end=4), PINS)[0]
        with self.assertRaises(ValueError):
            module.match_excerpt(item, 'first\n  return value\nlast\n')

    def test_unmatched_marker_rejected(self):
        with self.assertRaises(ValueError):
            module.parse_excerpts('note.md', document().replace('```ts', '```python'), PINS)

    def test_unicode_and_crlf(self):
        item = module.parse_excerpts('note.md', document(code="  return '上下文'\n"), PINS)[0]
        self.assertEqual(module.match_excerpt(item, "first\r\n  return '上下文'\r\n"), (2, 2))

    def test_empty_excerpt_rejected(self):
        with self.assertRaises(ValueError):
            module.parse_excerpts('note.md', document(code='\n'), PINS)

    def test_reference_links_and_duplicate_heading_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'target.md').write_text('# 开始\n\n## Same\n\n## Same\n', encoding='utf-8')
            (root / 'index.md').write_text(
                '# 索引\n\n[重复标题][target]\n\n[target]: target.md#same-1\n'
                '\n[自身](#索引)\n\n```ts\n[伪链接](missing.md)\n```\n', encoding='utf-8')
            self.assertEqual(module.check_links(root), [])
            with (root / 'index.md').open('a', encoding='utf-8') as output:
                output.write('\n[坏引用][bad]\n\n[bad]: missing.md\n\n[坏锚点](target.md#gone)\n')
            errors = module.check_links(root)
            self.assertTrue(any('missing local link missing.md' in error for error in errors))
            self.assertTrue(any('missing local anchor target.md#gone' in error for error in errors))

    def test_local_snapshot_exact_match_is_explicitly_labeled(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'read_source', side_effect=AssertionError('network')):
            notes, upstream = fixture(Path(directory))
            report = module.verify(notes, upstream_root=upstream)
            self.assertEqual(report['status'], 'PASS')
            self.assertEqual(report['mode'], 'LOCAL_PINNED_SOURCE')
            self.assertEqual(report['verified_excerpts'], 2)
            self.assertEqual(report['local_snapshot_identities'][0]['identity_method'], 'local_pin_manifest')
            self.assertIn('codex/01-topic.md', report['input_sha256'])

    def test_wrong_local_pin_and_changed_source_cannot_pass(self):
        for kind in ['wrong_pin', 'changed_source', 'missing_source']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                notes, upstream = fixture(Path(directory))
                source = upstream / 'codex/src/x.ts'
                if kind == 'wrong_pin':
                    (upstream / 'codex/.source-pin.json').write_text(
                        json.dumps({'repository': 'owner/repo', 'commit': 'b' * 40}), encoding='utf-8')
                elif kind == 'changed_source':
                    source.write_text('first\n  return other\nlast\n', encoding='utf-8')
                else:
                    source.unlink()
                report = module.verify(notes, upstream_root=upstream)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(report['verified_excerpts'], 0)
                self.assertTrue(report['errors'])

    def test_architecture_excerpts_are_verified_and_reported_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            notes, upstream = fixture(Path(directory))
            architecture = notes / 'codex/00-architecture.md'
            architecture.write_text('# Architecture\n\n' + document(
                '// 笔记：架构入口。\n  return value\n', kind='annotated-source'), encoding='utf-8')
            report = module.verify(notes, upstream_root=upstream)
            self.assertEqual(report['status'], 'PASS')
            self.assertEqual(report['topic_notes'], 1)
            self.assertEqual(report['architecture_notes'], 1)
            self.assertEqual(report['notes'], 2)
            self.assertEqual(report['topic_source_excerpts'], 2)
            self.assertEqual(report['architecture_source_excerpts'], 1)
            self.assertEqual(report['verbatim_source_excerpts'], 2)
            self.assertEqual(report['annotated_source_excerpts'], 1)
            self.assertEqual(report['annotation_lines'], 1)
            self.assertEqual(report['verified_verbatim_excerpts'], 2)
            self.assertEqual(report['verified_annotated_excerpts'], 1)
            self.assertEqual(report['verified_excerpts'], 3)
            self.assertIn('codex/00-architecture.md', report['input_sha256'])
            match = next(item for item in report['matches'] if item['note'] == 'codex/00-architecture.md')
            self.assertEqual(match['comparison'], 'original_lines_after_teaching_comments_removed')
            architecture.write_text(architecture.read_text(encoding='utf-8').replace('return value', 'return other'),
                                    encoding='utf-8')
            failed = module.verify(notes, upstream_root=upstream)
            self.assertEqual(failed['status'], 'FAIL')
            self.assertIn('codex/00-architecture.md', failed['errors'][0])

    def test_architecture_requirement_is_opt_in_and_structure_only_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            notes, upstream = fixture(Path(directory))
            self.assertEqual(module.verify(notes, upstream_root=upstream)['status'], 'PASS')
            lock_path = notes / 'source-lock.json'
            lock = json.loads(lock_path.read_text(encoding='utf-8'))
            lock['architecture_notes'] = 1
            lock_path.write_text(json.dumps(lock), encoding='utf-8')
            report = module.verify(notes, structure_only=True)
            self.assertEqual(report['status'], 'FAIL')
            self.assertTrue(any('architecture coverage' in error for error in report['errors']))
            (notes / 'codex/00-architecture.md').write_text('# Architecture\n\n' + document(
                '// 笔记：解释。\n  return other\n', kind='annotated-source'), encoding='utf-8')
            structure = module.verify(notes, structure_only=True)
            self.assertEqual(structure['status'], 'STRUCTURE_ONLY')
            self.assertEqual(structure['verified_excerpts'], 0)
            self.assertIn('source equality was not checked', structure['scope'])
            self.assertEqual(module.verify(notes, upstream_root=upstream)['status'], 'FAIL')

    def test_online_read_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'read_source', side_effect=OSError('unavailable')):
            notes, _ = fixture(Path(directory))
            report = module.verify(notes)
            self.assertEqual(report['status'], 'FAIL')
            self.assertIn('unavailable', report['errors'][0])

    def test_cli_source_failure_has_nonzero_exit_and_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes, upstream = fixture(root)
            (upstream / 'codex/src/x.ts').unlink()
            report_path = root / 'report.json'
            result = subprocess.run([sys.executable, str(script), '--root', str(notes),
                                     '--upstream-root', str(upstream), '--report', str(report_path)],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(report_path.read_text(encoding='utf-8'))['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
