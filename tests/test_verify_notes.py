import importlib.util
import sys
import unittest
from pathlib import Path

script = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_notes.py'
spec = importlib.util.spec_from_file_location('verify_notes', script)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SHA = 'a' * 40
PINS = {'owner/repo': SHA}


def document(code='  return value\n', sha=SHA, start=2, end=4):
    return f'<!-- source: https://github.com/owner/repo/blob/{sha}/src/x.ts#L{start}-L{end} -->\n```ts\n{code}```\n'


class VerifierTests(unittest.TestCase):
    def test_exact_match_with_indentation(self):
        item = module.parse_excerpts('note.md', document(), PINS)[0]
        self.assertEqual(module.match_excerpt(item, 'first\n  return value\nlast\n'), (2, 2))

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


if __name__ == '__main__':
    unittest.main()
