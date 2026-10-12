from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts/build_design_edition.py'
spec = importlib.util.spec_from_file_location('build_design_edition', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CODE = '<!-- source: https://github.com/o/r/blob/' + 'a'*40 + '/a.ts#L1-L4 -->\n```ts\nconst x = 1\n```\n'
ORIGINAL = '# Old\n\n## 1. Intro\nold text\n\n## 2. First\n' + CODE + '\n### Explain\nexplanation\n\n## 3. Second\n' + CODE
DESIGN = '# New\n\n## 1. 问题\n' + '研究问题与约束。'*150 + '\n## 2. 决策 C01-D1：输入\ntext\n## 3. 决策 C01-D2：快照\ntext\n'

class EditionBuilderTests(unittest.TestCase):
    def test_preserves_all_source_bytes_and_order(self):
        actual = module.compose(ORIGINAL, DESIGN, 'codex/01-agent-loop.md', 'o/r@' + 'a'*40)
        self.assertEqual(module.signatures(actual), module.signatures(ORIGINAL))
        self.assertLess(actual.index('## 2. 决策'), actual.index('## 6. 核心源码'))
        self.assertIn('explanation', actual)

    def test_does_not_demote_headings_inside_code(self):
        source = '## Outer\n```ts\n## not-a-heading\n```\n### Inner\n'
        expected = '### Outer\n```ts\n## not-a-heading\n```\n#### Inner\n'
        self.assertEqual(module.demote_headings(source), expected)

    def test_missing_decision_rejected(self):
        with self.assertRaises(ValueError):
            module.compose(ORIGINAL, '# Missing\n', 'codex/01.md', 'pin')

    def test_unclosed_fence_rejected(self):
        with self.assertRaises(ValueError):
            module.h2_sections('## Heading\n```ts\nmissing close\n')

if __name__ == '__main__':
    unittest.main()
