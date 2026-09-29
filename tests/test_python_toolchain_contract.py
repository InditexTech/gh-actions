# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0

"""Static contracts for the governed Python toolchain composite."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "python-toolchain" / "action.yml"
VERIFY_WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"

EXPECTED_INPUTS = {
    "tool-versions": {"required": "true"},
    "asdf-version": {"required": "true"},
    "working-directory": {"required": "false", "default": "."},
    "cache-dependency-glob": {"required": "false", "default": "uv.lock"},
}


def _input_contract(content: str) -> dict[str, dict[str, str]]:
    inputs = content.split("inputs:\n", 1)[1].split("\noutputs:\n", 1)[0]
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


class PythonToolchainContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = ACTION.read_text(encoding="utf-8")
        self.verify_content = VERIFY_WORKFLOW.read_text(encoding="utf-8")

    def test_public_input_contract_is_exact(self) -> None:
        contract = _input_contract(self.content)
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

    def test_declares_python_output(self) -> None:
        python_block = self.content.split("outputs:", 1)[1].split("runs:", 1)[0]
        self.assertIn("python:", python_block)
        self.assertIn("steps.toolchain.outputs.python", python_block)

    def test_toolchain_cache_is_platform_keyed(self) -> None:
        cache_block = self.content.split("Restore asdf toolchain cache", 1)[1]
        self.assertIn("actions/cache@", cache_block)
        self.assertIsNotNone(
            re.search(
                r"key: python-asdf-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-",
                cache_block,
            )
        )
        self.assertIn("~/.asdf/downloads", cache_block)
        self.assertIn("~/.asdf/installs/python", cache_block)

    def test_pins_every_external_action_to_full_sha(self) -> None:
        for match in re.finditer(r"uses:\s*([^\s]+)@([0-9a-f]{40})", self.content):
            self.assertNotIn("${{", match.group(1))
            self.assertEqual(len(match.group(2)), 40)

    def test_verify_workflow_covers_the_composite(self) -> None:
        self.assertIn("python-toolchain/action.yml", self.verify_content)


if __name__ == "__main__":
    unittest.main()
