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
ACTION_README = ROOT / "pypi" / "README.md"
VERIFY_WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"
EXPECTED_INPUTS = {
    "packages-dir": {"required": "true"},
    "repository-url": {
        "required": "false",
        "default": "https://upload.pypi.org/legacy/",
    },
    "attestations": {"required": "false", "default": "true"},
    "skip-existing": {"required": "false", "default": "false"},
    "verify-metadata": {"required": "false", "default": "true"},
}


def _input_contract(content: str) -> dict[str, dict[str, str]]:
    inputs = content.split("inputs:\n", 1)[1].split("\nruns:\n", 1)[0]
    contract: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in inputs.splitlines():
        input_match = re.fullmatch(r"  ([a-z0-9-]+):", line)
        if input_match:
            current = input_match.group(1)
            contract[current] = {}
            continue
        property_match = re.fullmatch(r"    ([a-z-]+):\s*(.*)", line)
        if current is not None and property_match:
            value = property_match.group(2).strip().strip("'\"")
            contract[current][property_match.group(1)] = value
    return contract


class PublishActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action_content = ACTION.read_text(encoding="utf-8")
        self.action_readme_content = ACTION_README.read_text(encoding="utf-8")
        self.verify_workflow_content = VERIFY_WORKFLOW.read_text(encoding="utf-8")

    def test_public_input_contract_is_exact_and_documented(self) -> None:
        contract = _input_contract(self.action_content)
        self.assertEqual(set(contract), set(EXPECTED_INPUTS))
        for name, expected in EXPECTED_INPUTS.items():
            with self.subTest(input=name):
                self.assertEqual(
                    {
                        key: value
                        for key, value in contract[name].items()
                        if key in {"required", "default"}
                    },
                    expected,
                )
                self.assertTrue(contract[name].get("description"))
        documented = set(
            re.findall(r"^\| `([a-z0-9-]+)` \|", self.action_readme_content, re.M)
        )
        self.assertEqual(documented, set(EXPECTED_INPUTS))
        self.assertNotIn("\noutputs:", self.action_content)
        self.assertIn("The action has no outputs", self.action_readme_content)

    def test_catalog_contains_one_cohesive_runtime_action(self) -> None:
        self.assertEqual(sorted(ROOT.glob("*/action.yml")), [ACTION])
        self.assertEqual(
            sorted(
                path
                for path in (ROOT / "pypi" / "scripts").glob("*")
                if path.is_file()
            ),
            [ROOT / "pypi" / "scripts" / "validate_distributions.py"],
        )
        self.assertFalse(list(ROOT.glob("**/package-lock.json")))
        self.assertFalse(list(ROOT.glob("**/requirements*.txt")))

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
        self.assertNotIn("validate-distributions:", self.action_content)
        validate_step = self.action_content.index(
            "- name: Validate trusted publishing boundary"
        )
        publish_step = self.action_content.index("- name: Publish distributions")
        self.assertLess(validate_step, publish_step)
        validation_block = self.action_content[validate_step:publish_step]
        self.assertNotIn("\n      if:", validation_block)
        self.assertIn(
            'python3 "$GITHUB_ACTION_PATH/scripts/validate_distributions.py"',
            validation_block,
        )
        for fragment in (
            '--repository-url "$REPOSITORY_URL"',
            '--attestations "$ATTESTATIONS"',
            '--skip-existing "$SKIP_EXISTING"',
            '--verify-metadata "$VERIFY_METADATA"',
        ):
            self.assertIn(fragment, validation_block)

    def test_action_is_oidc_only_and_forwards_every_validated_input(self) -> None:
        self.assertNotIn("\n  password:", self.action_content)
        self.assertNotIn("\n  user:", self.action_content)
        publish_block = self.action_content.split(
            "- name: Publish distributions",
            1,
        )[1]
        for name in EXPECTED_INPUTS:
            self.assertIn(f"{name}: ${{{{ inputs.{name} }}}}", publish_block)
        self.assertIn("id-token: write", self.action_readme_content)
        self.assertIn("ubuntu-24.04", self.action_readme_content)
        self.assertIn(
            "does not support being\ninvoked from another composite action",
            self.action_readme_content,
        )
        self.assertIn("protected TestPyPI canary", self.action_readme_content)

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
        self.assertEqual(checkout_shas, [APPROVED_CHECKOUT_SHA] * 4)
        self.assertEqual(
            self.verify_workflow_content.count("persist-credentials: false"),
            len(checkout_shas),
        )
        self.assertIn(
            "python3 -m unittest discover -s tests -v",
            self.verify_workflow_content,
        )
        self.assertEqual(
            self.verify_workflow_content.count("runs-on: ubuntu-24.04"),
            4,
        )
        self.assertIn("ACTION_VALIDATOR_VERSION: 0.9.0", self.verify_workflow_content)
        self.assertIn(
            "ACTION_VALIDATOR_SHA256: "
            "9f42f94fca5b8d04c13bccfbb331104b37a9250650d89ae58dc888d46206f9b9",
            self.verify_workflow_content,
        )
        self.assertIn('"$binary" pypi/action.yml', self.verify_workflow_content)
        self.assertIn("uses: ./pypi", self.verify_workflow_content)
        self.assertIn('[[ "$PREFLIGHT_OUTCOME" == "failure" ]]', self.verify_workflow_content)
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
