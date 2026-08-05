#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Validate that a PyPI publish input contains only intended distributions."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Mapping, Never

SUPPORTED_SUFFIXES = (".whl", ".tar.gz", ".zip")
SUPPORTED_REPOSITORY_URLS = frozenset(
    {
        "https://upload.pypi.org/legacy/",
        "https://test.pypi.org/legacy/",
    }
)
BOOLEAN_INPUTS = frozenset({"true", "false"})
OIDC_ENVIRONMENT_VARIABLES = (
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)


def fail(message: str) -> Never:
    print(f"Distribution validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


class ValidationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        fail(f"invalid arguments: {message}")


def resolve_within_workspace(raw_path: str, workspace: Path) -> Path:
    if not raw_path:
        fail("packages-dir must not be empty")
    if "\0" in raw_path:
        fail("packages-dir must not contain a null byte")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate

    try:
        lexical = Path(os.path.abspath(candidate))
        relative = lexical.relative_to(workspace)
    except (OSError, ValueError):
        fail(f"directory must be inside GITHUB_WORKSPACE: {candidate}")

    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            fail(f"symbolic path components are not supported: {current}")

    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        fail(f"directory does not exist: {candidate}")

    if not resolved.is_dir():
        fail(f"path is not a directory: {resolved}")

    try:
        resolved.relative_to(workspace)
    except ValueError:
        fail(f"directory must be inside GITHUB_WORKSPACE: {resolved}")
    return resolved


def validate_boolean(name: str, value: str) -> None:
    if value not in BOOLEAN_INPUTS:
        fail(f"{name} must be exactly 'true' or 'false'")


def validate_repository_url(repository_url: str) -> None:
    if repository_url not in SUPPORTED_REPOSITORY_URLS:
        supported = ", ".join(sorted(SUPPORTED_REPOSITORY_URLS))
        fail(f"repository URL must be one of: {supported}")


def validate_oidc_environment(environment: Mapping[str, str]) -> None:
    missing = [
        name for name in OIDC_ENVIRONMENT_VARIABLES if not environment.get(name)
    ]
    if missing:
        fail(
            "trusted publishing requires job permission id-token: write; "
            f"missing {', '.join(missing)}"
        )


def validate(
    packages_dir: str,
    repository_url: str,
    workspace: Path,
    *,
    attestations: str,
    skip_existing: str,
    verify_metadata: str,
    environment: Mapping[str, str],
) -> None:
    validate_repository_url(repository_url)
    validate_boolean("attestations", attestations)
    validate_boolean("skip-existing", skip_existing)
    validate_boolean("verify-metadata", verify_metadata)
    validate_oidc_environment(environment)
    directory = resolve_within_workspace(packages_dir, workspace)
    entries = sorted(directory.iterdir(), key=lambda path: path.name)
    if not entries:
        fail(f"directory is empty: {directory}")

    for entry in entries:
        try:
            mode = entry.lstat().st_mode
        except OSError:
            fail(f"cannot inspect filesystem entry: {entry.name}")
        if stat.S_ISLNK(mode):
            fail(f"symbolic links are not supported: {entry.name}")
        if stat.S_ISDIR(mode):
            fail(f"nested directories are not supported: {entry.name}")
        if not stat.S_ISREG(mode):
            fail(f"unsupported filesystem entry: {entry.name}")
        if not entry.name.endswith(SUPPORTED_SUFFIXES):
            supported = ", ".join(SUPPORTED_SUFFIXES)
            fail(f"unsupported artifact {entry.name!r}; expected one of: {supported}")

    print(f"Validated {len(entries)} distribution(s) in {directory}")


def main(argv: list[str]) -> None:
    parser = ValidationArgumentParser()
    parser.add_argument("packages_dir")
    parser.add_argument(
        "--repository-url",
        default="https://upload.pypi.org/legacy/",
    )
    parser.add_argument("--attestations", default="true")
    parser.add_argument("--skip-existing", default="false")
    parser.add_argument("--verify-metadata", default="true")
    arguments = parser.parse_args(argv[1:])
    workspace_value = os.environ.get("GITHUB_WORKSPACE")
    if not workspace_value:
        fail("GITHUB_WORKSPACE is required")

    try:
        workspace = Path(workspace_value).resolve(strict=True)
    except FileNotFoundError:
        fail(f"GITHUB_WORKSPACE does not exist: {workspace_value}")
    except (OSError, RuntimeError) as error:
        fail(f"GITHUB_WORKSPACE could not be resolved: {workspace_value}: {error}")
    if not workspace.is_dir():
        fail(f"GITHUB_WORKSPACE is not a directory: {workspace}")

    validate(
        arguments.packages_dir,
        arguments.repository_url,
        workspace,
        attestations=arguments.attestations,
        skip_existing=arguments.skip_existing,
        verify_metadata=arguments.verify_metadata,
        environment=os.environ,
    )


if __name__ == "__main__":
    main(sys.argv)
