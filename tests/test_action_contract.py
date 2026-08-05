# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the reusable PyPI publishing action."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


APPROVED_CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "pypi" / "action.yml"
VERIFY_WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"


class PublishActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action_content = ACTION.read_text(encoding="utf-8")
        self.verify_workflow_content = VERIFY_WORKFLOW.read_text(encoding="utf-8")

    def test_uses_an_immutable_upstream_publish_action(self) -> None:
        match = re.search(
            r"uses:\s+pypa/gh-action-pypi-publish@([0-9a-f]{40})\b",
            self.action_content,
        )
        self.assertIsNotNone(match)

    def test_exposes_testpypi_without_weakening_production_default(self) -> None:
        self.assertRegex(
            self.action_content,
            r"repository-url:\n"
            r"\s+description:.*\n"
            r"\s+required: false\n"
            r"\s+default: 'https://upload\.pypi\.org/legacy/'",
        )
        self.assertIn(
            "repository-url: ${{ inputs.repository-url }}",
            self.action_content,
        )

    def test_validates_before_publishing_by_default(self) -> None:
        self.assertIn("validate-distributions:", self.action_content)
        self.assertIn("default: 'true'", self.action_content)
        validate_step = self.action_content.index("- name: Validate distribution input")
        publish_step = self.action_content.index("- name: Publish distributions")
        self.assertLess(validate_step, publish_step)
        self.assertIn(
            'python3 "$GITHUB_ACTION_PATH/scripts/validate_distributions.py"',
            self.action_content,
        )
        self.assertIn('--repository-url "$REPOSITORY_URL"', self.action_content)

    def test_all_external_actions_are_pinned_to_commit_shas(self) -> None:
        for workflow in sorted(ROOT.glob("**/*.yml")):
            for reference in re.findall(r"^\s*uses:\s+([^#\s]+)", workflow.read_text(), re.M):
                if reference.startswith("./"):
                    continue
                owner_repository, separator, revision = reference.partition("@")
                self.assertTrue(separator, f"{workflow}: {reference} has no revision")
                self.assertRegex(
                    revision,
                    r"^[0-9a-f]{40}$",
                    f"{workflow}: {owner_repository} is not pinned to a commit SHA",
                )

    def test_verify_workflow_hardens_checkouts_and_scans_local_catalog_yaml(self) -> None:
        checkout_shas = re.findall(
            r"uses:\s+actions/checkout@([0-9a-f]{40})\b",
            self.verify_workflow_content,
        )
        self.assertEqual(checkout_shas, [APPROVED_CHECKOUT_SHA] * 3)
        self.assertEqual(
            self.verify_workflow_content.count("persist-credentials: false"),
            len(checkout_shas),
        )
        self.assertIn(
            "python3 -m unittest discover -s tests -v",
            self.verify_workflow_content,
        )
        self.assertIn(
            "reviewdog/action-actionlint@50842263c20a7c46bd0065b9e624d3c569db061e",
            self.verify_workflow_content,
        )
        self.assertIn(
            "zizmorcore/zizmor-action@3dc1ecc9bcb9e94e9b2c709687979e1298497054",
            self.verify_workflow_content,
        )
        self.assertIn("inputs: .github/workflows pypi/action.yml", self.verify_workflow_content)
        self.assertIn("collect: workflows,actions", self.verify_workflow_content)
        self.assertIn("persona: pedantic", self.verify_workflow_content)
        self.assertIn("version: 1.29.0", self.verify_workflow_content)
        self.assertIn("online-audits: false", self.verify_workflow_content)
        self.assertIn("advanced-security: false", self.verify_workflow_content)
        self.assertIn("annotations: true", self.verify_workflow_content)


if __name__ == "__main__":
    unittest.main()
