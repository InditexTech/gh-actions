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


def _step_names(content: str) -> list[str]:
    return re.findall(r"^    - name: (.+)$", content, re.MULTILINE)


def _step(content: str, name: str) -> str:
    return content.split(f"    - name: {name}\n", 1)[1].split("\n    - name: ", 1)[0]


def _cache_paths(step: str) -> list[str]:
    block = step.split("path: |\n", 1)[1]
    return re.findall(r"^          (\S.*)$", block.split("\n        key:", 1)[0], re.M)


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
        cache_block = _step(self.content, "Restore asdf toolchain cache")
        self.assertIn("actions/cache/restore@", cache_block)
        self.assertIsNotNone(
            re.search(
                r"key: python-asdf-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-",
                cache_block,
            )
        )
        self.assertIn("~/.asdf/downloads", cache_block)
        self.assertIn("~/.asdf/installs/python", cache_block)

    def test_toolchain_cache_is_saved_as_soon_as_it_is_built(self) -> None:
        # The combined actions/cache only saves in its post step when the whole
        # job succeeds, so a release that fails after compiling never seeds the
        # default-branch scope and every retry recompiles CPython.
        self.assertNotRegex(self.content, r"uses:\s*actions/cache@")
        names = _step_names(self.content)
        self.assertLess(
            names.index("Set up asdf-managed Python"),
            names.index("Save asdf toolchain cache"),
        )
        restore = _step(self.content, "Restore asdf toolchain cache")
        save = _step(self.content, "Save asdf toolchain cache")
        self.assertEqual(
            re.search(r"actions/cache/restore@([0-9a-f]{40})", restore).group(1),
            re.search(r"actions/cache/save@([0-9a-f]{40})", save).group(1),
        )
        self.assertIn(
            "if: steps.toolchain-cache.outputs.cache-hit != 'true'", save
        )
        self.assertIn(
            "key: ${{ steps.toolchain-cache.outputs.cache-primary-key }}", save
        )
        self.assertEqual(_cache_paths(restore), _cache_paths(save))

    def test_pins_every_external_action_to_full_sha(self) -> None:
        for match in re.finditer(r"uses:\s*([^\s]+)@([0-9a-f]{40})", self.content):
            self.assertNotIn("${{", match.group(1))
            self.assertEqual(len(match.group(2)), 40)

    def test_verify_workflow_covers_the_composite(self) -> None:
        self.assertIn("python-toolchain/action.yml", self.verify_content)


if __name__ == "__main__":
    unittest.main()
