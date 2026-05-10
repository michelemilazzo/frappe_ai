#!/usr/bin/env python3
"""Test suite per frappe_ai — eseguire con: python tests/run_tests.py"""

import sys
import os

# Aggiungi il path dell'app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest


# ── Importa i test ──────────────────────────────────────────────

from frappe_ai.frappe_ai.ai_engine.providers.test_opencode_provider import (
    TestOpenCodeProvider,
    TestOpenCodeSyncChat,
)


def run_tests():
    """Esegui tutti i test."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Provider tests
    suite.addTests(loader.loadTestsFromTestCase(TestOpenCodeProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestOpenCodeSyncChat))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit code
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    run_tests()