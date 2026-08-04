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
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ, GITHUB_WORKSPACE=str(workspace))
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                packages_dir,
                "--repository-url",
                repository_url,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_accepts_flat_supported_distributions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            dist = workspace / "release" / "pypi"
            dist.mkdir(parents=True)
            (dist / "library-1.0.0-py3-none-any.whl").touch()
            (dist / "library-1.0.0.tar.gz").touch()

            result = self.run_validator(workspace, "release/pypi")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 2 distribution(s)", result.stdout)

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

    def test_rejects_a_directory_outside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            outside = Path(temporary_directory) / "outside"
            outside.mkdir()
            (outside / "library-1.0.0-py3-none-any.whl").touch()

            result = self.run_validator(workspace, str(outside))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be inside GITHUB_WORKSPACE", result.stderr)

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
