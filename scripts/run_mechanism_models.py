#!/usr/bin/env python3
"""Run independently authored teaching models and write an honest scoped report."""
from __future__ import annotations
import argparse
import json
import unittest
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    suite = unittest.TestLoader().discover(str(root / 'tests'), pattern='test_design_mechanisms.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        'status': 'PASS' if result.wasSuccessful() else 'FAIL',
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'scope': 'Independently authored deterministic mechanism models; NOT upstream Agent tests or performance measurements',
        'upstream_agent_tests_run': False,
        'real_model_calls_run': False,
        'os_sandbox_tests_run': False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
