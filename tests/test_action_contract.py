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
MAVEN_CENTRAL_ACTION = ROOT / "maven-central" / "action.yml"
NPM_ACTION = ROOT / "npm" / "action.yml"
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

    def test_catalog_contains_only_the_known_cohesive_runtime_actions(self) -> None:
        # The catalog holds exactly the three governed publishing actions; each
        # keeps only its own runtime scripts and introduces no dependency
        # manifest, so the wrappers stay stdlib-only.
        self.assertEqual(
            sorted(ROOT.glob("*/action.yml")),
            [MAVEN_CENTRAL_ACTION, NPM_ACTION, ACTION],
        )
        self.assertEqual(
            sorted(
                path
                for path in (ROOT / "pypi" / "scripts").glob("*")
                if path.is_file()
            ),
            [ROOT / "pypi" / "scripts" / "validate_distributions.py"],
        )
        self.assertEqual(
            sorted(
                path
                for path in (ROOT / "maven-central" / "scripts").glob("*")
                if path.is_file()
            ),
            [
                ROOT / "maven-central" / "scripts" / "inject_publish_pom.py",
                ROOT / "maven-central" / "scripts" / "validate_publish.py",
            ],
        )
        self.assertEqual(
            sorted(
                path
                for path in (ROOT / "npm" / "scripts").glob("*")
                if path.is_file()
            ),
            [ROOT / "npm" / "scripts" / "validate_npm_publish.py"],
        )
        self.assertFalse(list(ROOT.glob("**/package-lock.json")))
        self.assertFalse(list(ROOT.glob("**/requirements*.txt")))

    def test_exposes_testpypi_without_weakening_production_default(self) -> None:
        self.assertRegex(
            self.action_content,
            r"repository-url:\n"
            r"\s+description:.*\n"
            r"\s+required: false\n"
            r"\s+default: 'https://upload\.pypi\.org/legacy/'",
        )
        # The endpoint is forwarded into the validator environment; the
        # production default is not weakened.
        self.assertIn(
            "REPOSITORY_URL: ${{ inputs.repository-url }}",
            self.action_content,
        )

    def test_validates_distributions_without_an_embedded_publish_step(self) -> None:
        # Publishing is the caller's responsibility: this action only runs the
        # governed boundary validator. It must NOT nest
        # pypa/gh-action-pypi-publish, whose runtime Docker image name mis-cases
        # when generated from inside a composite owned by an uppercase org
        # (InditexTech/gh-actions -> "repository name must be lowercase").
        self.assertNotIn("validate-distributions:", self.action_content)
        # The action may name pypa in prose (to tell the caller what to invoke
        # directly), but it must not nest it as a `uses:` step.
        self.assertIsNone(
            re.search(r"uses:\s*pypa/gh-action-pypi-publish", self.action_content)
        )
        self.assertNotIn("- name: Publish distributions", self.action_content)
        validate_step = self.action_content.index(
            "- name: Validate trusted publishing boundary"
        )
        validation_block = self.action_content[validate_step:]
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

    def test_action_takes_no_credentials_and_validates_every_input(self) -> None:
        self.assertNotIn("\n  password:", self.action_content)
        self.assertNotIn("\n  user:", self.action_content)
        # Every public input is forwarded into the validator environment so the
        # boundary check covers exactly what the caller will hand to pypa.
        env_block = self.action_content.split("env:", 1)[1].split("run:", 1)[0]
        env_names = {
            "packages-dir": "PACKAGES_DIR",
            "repository-url": "REPOSITORY_URL",
            "attestations": "ATTESTATIONS",
            "skip-existing": "SKIP_EXISTING",
            "verify-metadata": "VERIFY_METADATA",
        }
        for name, env_var in env_names.items():
            with self.subTest(input=name):
                self.assertIn(f"{env_var}: ${{{{ inputs.{name} }}}}", env_block)
        # The README documents that publishing runs directly in the caller's
        # job, and why nesting pypa inside this composite is unsafe.
        self.assertIn("id-token: write", self.action_readme_content)
        self.assertIn("ubuntu-24.04", self.action_readme_content)
        self.assertIn("pypa/gh-action-pypi-publish", self.action_readme_content)
        self.assertIn(
            "repository name must be lowercase", self.action_readme_content
        )
        self.assertIn(
            "does not support being invoked from another composite action",
            self.action_readme_content,
        )

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

    def test_every_external_pin_slot_has_exactly_one_dependabot_directory(self) -> None:
        configuration = (ROOT / ".github/dependabot.yml").read_text()
        configured = set(
            re.findall(r"^\s{6}- (/\S*)$", configuration, re.MULTILINE)
        )
        required = {
            f"/{action.parent.relative_to(ROOT).as_posix()}"
            for action in ROOT.glob("*/action.yml")
        }
        for workflow in sorted(ROOT.glob("**/*.yml")):
            relative = workflow.relative_to(ROOT)
            references = re.findall(
                r"^\s*uses:\s+([^#\s]+)",
                workflow.read_text(),
                re.MULTILINE,
            )
            if not any(not reference.startswith("./") for reference in references):
                continue
            required.add(
                "/"
                if relative.parts[:2] == (".github", "workflows")
                else f"/{relative.parts[0]}"
            )

        self.assertEqual(configured, required)

    def test_verify_workflow_hardens_checkouts_and_scans_local_catalog_yaml(self) -> None:
        checkout_shas = re.findall(
            r"uses:\s+actions/checkout@([0-9a-f]{40})\b",
            self.verify_workflow_content,
        )
        self.assertEqual(checkout_shas, [APPROVED_CHECKOUT_SHA] * 6)
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
            6,
        )
        self.assertIn("ACTION_VALIDATOR_VERSION: 0.9.0", self.verify_workflow_content)
        self.assertIn(
            "ACTION_VALIDATOR_SHA256: "
            "9f42f94fca5b8d04c13bccfbb331104b37a9250650d89ae58dc888d46206f9b9",
            self.verify_workflow_content,
        )
        # Every catalog action is syntax-validated and exercised as a
        # fail-closed local preflight.
        self.assertIn('"$binary" maven-central/action.yml', self.verify_workflow_content)
        self.assertIn('"$binary" npm/action.yml', self.verify_workflow_content)
        self.assertIn('"$binary" pypi/action.yml', self.verify_workflow_content)
        self.assertIn("uses: ./pypi", self.verify_workflow_content)
        self.assertIn("uses: ./maven-central", self.verify_workflow_content)
        self.assertIn("uses: ./npm", self.verify_workflow_content)
        self.assertEqual(
            self.verify_workflow_content.count('[[ "$PREFLIGHT_OUTCOME" == "failure" ]]'),
            3,
        )
        self.assertIn(
            "reviewdog/action-actionlint@50842263c20a7c46bd0065b9e624d3c569db061e",
            self.verify_workflow_content,
        )
        self.assertIn(
            "zizmorcore/zizmor-action@3dc1ecc9bcb9e94e9b2c709687979e1298497054",
            self.verify_workflow_content,
        )
        self.assertIn(
            "inputs: .github/workflows maven-central/action.yml "
            "npm/action.yml pypi/action.yml",
            self.verify_workflow_content,
        )
        self.assertIn("collect: workflows,actions", self.verify_workflow_content)
        self.assertIn("persona: pedantic", self.verify_workflow_content)
        self.assertIn("version: 1.29.0", self.verify_workflow_content)
        self.assertIn("online-audits: false", self.verify_workflow_content)
        self.assertIn("advanced-security: false", self.verify_workflow_content)
        self.assertIn("annotations: true", self.verify_workflow_content)


if __name__ == "__main__":
    unittest.main()
