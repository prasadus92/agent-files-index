"""Ablation check: suppress each rule in turn and confirm at least one test fails without it."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agentfiles.rules as rules  # noqa: E402
import tests.test_rules as t  # noqa: E402

original = rules.lint
uncovered = []
for rule in rules.RULES:
    t.lint = lambda *a, _r=rule, **k: [f for f in original(*a, **k) if f.rule != _r]
    suite = unittest.defaultTestLoader.loadTestsFromModule(t)
    result = unittest.TextTestRunner(stream=open("/dev/null", "w"), verbosity=0).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"{rule}: {failed} test(s) fail without it")
    if not failed:
        uncovered.append(rule)
t.lint = original
print("uncovered:", uncovered or "none")
sys.exit(1 if uncovered else 0)
