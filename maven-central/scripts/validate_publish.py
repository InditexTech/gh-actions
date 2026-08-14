#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Fail closed before a Maven Central publish unless the boundary is intact.

This guard is the composite's first step. It never signs, uploads, or reads a
consumer project's build logic; it only proves that a privileged publish is
allowed to proceed:

* the four Central Portal + GPG credentials are present and non-empty (their
  values are never read into a message or echoed);
* the reactor ``working-directory`` is a real directory inside
  ``GITHUB_WORKSPACE`` with a ``pom.xml`` and no symbolic path component;
* ``project-type`` is one of the two governed layouts;
* ``strategy`` is the implemented ``maven-central-gpg`` -- the reserved ``oidc``
  seam is rejected with a distinct, actionable message so a caller cannot
  silently fall through to an unsigned path;
* ``packages`` (the released modules of an independent monorepo release) name
  real Maven modules inside the reactor, never an absolute path, a parent
  traversal, or a symlink.

Any violation exits ``1`` with the stable ``Publish validation failed:`` prefix
and an empty stdout, mirroring the PyPI boundary validator's contract.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping, NoReturn

REQUIRED_CREDENTIALS = (
    "MAVEN_CENTRAL_USERNAME",
    "MAVEN_CENTRAL_PASSWORD",
    "CI_GPG_SECRET_KEY",
    "CI_GPG_SECRET_KEY_PASSWORD",
)
VALID_PROJECT_TYPES = frozenset({"single", "monorepo"})
IMPLEMENTED_STRATEGY = "maven-central-gpg"
RESERVED_STRATEGIES = frozenset({"oidc"})
BOOLEAN_INPUTS = frozenset({"true", "false"})


def fail(message: str) -> NoReturn:
    print(f"Publish validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


class ValidationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail(f"invalid arguments: {message}")


def validate_credentials(environment: Mapping[str, str]) -> None:
    missing = [name for name in REQUIRED_CREDENTIALS if not environment.get(name)]
    if missing:
        fail(
            "signing and publish credentials are required; missing "
            f"{', '.join(missing)}"
        )


def validate_boolean(name: str, value: str) -> None:
    if value not in BOOLEAN_INPUTS:
        fail(f"{name} must be exactly 'true' or 'false'")


def validate_strategy(strategy: str) -> None:
    if strategy in RESERVED_STRATEGIES:
        fail(
            f"strategy {strategy!r} is a reserved seam and is not implemented; "
            f"use {IMPLEMENTED_STRATEGY!r}"
        )
    if strategy != IMPLEMENTED_STRATEGY:
        fail(f"strategy must be {IMPLEMENTED_STRATEGY!r}")


def resolve_within_workspace(raw_path: str, workspace: Path, *, label: str) -> Path:
    if not raw_path:
        fail(f"{label} must not be empty")
    if "\0" in raw_path:
        fail(f"{label} must not contain a null byte")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        fail(f"{label} must be a path relative to the workspace: {raw_path}")

    lexical = Path(os.path.abspath(workspace / candidate))
    try:
        relative = lexical.relative_to(workspace)
    except ValueError:
        fail(f"{label} must stay inside GITHUB_WORKSPACE: {raw_path}")

    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            fail(f"symbolic path components are not supported: {current}")

    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        fail(f"path does not exist: {raw_path}")
    if not resolved.is_dir():
        fail(f"path is not a directory: {raw_path}")
    return resolved


def validate_reactor(working_directory: str, workspace: Path) -> Path:
    reactor = resolve_within_workspace(
        working_directory, workspace, label="working-directory"
    )
    pom = reactor / "pom.xml"
    if pom.is_symlink() or not pom.is_file():
        fail(f"reactor has no pom.xml: {working_directory}")
    return reactor


def validate_packages(
    packages: str, reactor: Path, workspace: Path, *, project_type: str
) -> None:
    entries = [entry.strip() for entry in packages.split(",") if entry.strip()]
    if not entries:
        return
    if project_type != "monorepo":
        fail("packages may only be supplied for a monorepo release")
    working_directory = reactor.relative_to(workspace).as_posix()
    for entry in entries:
        if "/" in entry or "\\" in entry:
            fail(f"package must be a single reactor module directory: {entry!r}")
        module = resolve_within_workspace(
            f"{working_directory}/{entry}", workspace, label="package"
        )
        module_pom = module / "pom.xml"
        if module_pom.is_symlink() or not module_pom.is_file():
            fail(f"package is not a Maven module: {entry!r}")


def validate(
    working_directory: str,
    project_type: str,
    strategy: str,
    packages: str,
    auto_publish: str,
    workspace: Path,
    *,
    environment: Mapping[str, str],
) -> None:
    validate_credentials(environment)
    if project_type not in VALID_PROJECT_TYPES:
        supported = ", ".join(sorted(VALID_PROJECT_TYPES))
        fail(f"project-type must be one of: {supported}")
    validate_strategy(strategy)
    validate_boolean("auto-publish", auto_publish)
    reactor = validate_reactor(working_directory, workspace)
    validate_packages(packages, reactor, workspace, project_type=project_type)

    scope = "the whole reactor" if not packages.strip() else packages.strip()
    print(
        f"Validated {project_type} publish boundary for {working_directory} "
        f"({scope}) via {strategy}"
    )


def main(argv: list[str]) -> None:
    parser = ValidationArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--project-type", required=True)
    parser.add_argument("--strategy", default=IMPLEMENTED_STRATEGY)
    parser.add_argument("--packages", default="")
    parser.add_argument("--auto-publish", default="true")
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
        arguments.working_directory,
        arguments.project_type,
        arguments.strategy,
        arguments.packages,
        arguments.auto_publish,
        workspace,
        environment=os.environ,
    )


if __name__ == "__main__":
    main(sys.argv)
