#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Validate that a PyPI publish input contains only intended distributions."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SUPPORTED_SUFFIXES = (".whl", ".tar.gz", ".zip")
SUPPORTED_REPOSITORY_URLS = frozenset(
    {
        "https://upload.pypi.org/legacy/",
        "https://test.pypi.org/legacy/",
    }
)


def fail(message: str) -> None:
    print(f"Distribution validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_within_workspace(raw_path: str, workspace: Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        fail(f"directory does not exist: {candidate}")

    if not resolved.is_dir():
        fail(f"path is not a directory: {resolved}")

    try:
        resolved.relative_to(workspace)
    except ValueError:
        fail(f"directory must be inside GITHUB_WORKSPACE: {resolved}")
    return resolved


def validate_repository_url(repository_url: str) -> None:
    if repository_url not in SUPPORTED_REPOSITORY_URLS:
        supported = ", ".join(sorted(SUPPORTED_REPOSITORY_URLS))
        fail(f"repository URL must be one of: {supported}")


def validate(packages_dir: str, repository_url: str, workspace: Path) -> None:
    validate_repository_url(repository_url)
    directory = resolve_within_workspace(packages_dir, workspace)
    entries = sorted(directory.iterdir(), key=lambda path: path.name)
    if not entries:
        fail(f"directory is empty: {directory}")

    for entry in entries:
        if entry.is_symlink():
            fail(f"symbolic links are not supported: {entry.name}")
        if entry.is_dir():
            fail(f"nested directories are not supported: {entry.name}")
        if not entry.is_file():
            fail(f"unsupported filesystem entry: {entry.name}")
        if not entry.name.endswith(SUPPORTED_SUFFIXES):
            supported = ", ".join(SUPPORTED_SUFFIXES)
            fail(f"unsupported artifact {entry.name!r}; expected one of: {supported}")

    print(f"Validated {len(entries)} distribution(s) in {directory}")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages_dir")
    parser.add_argument(
        "--repository-url",
        default="https://upload.pypi.org/legacy/",
    )
    arguments = parser.parse_args(argv[1:])
    workspace_value = os.environ.get("GITHUB_WORKSPACE")
    if not workspace_value:
        fail("GITHUB_WORKSPACE is required")

    try:
        workspace = Path(workspace_value).resolve(strict=True)
    except FileNotFoundError:
        fail(f"GITHUB_WORKSPACE does not exist: {workspace_value}")
    if not workspace.is_dir():
        fail(f"GITHUB_WORKSPACE is not a directory: {workspace}")

    validate(arguments.packages_dir, arguments.repository_url, workspace)


if __name__ == "__main__":
    main(sys.argv)
