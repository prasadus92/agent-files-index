"""Suppress each rule in turn and confirm at least 1 test fails without it. Run: python -m tests.ablate"""
import io
import sys
import unittest

import tests.test_rules as suite
from agentfiles.rules import RULES

original = suite.lint
uncovered = []
for rid in RULES:
    suite.lint = lambda *a, _rid=rid, **k: [f for f in original(*a, **k) if f.id != _rid]
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(suite))
    failed = len(result.failures) + len(result.errors)
    print(f"{rid}: {failed} test(s) fail without it")
    if not failed:
        uncovered.append(rid)
suite.lint = original
print("uncovered:", ", ".join(uncovered) or "none")
sys.exit(1 if uncovered else 0)
