# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Input validation and output-shape tests for the release-version script."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from test_release_version import (
    SCRIPT,
    ActionResult,
    ReleaseVersionTestCase,
    _environment,
    _read_outputs,
    package,
)


class InvalidInputTests(ReleaseVersionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo.tag("0.2.0")
        self.repo.commit()

    def assertFailsClosed(self, result: ActionResult, fragment: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("::error title=Release version::", result.stdout)
        self.assertIn(fragment, result.stdout)
        self.assertEqual(result.outputs, {})

    def test_unknown_tag_format_fails(self) -> None:
        for tag_format in ("", "V", "semver"):
            with self.subTest(tag_format=tag_format):
                self.assertFailsClosed(
                    self.run_action(
                        release_type="patch", tag_format=tag_format, packages=[package()]
                    ),
                    "tag-format",
                )

    def test_empty_release_type_fails(self) -> None:
        self.assertFailsClosed(
            self.run_action(release_type="", tag_format="bare", packages=[package()]),
            "unknown release type",
        )

    def test_unknown_strategy_fails(self) -> None:
        for strategy in ("", "monorepo", "workspaces"):
            with self.subTest(strategy=strategy):
                self.assertFailsClosed(
                    self.run_action(
                        release_type="patch",
                        tag_format="bare",
                        strategy=strategy,
                        packages=[package()],
                    ),
                    "unknown strategy",
                )

    def test_unknown_dev_suffix_fails(self) -> None:
        for dev_suffix in ("-snapshot", ".dev1", "SNAPSHOT", " "):
            with self.subTest(dev_suffix=dev_suffix):
                self.assertFailsClosed(
                    self.run_action(
                        release_type="patch",
                        tag_format="bare",
                        packages=[package()],
                        dev_suffix=dev_suffix,
                    ),
                    "dev-suffix",
                )

    def test_malformed_package_entries_fail(self) -> None:
        cases = {
            "empty list": [],
            "missing key": [{"name": "demo", "tag-prefix": ""}],
            "misspelled key": [
                {"name": "demo", "tag_prefix": "", "declared-version": ""}
            ],
            "extra key": [
                {"name": "demo", "tag-prefix": "", "declared-version": "", "path": "."}
            ],
            "non-string value": [
                {"name": "demo", "tag-prefix": "", "declared-version": None}
            ],
            "empty name": [package(name=" ")],
            "name with a newline": [package(name="demo\n::warning::injected")],
            "not an object": ["demo"],
        }
        for label, packages in cases.items():
            with self.subTest(case=label):
                self.assertFailsClosed(
                    self.run_action(
                        release_type="patch", tag_format="bare", packages=packages
                    ),
                    "packages",
                )

    def test_packages_that_are_not_a_json_list_fail(self) -> None:
        for raw in ("not json", '{"name": "demo"}', ""):
            with self.subTest(raw=raw):
                result = self._run_raw_packages(raw)
                self.assertFailsClosed(result, "packages")

    def _run_raw_packages(self, raw: str) -> ActionResult:
        output_file = self.workspace / "github-output"
        output_file.write_text("", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--release-type=patch",
                "--tag-format=bare",
                "--strategy=single",
                f"--packages={raw}",
                "--dev-suffix=",
            ],
            cwd=self.repo.path,
            check=False,
            capture_output=True,
            text=True,
            env=_environment(GITHUB_OUTPUT=str(output_file)),
        )
        return ActionResult(
            completed.returncode, completed.stdout, completed.stderr, _read_outputs(output_file)
        )

    def test_single_and_locked_step_take_one_package_without_a_prefix(self) -> None:
        for strategy in ("single", "locked-step"):
            for label, packages in (
                ("two packages", [package(name="a"), package(name="b")]),
                ("prefixed package", [package(prefix="core-")]),
            ):
                with self.subTest(strategy=strategy, case=label):
                    self.assertFailsClosed(
                        self.run_action(
                            release_type="patch",
                            tag_format="bare",
                            strategy=strategy,
                            packages=packages,
                        ),
                        "exactly one package",
                    )

    def test_independent_packages_need_distinct_non_empty_prefixes_and_names(self) -> None:
        cases = {
            "empty prefix": ([package(name="core", prefix="")], "non-empty tag-prefix"),
            "duplicate name": (
                [package(name="core", prefix="core-"), package(name="core", prefix="cli-")],
                "names must be unique",
            ),
            "duplicate prefix": (
                [package(name="core", prefix="core-"), package(name="cli", prefix="core-")],
                "tag-prefix values must be unique",
            ),
        }
        for label, (packages, fragment) in cases.items():
            with self.subTest(case=label):
                self.assertFailsClosed(
                    self.run_action(
                        release_type="patch",
                        tag_format="bare",
                        strategy="independent",
                        packages=packages,
                    ),
                    fragment,
                )

    def test_prefixes_that_are_not_literal_tag_text_fail(self) -> None:
        for prefix in ("core-*", "c?re-", "[c]ore-", "core -", "-core-", "core\\-", "core-\n"):
            with self.subTest(prefix=prefix):
                self.assertFailsClosed(
                    self.run_action(
                        release_type="patch",
                        tag_format="bare",
                        strategy="independent",
                        packages=[package(name="core", prefix=prefix)],
                    ),
                    "tag-prefix",
                )


class EnvironmentTests(ReleaseVersionTestCase):
    def _run(self, *, cwd: Path, github_output: str | None) -> subprocess.CompletedProcess[str]:
        extra = {"GIT_CEILING_DIRECTORIES": str(self.workspace)}
        if github_output is not None:
            extra["GITHUB_OUTPUT"] = github_output
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--release-type=patch",
                "--tag-format=bare",
                "--strategy=single",
                f"--packages={json.dumps([package()])}",
                "--dev-suffix=",
            ],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env=_environment(**extra),
        )

    def test_outside_a_git_repository_fails(self) -> None:
        outside = self.workspace / "outside"
        outside.mkdir()
        output_file = self.workspace / "github-output"
        output_file.write_text("", encoding="utf-8")
        completed = self._run(cwd=outside, github_output=str(output_file))
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("::error title=Release version::git tag --merged HEAD failed", completed.stdout)
        self.assertEqual(output_file.read_text(encoding="utf-8"), "")

    def test_missing_github_output_fails(self) -> None:
        completed = self._run(cwd=self.repo.path, github_output=None)
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("::error title=Release version::GITHUB_OUTPUT is not set", completed.stdout)

    def _clone(self, name: str, *options: str) -> Path:
        destination = self.workspace / name
        subprocess.run(
            ["git", "clone", "--quiet", *options, self.repo.path.as_uri(), str(destination)],
            check=True,
            capture_output=True,
            text=True,
            env=_environment(),
        )
        return destination

    def _is_shallow(self, path: Path) -> str:
        return subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
            env=_environment(),
        ).stdout.strip()

    def test_shallow_clone_fails_closed(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        shallow = self._clone("shallow", "--depth", "1")
        self.assertEqual(self._is_shallow(shallow), "true")
        output_file = self.workspace / "github-output"
        output_file.write_text("", encoding="utf-8")
        completed = self._run(cwd=shallow, github_output=str(output_file))
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("::error title=Release version::", completed.stdout)
        self.assertIn("shallow", completed.stdout)
        self.assertNotIn("Package ", completed.stdout)
        self.assertEqual(output_file.read_text(encoding="utf-8"), "")

    def test_full_clone_reads_the_origin_tags(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        full = self._clone("full")
        self.assertEqual(self._is_shallow(full), "false")
        output_file = self.workspace / "github-output"
        output_file.write_text("", encoding="utf-8")
        completed = self._run(cwd=full, github_output=str(output_file))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        outputs = _read_outputs(output_file)
        self.assertEqual(outputs["version"], "0.2.1")
        self.assertEqual(outputs["tag"], "0.2.1")

    def test_error_message_escapes_workflow_command_characters(self) -> None:
        result = self.run_action(
            release_type="50%\nhuge", tag_format="bare", packages=[package()]
        )
        self.assertNotEqual(result.returncode, 0)
        error_lines = [line for line in result.stdout.splitlines() if "::error" in line]
        self.assertEqual(len(error_lines), 1, result.stdout)
        self.assertIn("50%25", error_lines[0])
        self.assertIn("huge", error_lines[0])


class OutputShapeTests(ReleaseVersionTestCase):
    def test_independent_records_follow_the_packages_order_and_the_first_is_primary(
        self,
    ) -> None:
        self.repo.tag("core-1.4.0", "cli-0.9.2")
        self.repo.commit()
        for order in (("cli", "core"), ("core", "cli")):
            with self.subTest(order=order):
                result = self.run_action(
                    release_type="minor",
                    tag_format="bare",
                    strategy="independent",
                    packages=[package(name=name, prefix=f"{name}-") for name in order],
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([record["package"] for record in result.releases], list(order))
                self.assertEqual(result.outputs["version"], result.releases[0]["version"])
                self.assertEqual(result.outputs["tag"], result.releases[0]["tag"])

    def test_first_release_has_an_empty_base(self) -> None:
        for declared in ("0.1.0-SNAPSHOT", ""):
            with self.subTest(declared=declared):
                record = self.single(
                    self.run_action(
                        release_type="minor",
                        tag_format="bare",
                        packages=[package(declared=declared)],
                    )
                )
                self.assertEqual(record["base"], "")
                self.assertIs(record["first_release"], True)

    def test_outputs_are_single_line_name_value_pairs(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        output_file = self.workspace / "github-output"
        result = self.run_action(release_type="patch", tag_format="bare", packages=[package()])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = output_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual([line.split("=", 1)[0] for line in lines], ["releases", "version", "tag"])
        self.assertEqual(lines[1:], ["version=0.2.1", "tag=0.2.1"])


if __name__ == "__main__":
    unittest.main()
