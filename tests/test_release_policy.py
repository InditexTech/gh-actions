# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from copy import deepcopy
import unittest

from scripts.release_policy import (
    LEGACY_V1_COMMIT,
    TRUSTED_MINIMUMS,
    validate_release_candidate,
)


TARGET = "f" * 40


def _document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "version": "v2.0.0",
        "mobile_major": "v2",
        "legacy_v1_commit": LEGACY_V1_COMMIT,
        "actions": ["maven-central", "pypi"],
        "minimum_hardened_commits": sorted(TRUSTED_MINIMUMS),
    }


def _validate(
    document: object | None = None,
    **overrides: object,
) -> dict[str, str]:
    arguments = {
        "target_sha": TARGET,
        "checked_out_sha": TARGET,
        "clean": True,
        "workflow_conclusion": "success",
        "workflow_event": "push",
        "workflow_branch": "main",
        "current_actions": ["maven-central", "pypi"],
        "is_ancestor": lambda _minimum, _target: True,
        **overrides,
    }
    return validate_release_candidate(
        _document() if document is None else document,
        **arguments,
    )


class ReleasePolicyTests(unittest.TestCase):
    def test_exact_tested_hardened_main_candidate_passes(self) -> None:
        self.assertEqual(
            _validate(),
            {
                "mobile_major": "v2",
                "target_sha": TARGET,
                "version": "v2.0.0",
            },
        )

    def test_untrusted_execution_context_is_denied(self) -> None:
        cases = (
            {"checked_out_sha": "e" * 40},
            {"clean": False},
            {"workflow_conclusion": "failure"},
            {"workflow_event": "pull_request"},
            {"workflow_branch": "develop"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                _validate(**arguments)

    def test_fabricated_metadata_or_ancestry_is_denied(self) -> None:
        versions = (
            {"version": "main"},
            {"version": "v2.0.0", "mobile_major": "v3"},
            {"actions": ["pypi"]},
            {"legacy_v1_commit": "a" * 40},
            {"minimum_hardened_commits": ["a" * 40]},
        )
        for changes in versions:
            document = deepcopy(_document())
            document.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _validate(document)

        with self.assertRaises(ValueError):
            _validate(is_ancestor=lambda _minimum, _target: False)


if __name__ == "__main__":
    unittest.main()
