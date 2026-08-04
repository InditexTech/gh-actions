# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the reusable PyPI publishing action."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "pypi" / "action.yml"
TESTPYPI_SMOKE = ROOT / ".github" / "workflows" / "testpypi-smoke.yml"


class PublishActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = ACTION.read_text(encoding="utf-8")

    def test_uses_an_immutable_upstream_publish_action(self) -> None:
        match = re.search(
            r"uses:\s+pypa/gh-action-pypi-publish@([0-9a-f]{40})\b",
            self.content,
        )
        self.assertIsNotNone(match)

    def test_exposes_testpypi_without_weakening_production_default(self) -> None:
        self.assertRegex(
            self.content,
            r"repository-url:\n"
            r"\s+description:.*\n"
            r"\s+required: false\n"
            r"\s+default: 'https://upload\.pypi\.org/legacy/'",
        )
        self.assertIn("repository-url: ${{ inputs.repository-url }}", self.content)

    def test_validates_before_publishing_by_default(self) -> None:
        self.assertIn("validate-distributions:", self.content)
        self.assertIn("default: 'true'", self.content)
        validate_step = self.content.index("- name: Validate distribution input")
        publish_step = self.content.index("- name: Publish distributions")
        self.assertLess(validate_step, publish_step)
        self.assertIn(
            'python3 "$GITHUB_ACTION_PATH/scripts/validate_distributions.py"',
            self.content,
        )
        self.assertIn('--repository-url "$REPOSITORY_URL"', self.content)

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

    def test_testpypi_build_is_unprivileged_and_publish_is_isolated(self) -> None:
        content = TESTPYPI_SMOKE.read_text(encoding="utf-8")
        build_job, publish_job = re.split(r"\n  publish:\n", content, maxsplit=1)

        self.assertIn("\n  build:\n", build_job)
        self.assertIn("github.repository_owner == 'InditexTech'", build_job)
        self.assertNotIn("id-token:", build_job)
        self.assertIn("needs: build", publish_job)
        self.assertIn("environment: testpypi", publish_job)
        self.assertIn("id-token: write", publish_job)
        self.assertIn("actions/upload-artifact@", build_job)
        self.assertIn("actions/download-artifact@", publish_job)

    def test_testpypi_smoke_versions_are_unique_on_rerun(self) -> None:
        content = TESTPYPI_SMOKE.read_text(encoding="utf-8")
        self.assertIn("0.0.${GITHUB_RUN_NUMBER}.post${GITHUB_RUN_ATTEMPT}", content)


if __name__ == "__main__":
    unittest.main()
