# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the Maven Central publish boundary guard."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = (
    Path(__file__).resolve().parents[1]
    / "maven-central"
    / "scripts"
    / "validate_publish.py"
)

# Sentinels chosen so an accidental echo of any credential is unmistakable.
CREDENTIALS = {
    "MAVEN_CENTRAL_USERNAME": "central-token-user-SENTINEL",
    "MAVEN_CENTRAL_PASSWORD": "central-token-password-SENTINEL",
    "CI_GPG_SECRET_KEY": "-----BEGIN PGP PRIVATE KEY BLOCK-----\nSENTINELKEY\n",
    "CI_GPG_SECRET_KEY_PASSWORD": "gpg-passphrase-SENTINEL",
}


def _seed_module(module: Path) -> None:
    module.mkdir(parents=True, exist_ok=True)
    (module / "pom.xml").write_text("<project/>\n", encoding="utf-8")


class PublishBoundaryTests(unittest.TestCase):
    def run_validator(
        self,
        workspace: Path,
        *,
        working_directory: str = "code",
        project_type: str = "single",
        strategy: str = "maven-central-gpg",
        packages: str = "",
        auto_publish: str = "true",
        credentials: dict[str, str] | None = None,
        include_workspace: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in CREDENTIALS and key != "GITHUB_WORKSPACE"
        }
        if include_workspace:
            environment["GITHUB_WORKSPACE"] = str(workspace)
        environment.update(CREDENTIALS if credentials is None else credentials)
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--working-directory",
                working_directory,
                "--project-type",
                project_type,
                "--strategy",
                strategy,
                "--packages",
                packages,
                "--auto-publish",
                auto_publish,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def assertNoSecretLeak(self, result: subprocess.CompletedProcess[str]) -> None:
        for value in CREDENTIALS.values():
            for line in value.splitlines():
                if line:
                    self.assertNotIn(line, result.stdout)
                    self.assertNotIn(line, result.stderr)

    def test_accepts_a_valid_single_reactor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")

            result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated single publish boundary", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertNoSecretLeak(result)

    def test_accepts_a_monorepo_with_released_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            _seed_module(workspace / "code" / "orders-api")
            _seed_module(workspace / "code" / "billing-core")

            result = self.run_validator(
                workspace,
                project_type="monorepo",
                packages="orders-api, billing-core",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNoSecretLeak(result)

    def test_fails_closed_when_any_credential_is_absent(self) -> None:
        for missing in CREDENTIALS:
            with self.subTest(missing=missing):
                credentials = {k: v for k, v in CREDENTIALS.items() if k != missing}
                with tempfile.TemporaryDirectory() as temporary:
                    workspace = Path(temporary)
                    _seed_module(workspace / "code")
                    result = self.run_validator(workspace, credentials=credentials)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn(
                    "signing and publish credentials are required",
                    result.stderr,
                )
                self.assertIn(missing, result.stderr)
                self.assertNoSecretLeak(result)

    def test_fails_closed_when_credential_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            credentials = dict(CREDENTIALS, CI_GPG_SECRET_KEY="")
            result = self.run_validator(workspace, credentials=credentials)

        self.assertEqual(result.returncode, 1)
        self.assertIn("CI_GPG_SECRET_KEY", result.stderr)

    def test_reserved_oidc_strategy_is_rejected_distinctly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            result = self.run_validator(workspace, strategy="oidc")

        self.assertEqual(result.returncode, 1)
        self.assertIn("reserved seam", result.stderr)
        self.assertIn("not implemented", result.stderr)

    def test_unknown_strategy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            result = self.run_validator(workspace, strategy="nexus-staging")

        self.assertEqual(result.returncode, 1)
        self.assertIn("strategy must be 'maven-central-gpg'", result.stderr)

    def test_invalid_project_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            result = self.run_validator(workspace, project_type="workspace")

        self.assertEqual(result.returncode, 1)
        self.assertIn("project-type must be one of", result.stderr)

    def test_invalid_auto_publish_boolean_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            result = self.run_validator(workspace, auto_publish="yes")

        self.assertEqual(result.returncode, 1)
        self.assertIn("auto-publish must be exactly 'true' or 'false'", result.stderr)

    def test_missing_pom_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "code").mkdir()
            result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("reactor has no pom.xml", result.stderr)

    def test_absolute_and_traversal_working_directories_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            _seed_module(workspace / "code")
            outside = Path(temporary) / "outside"
            _seed_module(outside)

            absolute = self.run_validator(workspace, working_directory=str(outside))
            traversal = self.run_validator(workspace, working_directory="../outside")

        self.assertEqual(absolute.returncode, 1)
        self.assertIn("relative to the workspace", absolute.stderr)
        self.assertEqual(traversal.returncode, 1)
        self.assertIn("must stay inside GITHUB_WORKSPACE", traversal.stderr)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks require POSIX")
    def test_symlinked_path_component_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            real = workspace / "real-code"
            _seed_module(real)
            (workspace / "code").symlink_to(real, target_is_directory=True)

            result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("symbolic path components are not supported", result.stderr)

    def test_packages_on_single_project_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            _seed_module(workspace / "code" / "orders-api")
            result = self.run_validator(
                workspace, project_type="single", packages="orders-api"
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("packages may only be supplied for a monorepo", result.stderr)

    def test_package_traversal_and_non_module_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            (workspace / "code" / "docs").mkdir()

            nested = self.run_validator(
                workspace, project_type="monorepo", packages="../code"
            )
            non_module = self.run_validator(
                workspace, project_type="monorepo", packages="docs"
            )

        self.assertEqual(nested.returncode, 1)
        self.assertIn("single reactor module directory", nested.stderr)
        self.assertEqual(non_module.returncode, 1)
        self.assertIn("is not a Maven module", non_module.stderr)

    def test_requires_github_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _seed_module(workspace / "code")
            result = self.run_validator(workspace, include_workspace=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("GITHUB_WORKSPACE is required", result.stderr)

    def test_failures_use_a_stable_actionable_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "code").mkdir()
            result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(
            result.stderr.startswith("Publish validation failed: "),
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_argument_errors_use_the_same_failure_contract(self) -> None:
        environment = dict(os.environ, GITHUB_WORKSPACE=os.getcwd(), **CREDENTIALS)
        for arguments in (
            (),
            ("--help",),
            ("--working-directory", "code", "--unknown-option"),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(VALIDATOR), *arguments],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(
                    result.stderr.startswith(
                        "Publish validation failed: invalid arguments:"
                    ),
                    result.stderr,
                )


if __name__ == "__main__":
    unittest.main()
