# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the reusable Maven Central publishing action."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "maven-central" / "action.yml"
ACTION_README = ROOT / "maven-central" / "README.md"
VALIDATE_SCRIPT = ROOT / "maven-central" / "scripts" / "validate_publish.py"
INJECT_SCRIPT = ROOT / "maven-central" / "scripts" / "inject_publish_pom.py"
EXPECTED_INPUTS = {
    "working-directory": {"required": "true"},
    "project-type": {"required": "true"},
    "packages": {"required": "false", "default": ""},
    "strategy": {"required": "false", "default": "maven-central-gpg"},
    "auto-publish": {"required": "false", "default": "true"},
}
# The governed publish mechanism is pinned inside the action (gh-actions owns
# runtime pins), mirroring the profile's plugin-management versions.
GOVERNED_PLUGIN_VERSIONS = {
    "central-publishing-maven-plugin": "0.5.0",
    "maven-gpg-plugin": "3.2.5",
}
REQUIRED_CREDENTIAL_ENV = (
    "MAVEN_CENTRAL_USERNAME",
    "MAVEN_CENTRAL_PASSWORD",
    "CI_GPG_SECRET_KEY",
    "CI_GPG_SECRET_KEY_PASSWORD",
)


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


class MavenCentralContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action_content = ACTION.read_text(encoding="utf-8")
        self.action_readme_content = ACTION_README.read_text(encoding="utf-8")
        self.inject_content = INJECT_SCRIPT.read_text(encoding="utf-8")

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

    def test_action_takes_no_credential_inputs(self) -> None:
        contract = _input_contract(self.action_content)
        for credential in REQUIRED_CREDENTIAL_ENV:
            with self.subTest(credential=credential):
                self.assertNotIn(credential.lower().replace("_", "-"), contract)
        # Credentials arrive through the caller's job environment and are
        # documented as required secrets, not as action inputs.
        for credential in REQUIRED_CREDENTIAL_ENV:
            self.assertIn(credential, self.action_readme_content)

    def test_validates_and_signs_before_publishing(self) -> None:
        validate = self.action_content.index("- name: Validate publish boundary")
        import_key = self.action_content.index("- name: Import signing key")
        publish = self.action_content.index("- name: Publish to Maven Central")
        self.assertLess(validate, import_key)
        self.assertLess(import_key, publish)
        validation_block = self.action_content[validate:import_key]
        self.assertNotIn("\n      if:", validation_block)
        self.assertIn(
            'python3 "$GITHUB_ACTION_PATH/scripts/validate_publish.py"',
            validation_block,
        )
        for fragment in (
            '--working-directory "$WORKING_DIRECTORY"',
            '--project-type "$PROJECT_TYPE"',
            '--strategy "$STRATEGY"',
            '--packages "$PACKAGES"',
            '--auto-publish "$AUTO_PUBLISH"',
        ):
            self.assertIn(fragment, validation_block)

    def test_deploys_the_lifecycle_not_a_standalone_publish_goal(self) -> None:
        # central-publishing binds its upload to the deploy phase via the build
        # extension; the action must run `mvn ... deploy`, never a bare goal.
        self.assertRegex(self.action_content, r"mvn \"\$\{args\[@\]\}\" deploy")
        self.assertNotIn(":publish", self.action_content)

    def test_signing_passphrase_stays_in_the_process_environment(self) -> None:
        self.assertIn(
            'export MAVEN_GPG_PASSPHRASE="$CI_GPG_SECRET_KEY_PASSWORD"',
            self.action_content,
        )

    def test_injector_pins_the_governed_publish_versions(self) -> None:
        for plugin, version in GOVERNED_PLUGIN_VERSIONS.items():
            with self.subTest(plugin=plugin):
                self.assertIn(version, self.inject_content)
        self.assertIn("extensions", self.inject_content)
        self.assertIn("publishingServerId", self.inject_content)

    def test_reserved_oidc_seam_is_documented(self) -> None:
        self.assertIn("oidc", self.action_content)
        self.assertIn("reserved", self.action_readme_content.lower())

    def test_scripts_are_the_only_runtime_files(self) -> None:
        self.assertEqual(
            sorted(
                path
                for path in (ROOT / "maven-central" / "scripts").glob("*")
                if path.is_file()
            ),
            [INJECT_SCRIPT, VALIDATE_SCRIPT],
        )


if __name__ == "__main__":
    unittest.main()
