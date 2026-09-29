# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0

"""Static contracts for the release git signing composite."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "configure-release-git" / "action.yml"

EXPECTED_INPUTS = {
    "token": {"required": "true"},
    "gpg-secret-key": {"required": "true"},
    "gpg-passphrase": {"required": "true"},
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


class ConfigureReleaseGitContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = ACTION.read_text(encoding="utf-8")

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

    def test_signing_is_enabled_for_commits_and_tags(self) -> None:
        self.assertIn("commit.gpgsign true", self.content)
        self.assertIn("tag.gpgsign true", self.content)
        self.assertIn("user.signingkey", self.content)

    def test_release_identity_is_pinned(self) -> None:
        self.assertIn('user.name "srvcosoitxtech"', self.content)
        self.assertIn('user.email "oso@inditex.com"', self.content)

    def test_secret_inputs_never_reach_git_config(self) -> None:
        for line in self.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("git config"):
                self.assertNotIn("CI_GPG_SECRET_KEY", stripped)
                self.assertNotIn("CI_GPG_SECRET_KEY_PASSWORD", stripped)

    def test_no_uses_steps(self) -> None:
        self.assertNotIn("uses:", self.content)


if __name__ == "__main__":
    unittest.main()
