# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the npm publish boundary validator."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = (
    Path(__file__).resolve().parents[1] / "npm" / "scripts" / "validate_npm_publish.py"
)
OIDC_TOKEN_SENTINEL = "sensitive-oidc-request-token"
NPM_TOKEN_SENTINEL = "sensitive-npm-token"


class NpmPublishValidationTests(unittest.TestCase):
    def run_validator(
        self,
        workspace: Path,
        artifact_directory: str,
        working_directory: str = "code",
        project_type: str = "single",
        dist_tag: str = "latest",
        *,
        include_oidc: bool = True,
        include_npm_token: bool = False,
        include_workspace: bool = True,
        include_runner_temp: bool = True,
        runner_temp: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        for name in (
            "ACTIONS_ID_TOKEN_REQUEST_URL",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
            "NPM_TOKEN",
        ):
            environment.pop(name, None)
        if include_workspace:
            environment["GITHUB_WORKSPACE"] = str(workspace)
        else:
            environment.pop("GITHUB_WORKSPACE", None)
        if include_runner_temp:
            environment["RUNNER_TEMP"] = str(
                runner_temp if runner_temp is not None else workspace
            )
        else:
            environment.pop("RUNNER_TEMP", None)
        if include_oidc:
            environment.update(
                {
                    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example.invalid/token",
                    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": OIDC_TOKEN_SENTINEL,
                }
            )
        if include_npm_token:
            environment["NPM_TOKEN"] = NPM_TOKEN_SENTINEL
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--working-directory",
                working_directory,
                "--project-type",
                project_type,
                "--artifact-directory",
                artifact_directory,
                "--dist-tag",
                dist_tag,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    @staticmethod
    def _seed(workspace: Path, *, tarballs: int = 1) -> None:
        (workspace / "code").mkdir(parents=True, exist_ok=True)
        dist = workspace / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        for index in range(tarballs):
            (dist / f"library-1.0.{index}.tgz").touch()

    def test_accepts_a_single_project_with_one_tarball(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)

            result = self.run_validator(workspace, "dist")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 1 pre-built tarball(s)", result.stdout)
        self.assertNotIn(OIDC_TOKEN_SENTINEL, result.stdout)
        self.assertEqual(result.stderr, "")

    def test_accepts_workspaces_with_several_tarballs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=3)

            result = self.run_validator(workspace, "dist", project_type="workspaces")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 3 pre-built tarball(s)", result.stdout)

    def test_accepts_an_absolute_artifact_directory_inside_runner_temp(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_directory, (
            tempfile.TemporaryDirectory()
        ) as runner_temp_directory:
            workspace = Path(workspace_directory)
            (workspace / "code").mkdir()
            runner_temp = Path(runner_temp_directory)
            artifacts = runner_temp / "publish-dist"
            artifacts.mkdir()
            (artifacts / "library-1.0.0.tgz").touch()

            result = self.run_validator(
                workspace,
                str(artifacts.resolve()),
                runner_temp=runner_temp,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 1 pre-built tarball(s)", result.stdout)

    def test_rejects_undeclared_non_tarball_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)
            (workspace / "dist" / "metadata.json").touch()

            result = self.run_validator(workspace, "dist", project_type="workspaces")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported artifact", result.stderr)

    def test_rejects_empty_or_nested_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "code").mkdir()
            (workspace / "empty").mkdir()
            empty_result = self.run_validator(workspace, "empty")

            nested = workspace / "nested"
            (nested / "not-flat").mkdir(parents=True)
            nested_result = self.run_validator(workspace, "nested")

        self.assertNotEqual(empty_result.returncode, 0)
        self.assertIn("artifact-directory is empty", empty_result.stderr)
        self.assertNotEqual(nested_result.returncode, 0)
        self.assertIn("nested directories", nested_result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX permissions required")
    def test_unreadable_directory_uses_the_failure_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "code").mkdir()
            dist = workspace / "dist"
            dist.mkdir()
            dist.chmod(0)
            try:
                result = self.run_validator(workspace, "dist")
            finally:
                dist.chmod(0o700)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn(
            "npm publish validation failed: cannot read artifact-directory",
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_rejects_outside_and_parent_traversal_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            (workspace / "code").mkdir()
            outside = Path(temporary_directory) / "outside"
            outside.mkdir()
            (outside / "library-1.0.0.tgz").touch()

            result = self.run_validator(workspace, str(outside))
            traversal_result = self.run_validator(workspace, "../outside")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifact-directory must be inside", result.stderr)
        self.assertNotEqual(traversal_result.returncode, 0)
        self.assertIn("artifact-directory must be inside", traversal_result.stderr)

    def test_rejects_a_symlinked_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            (workspace / "code").mkdir()
            dist = workspace / "dist"
            dist.mkdir()
            external_artifact = Path(temporary_directory) / "external-1.0.0.tgz"
            external_artifact.touch()
            (dist / external_artifact.name).symlink_to(external_artifact)

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic links are not supported", result.stderr)

    def test_rejects_a_symlinked_artifact_directory_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "code").mkdir()
            real_dist = workspace / "real-dist"
            real_dist.mkdir()
            (real_dist / "library-1.0.0.tgz").touch()
            (workspace / "dist").symlink_to(real_dist, target_is_directory=True)

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic path component", result.stderr)

    def test_rejects_invalid_project_type_without_shell_interpretation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)

            for project_type in ("library", "single; echo injected"):
                with self.subTest(project_type=project_type):
                    result = self.run_validator(
                        workspace, "dist", project_type=project_type
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("project-type must be one of", result.stderr)
                    self.assertNotIn("injected\n", result.stdout)

    def test_rejects_invalid_dist_tag_without_shell_interpretation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)

            for dist_tag in ("beta", "latest; echo injected"):
                with self.subTest(dist_tag=dist_tag):
                    result = self.run_validator(workspace, "dist", dist_tag=dist_tag)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("dist-tag must be one of", result.stderr)
                    self.assertNotIn("injected\n", result.stdout)

    def test_accepts_each_supported_dist_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)

            for dist_tag in ("next", "latest"):
                with self.subTest(dist_tag=dist_tag):
                    result = self.run_validator(workspace, "dist", dist_tag=dist_tag)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_a_publish_credential_and_never_logs_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)

            result = self.run_validator(
                workspace,
                "dist",
                include_oidc=False,
                include_npm_token=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no publish credential is available", result.stderr)
        self.assertIn("id-token: write", result.stderr)
        self.assertNotIn(OIDC_TOKEN_SENTINEL, result.stdout)
        self.assertNotIn(OIDC_TOKEN_SENTINEL, result.stderr)

    def test_accepts_the_npm_token_fallback_without_oidc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=1)

            result = self.run_validator(
                workspace,
                "dist",
                include_oidc=False,
                include_npm_token=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(NPM_TOKEN_SENTINEL, result.stdout)
        self.assertNotIn(NPM_TOKEN_SENTINEL, result.stderr)

    def test_single_project_type_rejects_multiple_tarballs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            self._seed(workspace, tarballs=2)

            result = self.run_validator(workspace, "dist", project_type="single")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "single project-type must publish exactly one tarball",
            result.stderr,
        )

    def test_requires_a_valid_workspace_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing_workspace = self.run_validator(
                root,
                "dist",
                include_workspace=False,
            )
            nonexistent_workspace = self.run_validator(root / "missing", "dist")
            file_workspace = root / "workspace-file"
            file_workspace.touch()
            file_workspace_result = self.run_validator(file_workspace, "dist")

            workspace = root / "workspace"
            workspace.mkdir()
            missing_working_dir = self.run_validator(
                workspace, "dist", working_directory="missing"
            )
            (workspace / "code").mkdir()
            file_working_dir = workspace / "code" / "package.json"
            file_working_dir.touch()
            file_working_dir_result = self.run_validator(
                workspace, "dist", working_directory="code/package.json"
            )
            missing_artifact = self.run_validator(workspace, "missing")
            empty_artifact = self.run_validator(workspace, "")

        self.assertIn("GITHUB_WORKSPACE is required", missing_workspace.stderr)
        self.assertIn("GITHUB_WORKSPACE does not exist", nonexistent_workspace.stderr)
        self.assertIn(
            "GITHUB_WORKSPACE is not a directory", file_workspace_result.stderr
        )
        self.assertIn("working-directory does not exist", missing_working_dir.stderr)
        self.assertIn(
            "working-directory is not a directory", file_working_dir_result.stderr
        )
        self.assertIn("artifact-directory does not exist", missing_artifact.stderr)
        self.assertIn("artifact-directory must not be empty", empty_artifact.stderr)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks require POSIX")
    def test_unresolvable_workspace_uses_the_failure_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            loop = Path(temporary_directory) / "loop"
            loop.symlink_to(loop)
            result = self.run_validator(loop, "dist")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn(
            "npm publish validation failed: GITHUB_WORKSPACE could not be resolved",
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO entries require POSIX")
    def test_rejects_non_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "code").mkdir()
            dist = workspace / "dist"
            dist.mkdir()
            os.mkfifo(dist / "stream.tgz")

            result = self.run_validator(workspace, "dist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported filesystem entry", result.stderr)

    def test_failures_use_a_stable_actionable_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "code").mkdir()
            result = self.run_validator(workspace, "missing")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(
            result.stderr.startswith("npm publish validation failed: "),
            result.stderr,
        )

    def test_argument_errors_use_the_same_failure_contract(self) -> None:
        environment = dict(
            os.environ,
            GITHUB_WORKSPACE=os.getcwd(),
            ACTIONS_ID_TOKEN_REQUEST_URL="https://oidc.example.invalid/token",
            ACTIONS_ID_TOKEN_REQUEST_TOKEN=OIDC_TOKEN_SENTINEL,
        )
        for arguments in (
            (),
            ("--help",),
            ("--working-directory", "code", "--project-type", "single"),
            (
                "--working-directory",
                "code",
                "--project-type",
                "single",
                "--artifact-directory",
                "dist",
                "--unknown-option",
            ),
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
                        "npm publish validation failed: invalid arguments:"
                    ),
                    result.stderr,
                )
                self.assertNotIn(OIDC_TOKEN_SENTINEL, result.stderr)


if __name__ == "__main__":
    unittest.main()
