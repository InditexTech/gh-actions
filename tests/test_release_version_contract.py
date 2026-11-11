# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the release-version composite action."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "release-version" / "action.yml"
SCRIPT = "release-version/scripts/release_version.py"
VERIFY_WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"
CATALOG_README = ROOT / "README.md"

EXPECTED_INPUTS = {
    "release-type": {"required": "true"},
    "tag-format": {"required": "true"},
    "strategy": {"required": "true"},
    "packages": {"required": "true"},
    "dev-suffix": {"required": "false", "default": ""},
}
EXPECTED_ENV = {
    "release-type": "RELEASE_TYPE",
    "tag-format": "TAG_FORMAT",
    "strategy": "STRATEGY",
    "packages": "PACKAGES",
    "dev-suffix": "DEV_SUFFIX",
}
EXPECTED_OUTPUTS = ("releases", "version", "tag")


def _block(content: str, start: str, end: str) -> str:
    return content.split(f"\n{start}:\n", 1)[1].split(f"\n{end}:\n", 1)[0]


def _contract(block: str) -> dict[str, dict[str, str]]:
    contract: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in block.splitlines():
        name_match = re.fullmatch(r"  ([a-z0-9-]+):", line)
        if name_match:
            current = name_match.group(1)
            contract[current] = {}
            continue
        property_match = re.fullmatch(r"    ([a-z-]+):\s*(.*)", line)
        if current is not None and property_match:
            value = property_match.group(2).strip().strip("'\"")
            contract[current][property_match.group(1)] = value
    return contract


def _zizmor_inputs(workflow: str) -> list[str]:
    match = re.search(r"^\s+inputs: (.+)$", workflow, re.MULTILINE)
    assert match is not None, "zizmor step has no inputs line"
    return match.group(1).split()


class ReleaseVersionActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = ACTION.read_text(encoding="utf-8")
        self.verify_content = VERIFY_WORKFLOW.read_text(encoding="utf-8")
        self.readme_content = CATALOG_README.read_text(encoding="utf-8")

    def test_metadata_is_licensed_named_and_described(self) -> None:
        self.assertTrue(self.content.startswith("# SPDX-FileCopyrightText: 2026 "))
        self.assertIn("# SPDX-License-Identifier: Apache-2.0\n", self.content)
        self.assertRegex(self.content, r"(?m)^name: \S.*$")
        self.assertRegex(self.content, r"(?m)^description: \S")

    def test_public_input_contract_is_exact(self) -> None:
        contract = _contract(_block(self.content, "inputs", "outputs"))
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

    def test_output_contract_is_exact_and_bound_to_the_compute_step(self) -> None:
        contract = _contract(_block(self.content, "outputs", "runs"))
        self.assertEqual(set(contract), set(EXPECTED_OUTPUTS))
        for name in EXPECTED_OUTPUTS:
            with self.subTest(output=name):
                self.assertTrue(contract[name].get("description"))
                self.assertEqual(
                    contract[name].get("value"),
                    f"${{{{ steps.compute.outputs.{name} }}}}",
                )
        self.assertEqual(len(re.findall(r"(?m)^\s+id: compute$", self.content)), 1)

    def test_is_a_single_step_composite_with_no_external_uses(self) -> None:
        runs = self.content.split("\nruns:\n", 1)[1]
        self.assertIn("  using: composite\n", runs)
        self.assertEqual(len(re.findall(r"(?m)^    - name: ", runs)), 1)
        self.assertNotIn("uses:", self.content)

    def test_inputs_reach_the_script_only_through_env(self) -> None:
        runs = self.content.split("\nruns:\n", 1)[1]
        env_block = runs.split("      env:\n", 1)[1].split("      run:", 1)[0]
        run_block = runs.split("      run:", 1)[1]
        for name, variable in EXPECTED_ENV.items():
            with self.subTest(input=name):
                self.assertIn(
                    f"        {variable}: ${{{{ inputs.{name} }}}}\n", env_block
                )
                self.assertIn(f'"--{name}=${variable}"', run_block)
        self.assertNotIn("${{", run_block)
        self.assertIn(
            'python3 "$GITHUB_ACTION_PATH/scripts/release_version.py"', run_block
        )

    def test_verify_workflow_validates_compiles_and_audits_the_action(self) -> None:
        self.assertIn('"$binary" release-version/action.yml', self.verify_content)
        compile_block = self.verify_content.split("python3 -m py_compile", 1)[1]
        compile_block = compile_block.split("python3 -m unittest", 1)[0]
        self.assertIn(SCRIPT, compile_block)
        self.assertIn(
            "release-version/action.yml", _zizmor_inputs(self.verify_content)
        )

    def test_catalog_readme_lists_the_action(self) -> None:
        self.assertRegex(self.readme_content, r"(?m)^- `release-version/` ")


if __name__ == "__main__":
    unittest.main()
