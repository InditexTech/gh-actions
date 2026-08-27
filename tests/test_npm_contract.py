# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the reusable npm publishing action."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "npm" / "action.yml"
ACTION_README = ROOT / "npm" / "README.md"
EXPECTED_INPUTS = {
    "working-directory": {"required": "true"},
    "project-type": {"required": "true"},
    "artifact-directory": {"required": "true"},
    "dist-tag": {"required": "false", "default": "latest"},
    "registry-url": {
        "required": "false",
        "default": "https://registry.npmjs.org/",
    },
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


class NpmActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action_content = ACTION.read_text(encoding="utf-8")
        self.action_readme_content = ACTION_README.read_text(encoding="utf-8")

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

    def test_defaults_to_the_public_npm_registry(self) -> None:
        self.assertRegex(
            self.action_content,
            r"registry-url:\n"
            r"\s+description:.*\n"
            r"\s+required: false\n"
            r"\s+default: 'https://registry\.npmjs\.org/'",
        )
        self.assertIn(
            "REGISTRY_URL: ${{ inputs.registry-url }}",
            self.action_content,
        )

    def test_validates_before_publishing_with_environment_injected_inputs(self) -> None:
        validate_step = self.action_content.index("- name: Validate npm publish boundary")
        publish_step = self.action_content.index("- name: Publish pre-built tarballs")
        self.assertLess(validate_step, publish_step)
        validation_block = self.action_content[validate_step:publish_step]
        self.assertNotIn("\n      if:", validation_block)
        self.assertIn(
            'python3 "$GITHUB_ACTION_PATH/scripts/validate_npm_publish.py"',
            validation_block,
        )
        for fragment in (
            '--working-directory "$WORKING_DIRECTORY"',
            '--project-type "$PROJECT_TYPE"',
            '--artifact-directory "$ARTIFACT_DIRECTORY"',
            '--dist-tag "$DIST_TAG"',
        ):
            self.assertIn(fragment, validation_block)

    def test_publish_never_re_runs_consumer_lifecycle_or_takes_a_token_input(
        self,
    ) -> None:
        self.assertNotIn("\n  password:", self.action_content)
        self.assertNotIn("\n  token:", self.action_content)
        self.assertNotIn("\n  npm-token:", self.action_content)
        publish_block = self.action_content.split(
            "- name: Publish pre-built tarballs",
            1,
        )[1]
        self.assertIn("npm publish", publish_block)
        self.assertIn("--ignore-scripts", publish_block)
        self.assertIn('--tag "$DIST_TAG"', publish_block)
        # The token, when needed, is read from the ambient job environment (never
        # a composite input) and written only to a temporary npmrc removed on
        # exit.
        self.assertIn("${NPM_TOKEN:-}", publish_block)
        self.assertIn("NPM_CONFIG_USERCONFIG", publish_block)
        self.assertIn("trap 'rm -f \"$npmrc\"' EXIT", publish_block)

    def test_provenance_is_gated_on_public_repository_visibility(self) -> None:
        publish_block = self.action_content.split(
            "- name: Publish pre-built tarballs",
            1,
        )[1]
        self.assertIn(
            "REPOSITORY_VISIBILITY: ${{ github.event.repository.visibility }}",
            publish_block,
        )
        self.assertIn('"$REPOSITORY_VISIBILITY" == "public"', publish_block)
        self.assertIn("provenance=false", publish_block)
        self.assertIn('NPM_CONFIG_PROVENANCE="$provenance"', publish_block)

    def test_readme_documents_the_governed_publish_boundary(self) -> None:
        for fragment in (
            "id-token: write",
            "ubuntu-24.04",
            "--ignore-scripts",
            "only when the repository is public",
            "reviewer-gated publish Environment",
            "protected npm canary",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.action_readme_content)


if __name__ == "__main__":
    unittest.main()
