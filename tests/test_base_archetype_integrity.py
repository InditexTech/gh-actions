"""Tests for the standalone base-archetype source validator action."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACTION_ROOT = ROOT / "base-archetype-integrity"
CONTRACT_PATH = ACTION_ROOT / "contract.json"
MODULE_PATH = ACTION_ROOT / "verify_base_archetype.py"
REUSABLE_WORKFLOW = ROOT / ".github/workflows/verify-base-archetype.yml"

SPEC = importlib.util.spec_from_file_location("verify_base_archetype", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _contract() -> dict[str, object]:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _valid_source() -> dict[str, bytes]:
    contract = _contract()
    source: dict[str, bytes] = {}
    for group in (
        "create_only_assets",
        "sync_governed_consumer_assets",
        "base_self_only_assets",
    ):
        values = contract[group]
        assert isinstance(values, list)
        for path in values:
            assert isinstance(path, str)
            source[path] = b"Governance asset\n"

    templated_assets = contract["year_templated_assets"]
    assert isinstance(templated_assets, list)
    for path in templated_assets:
        assert isinstance(path, str)
        source[path] = b"Copyright {{ CURRENT_YEAR }} InditexTech\n"

    source["REUSE.toml"] = (
        b"# Copyright {{ CURRENT_YEAR }} InditexTech\nversion = 1\n"
    )
    source[".github/workflows/pr-verify.yml"] = (
        b"# Copyright {{ CURRENT_YEAR }} InditexTech\n"
        b"jobs:\n  verify:\n    steps:\n"
        b"      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        b"        with:\n"
        b"          persist-credentials: false\n"
    )
    source[".github/workflows/push-verify.yml"] = (
        b"# Copyright {{ CURRENT_YEAR }} InditexTech\n"
        b"jobs:\n  verify:\n    steps:\n"
        b"      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        b"        with:\n"
        b"          persist-credentials: false\n"
    )
    source[".github/workflows/archetype-integrity.yml"] = (
        b"jobs:\n  verify:\n    uses: "
        b"InditexTech/gh-actions/.github/workflows/verify-base-archetype.yml@"
        b"0123456789abcdef0123456789abcdef01234567\n"
    )
    source[".github/workflows/sync-to-develop.yml"] = b"""\
name: Synchronize develop
# Copyright {{ CURRENT_YEAR }} InditexTech
on:
  pull_request_target:
    types: [closed]
env:
  DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
jobs:
  sync:
    if: >-
      github.event.pull_request.merged &&
      vars.DEVELOPMENT_FLOW == 'git-flow' &&
      (github.event.pull_request.base.ref == github.event.repository.default_branch ||
      startsWith(github.event.pull_request.base.ref,
      format('{0}-', github.event.repository.default_branch)))
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
          ref: ${{ github.event.pull_request.base.ref }}
      - run: |
          suffix="${BASE_BRANCH#"$DEFAULT_BRANCH"-}"
          if [[ -z "$suffix" ]]; then
            exit 0
          fi
          echo sync
"""
    return source


class VerifyBaseArchetypeTests(unittest.TestCase):
    """Exercise the action contract with hermetic synthetic source trees."""

    def test_collect_files_reads_action_files_without_importing_candidate_code(self) -> None:
        files = validator.collect_files(ACTION_ROOT)
        self.assertIn("contract.json", files)
        self.assertIn("verify_base_archetype.py", files)

    def test_collect_files_skips_git_metadata(self) -> None:
        files = validator.collect_files(ROOT)
        self.assertNotIn(".git/HEAD", files)

    def test_valid_synthetic_source_satisfies_contract(self) -> None:
        self.assertEqual(
            validator.validate_files(_valid_source(), _contract(), year=2032),
            [],
        )

    def test_deprecated_base_tooling_is_rejected(self) -> None:
        contract = _contract()
        forbidden = contract["forbidden_base_paths"]
        assert isinstance(forbidden, list)
        for path in forbidden:
            assert isinstance(path, str)
            with self.subTest(path=path):
                source = _valid_source()
                source[path] = b"deprecated tooling\n"
                errors = validator.validate_files(source, contract, year=2032)
                self.assertIn(
                    f"deprecated base tooling must not exist: {path}",
                    errors,
                )

    def test_mutable_external_action_is_rejected(self) -> None:
        source = _valid_source()
        source[".github/workflows/pr-verify.yml"] = b"uses: actions/checkout@v4\n"
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertTrue(
            any(
                "external uses reference is not a 40-character SHA" in error
                for error in errors
            )
        )

    def test_local_workflow_action_is_allowed(self) -> None:
        source = _valid_source()
        source[".github/workflows/pr-verify.yml"] += (
            b"      - uses: ./.github/actions/validate\n"
        )
        self.assertEqual(
            validator.validate_files(source, _contract(), year=2032),
            [],
        )

    def test_checkout_requires_the_hardened_release_and_ephemeral_credentials(self) -> None:
        source = _valid_source()
        source[".github/workflows/pr-verify.yml"] = (
            source[".github/workflows/pr-verify.yml"].replace(
                b"persist-credentials: false",
                b"persist-credentials: true",
            )
        )
        source[".github/workflows/push-verify.yml"] = (
            source[".github/workflows/push-verify.yml"].replace(
                b"3d3c42e5aac5ba805825da76410c181273ba90b1",
                b"0123456789abcdef0123456789abcdef01234567",
            )
        )
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertTrue(
            any("checkout must set persist-credentials: false" in error for error in errors)
        )
        self.assertTrue(
            any("checkout must use the approved v7 SHA pin" in error for error in errors)
        )

    def test_generic_workflow_cannot_leak_base_validation(self) -> None:
        source = _valid_source()
        source[".github/workflows/push-verify.yml"] += b"# verify-archetype\n"
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertTrue(any("leaks base-only validation" in error for error in errors))

    def test_integrity_workflow_requires_the_canonical_reusable_workflow(self) -> None:
        source = _valid_source()
        source[".github/workflows/archetype-integrity.yml"] = (
            b"jobs:\n  verify:\n    uses: "
            b"InditexTech/internal-ops/.github/workflows/"
            b"ci-governance-base-archetype-integrity.yml@"
            b"0123456789abcdef0123456789abcdef01234567\n"
        )
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertIn(
            "archetype-integrity.yml must use the canonical SHA-pinned reusable workflow",
            errors,
        )

    def test_sync_workflow_rejects_static_branch_and_main_role(self) -> None:
        source = _valid_source()
        source[".github/workflows/sync-to-develop.yml"] = (
            source[".github/workflows/sync-to-develop.yml"]
            .replace(b"types: [closed]", b"types: [closed]\n    branches: [main]")
            .replace(
                b"github.event.pull_request.base.ref == "
                b"github.event.repository.default_branch",
                b"github.event.pull_request.base.ref == 'main'",
            )
        )
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertTrue(any("must not statically filter branches" in error for error in errors))
        self.assertTrue(any("must not hardcode a main branch role" in error for error in errors))
        self.assertTrue(
            any(
                "compare the base branch to the default branch" in error
                for error in errors
            )
        )

    def test_sync_workflow_requires_closed_pull_request_target(self) -> None:
        source = _valid_source()
        source[".github/workflows/sync-to-develop.yml"] = (
            source[".github/workflows/sync-to-develop.yml"]
            .replace(b"types: [closed]", b"types: [opened]")
        )
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertIn(
            "sync-to-develop.yml must run only for closed pull requests",
            errors,
        )

    def test_sync_workflow_requires_pull_request_target(self) -> None:
        source = _valid_source()
        source[".github/workflows/sync-to-develop.yml"] = (
            source[".github/workflows/sync-to-develop.yml"].replace(
                b"pull_request_target",
                b"pull_request",
            )
        )
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertIn("sync-to-develop.yml must use pull_request_target", errors)

    def test_sync_workflow_requires_an_empty_suffix_guard(self) -> None:
        source = _valid_source()
        source[".github/workflows/sync-to-develop.yml"] = (
            source[".github/workflows/sync-to-develop.yml"].replace(
                b'if [[ -z "$suffix" ]]',
                b'if [[ -n "$suffix" ]]',
            )
        )
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertIn(
            "sync-to-develop.yml must skip empty release suffixes",
            errors,
        )

    def test_sync_workflow_rejects_unsafe_pull_request_target_controls(self) -> None:
        unsafe_cases = {
            "head": (
                b"\n# github.event.pull_request.head.sha\n",
                "must not reference pull request head data",
            ),
            "pull-ref": (
                b"\n# refs/pull/42/merge\n",
                "must not use pull request refs",
            ),
            "unsafe-checkout": (
                b"\n# allow-unsafe-pr-checkout\n",
                "must not enable unsafe PR checkout",
            ),
            "self-hosted": (
                b"\n# self-hosted\n",
                "must not use self-hosted runners",
            ),
        }
        for name, (unsafe_content, expected_error) in unsafe_cases.items():
            with self.subTest(name=name):
                source = _valid_source()
                source[".github/workflows/sync-to-develop.yml"] += unsafe_content
                errors = validator.validate_files(source, _contract(), year=2032)
                self.assertTrue(any(expected_error in error for error in errors))

    def test_branch_mapping_fixture_exercises_development_branches(self) -> None:
        self.assertEqual(validator.development_branch("main", "main"), "develop")
        self.assertEqual(validator.development_branch("trunk", "trunk"), "develop")
        self.assertEqual(
            validator.development_branch("production", "production-2026.08"),
            "develop-2026.08",
        )
        self.assertEqual(
            validator.development_branch(
                "release-candidate",
                "release-candidate-hotfix",
            ),
            "develop-hotfix",
        )
        self.assertIsNone(validator.development_branch("trunk", "release"))
        self.assertIsNone(validator.development_branch("main", "main-"))

        contract = _contract()
        cases = contract["branch_mapping_cases"]
        assert isinstance(cases, list)
        first_case = cases[0]
        assert isinstance(first_case, dict)
        first_case["expected_development_branch"] = "main"
        self.assertTrue(validator.validate_branch_mapping(contract))

    def test_year_template_and_reuse_policy_are_enforced(self) -> None:
        source = _valid_source()
        source["NOTICE"] = b"Copyright 2032 InditexTech\n"
        source["REUSE.toml"] = b"name = 'base-archetype'\n"
        errors = validator.validate_files(source, _contract(), year=2032)
        self.assertTrue(any("missing literal {{ CURRENT_YEAR }}" in error for error in errors))
        self.assertTrue(any("must not contain package metadata" in error for error in errors))
        self.assertTrue(any("must not contain base-archetype identity" in error for error in errors))

    def test_contract_asset_lifecycles_are_disjoint(self) -> None:
        contract = _contract()
        groups = (
            "create_only_assets",
            "sync_governed_consumer_assets",
            "base_self_only_assets",
        )
        seen: set[str] = set()
        for group in groups:
            paths = contract[group]
            assert isinstance(paths, list)
            entries = set(paths)
            self.assertFalse(seen & entries, group)
            seen.update(entries)
        forbidden = contract["forbidden_base_paths"]
        assert isinstance(forbidden, list)
        self.assertFalse(seen & set(forbidden))

    def test_reusable_workflow_gates_behavior_on_static_validation(self) -> None:
        workflow = REUSABLE_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(
            workflow,
            r"uses: zizmorcore/zizmor-action@[0-9a-f]{40}",
        )
        self.assertIn("persona: pedantic", workflow)
        self.assertIn("advanced-security: false", workflow)
        self.assertRegex(
            workflow,
            r"(?ms)sync-workflow-behavior:\s+needs:\s+- verify\s+- zizmor",
        )
        self.assertRegex(
            workflow,
            r"uses: InditexTech/gh-actions/"
            r"base-archetype-sync-workflow-test@[0-9a-f]{40}",
        )
