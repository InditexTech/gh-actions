# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the PyPI artifact boundary validator."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = (
    Path(__file__).resolve().parents[1] / "pypi" / "scripts" / "validate_distributions.py"
)


class DistributionValidationTests(unittest.TestCase):
    def run_validator(
        self,
        workspace: Path,
        packages_dir: str,
        repository_url: str = "https://upload.pypi.org/legacy/",
        *,
        attestations: str = "true",
        skip_existing: str = "false",
        verify_metadata: str = "true",
        include_oidc: bool = True,
        include_workspace: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        if include_workspace:
            environment["GITHUB_WORKSPACE"] = str(workspace)
        else:
            environment.pop("GITHUB_WORKSPACE", None)
        if include_oidc:
            environment.update(
                {
                    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example.invalid/token",
                    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "sensitive-oidc-request-token",
                }
            )
        else:
            environment.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
            environment.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                packages_dir,
                "--repository-url",
                repository_url,
                "--attestations",
                attestations,
                "--skip-existing",
                skip_existing,
                "--verify-metadata",
                verify_metadata,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_accepts_flat_supported_distributions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "release files" / "pypi"
            dist.mkdir(parents=True)
            (dist / "library-1.0.0-py3-none-any.whl").touch()
            (dist / "library-1.0.0.tar.gz").touch()
            (dist / "library-1.0.0.zip").touch()

            result = self.run_validator(workspace, "release files/pypi")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 3 distribution(s)", result.stdout)
        self.assertNotIn("sensitive-oidc-request-token", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_accepts_an_absolute_directory_inside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            artifact = dist / "library-1.0.0-py3-none-any.whl"
            artifact.touch()
            artifact.chmod(0o444)

            result = self.run_validator(workspace, str(dist.resolve()))

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_undeclared_non_distribution_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "declared-1.0.0-py3-none-any.whl").touch()
            (dist / "undeclared-package-metadata.json").touch()

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported artifact", result.stderr)

    def test_rejects_empty_or_nested_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            empty = workspace / "empty"
            empty.mkdir()
            empty_result = self.run_validator(workspace, "empty")

            nested = workspace / "nested"
            (nested / "not-flat").mkdir(parents=True)
            nested_result = self.run_validator(workspace, "nested")

        self.assertNotEqual(empty_result.returncode, 0)
        self.assertIn("directory is empty", empty_result.stderr)
        self.assertNotEqual(nested_result.returncode, 0)
        self.assertIn("nested directories", nested_result.stderr)

    def test_rejects_outside_and_parent_traversal_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            outside = Path(temporary_directory) / "outside"
            outside.mkdir()
            (outside / "library-1.0.0-py3-none-any.whl").touch()

            result = self.run_validator(workspace, str(outside))
            traversal_result = self.run_validator(workspace, "../outside")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be inside GITHUB_WORKSPACE", result.stderr)
        self.assertNotEqual(traversal_result.returncode, 0)
        self.assertIn("must be inside GITHUB_WORKSPACE", traversal_result.stderr)

    def test_rejects_a_symlinked_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            dist = workspace / "dist"
            dist.mkdir()
            external_artifact = Path(temporary_directory) / "external-1.0.0-py3-none-any.whl"
            external_artifact.touch()
            (dist / external_artifact.name).symlink_to(external_artifact)

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic links are not supported", result.stderr)

    def test_rejects_a_symlinked_packages_directory_even_when_it_stays_inside(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            real_dist = workspace / "real-dist"
            real_dist.mkdir()
            (real_dist / "library-1.0.0-py3-none-any.whl").touch()
            (workspace / "dist").symlink_to(real_dist, target_is_directory=True)

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic path components are not supported", result.stderr)

    def test_accepts_testpypi_but_rejects_untrusted_publish_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "library-1.0.0-py3-none-any.whl").touch()

            testpypi_result = self.run_validator(
                workspace,
                "dist",
                "https://test.pypi.org/legacy/",
            )
            malicious_result = self.run_validator(
                workspace,
                "dist",
                "https://publisher.example.invalid/legacy/",
            )

        self.assertEqual(testpypi_result.returncode, 0, testpypi_result.stderr)
        self.assertNotEqual(malicious_result.returncode, 0)
        self.assertIn("repository URL must be one of", malicious_result.stderr)

    def test_repository_url_allowlist_is_exact(self) -> None:
        invalid_urls = (
            "http://upload.pypi.org/legacy/",
            "https://UPLOAD.PYPI.ORG/legacy/",
            "https://upload.pypi.org/legacy",
            "https://upload.pypi.org/legacy/?next=https://example.invalid",
            "https://upload.pypi.org@publisher.example.invalid/legacy/",
            " https://upload.pypi.org/legacy/",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "library-1.0.0-py3-none-any.whl").touch()

            for repository_url in invalid_urls:
                with self.subTest(repository_url=repository_url):
                    result = self.run_validator(
                        workspace,
                        "dist",
                        repository_url,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("repository URL must be one of", result.stderr)

    def test_rejects_invalid_boolean_inputs_without_shell_interpretation(self) -> None:
        cases = (
            ("attestations", {"attestations": "TRUE"}),
            ("skip-existing", {"skip_existing": "yes"}),
            ("verify-metadata", {"verify_metadata": "true; echo injected"}),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "library-1.0.0-py3-none-any.whl").touch()

            for name, values in cases:
                with self.subTest(name=name):
                    result = self.run_validator(workspace, "dist", **values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        f"{name} must be exactly 'true' or 'false'",
                        result.stderr,
                    )
                    self.assertNotIn("injected\n", result.stdout)

    def test_accepts_each_boolean_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "library-1.0.0-py3-none-any.whl").touch()

            for value in ("true", "false"):
                with self.subTest(value=value):
                    result = self.run_validator(
                        workspace,
                        "dist",
                        attestations=value,
                        skip_existing=value,
                        verify_metadata=value,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_oidc_and_never_logs_the_request_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "library-1.0.0-py3-none-any.whl").touch()

            result = self.run_validator(
                workspace,
                "dist",
                include_oidc=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("job permission id-token: write", result.stderr)
        self.assertNotIn("sensitive-oidc-request-token", result.stdout)
        self.assertNotIn("sensitive-oidc-request-token", result.stderr)

    def test_requires_a_valid_workspace_and_packages_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing_workspace = self.run_validator(
                root,
                "dist",
                include_workspace=False,
            )
            nonexistent_workspace = self.run_validator(
                root / "missing",
                "dist",
            )
            file_workspace = root / "workspace-file"
            file_workspace.touch()
            file_workspace_result = self.run_validator(file_workspace, "dist")

            workspace = root / "workspace"
            workspace.mkdir()
            missing_directory = self.run_validator(workspace, "missing")
            distribution_file = workspace / "library.whl"
            distribution_file.touch()
            file_result = self.run_validator(workspace, "library.whl")
            empty_path = self.run_validator(workspace, "")

        self.assertIn("GITHUB_WORKSPACE is required", missing_workspace.stderr)
        self.assertIn(
            "GITHUB_WORKSPACE does not exist",
            nonexistent_workspace.stderr,
        )
        self.assertIn(
            "GITHUB_WORKSPACE is not a directory",
            file_workspace_result.stderr,
        )
        self.assertIn("directory does not exist", missing_directory.stderr)
        self.assertIn("path is not a directory", file_result.stderr)
        self.assertIn("packages-dir must not be empty", empty_path.stderr)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO entries require POSIX")
    def test_rejects_non_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "dist"
            dist.mkdir()
            os.mkfifo(dist / "stream.whl")

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported filesystem entry", result.stderr)

    def test_failures_use_a_stable_actionable_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            result = self.run_validator(workspace, "missing")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(
            result.stderr.startswith("Distribution validation failed: "),
            result.stderr,
        )

    def test_argument_errors_use_the_same_failure_contract(self) -> None:
        environment = dict(
            os.environ,
            GITHUB_WORKSPACE=os.getcwd(),
            ACTIONS_ID_TOKEN_REQUEST_URL="https://oidc.example.invalid/token",
            ACTIONS_ID_TOKEN_REQUEST_TOKEN="sensitive-oidc-request-token",
        )
        for arguments in ((), ("dist", "--unknown-option")):
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
                        "Distribution validation failed: invalid arguments:"
                    ),
                    result.stderr,
                )
                self.assertNotIn("sensitive-oidc-request-token", result.stderr)
