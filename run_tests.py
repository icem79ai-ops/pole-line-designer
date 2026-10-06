# -*- coding: utf-8 -*-
"""run_tests.py - run the whole test suite.

    python run_tests.py
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(ROOT, "tests"), pattern="test_*.py", top_level_dir=ROOT)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("=" * 70)
    print(f"รวม {result.testsRun} เคส | ผ่าน {result.testsRun - len(result.failures) - len(result.errors)}"
          f" | ไม่ผ่าน {len(result.failures)} | ผิดพลาด {len(result.errors)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
