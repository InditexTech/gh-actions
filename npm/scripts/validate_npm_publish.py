#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Validate the npm trusted-publishing boundary before any package is published.

The composite that owns this script publishes pre-built ``.tgz`` tarballs through
npm trusted publishing (OIDC), falling back to an Environment-scoped ``NPM_TOKEN``
only for a brand-new package that is not yet a registered trusted publisher. This
validator is the fail-closed gate that runs first: it never reads or logs the
OIDC request token or ``NPM_TOKEN``, and it rejects the publish before npm is ever
invoked when the inputs, the artifact set, or the available credentials are not
exactly what the governed publish path allows.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Mapping, NoReturn, Sequence

TARBALL_SUFFIX = ".tgz"
VALID_PROJECT_TYPES = frozenset({"single", "workspaces"})
VALID_DIST_TAGS = frozenset({"latest", "next"})
OIDC_ENVIRONMENT_VARIABLES = (
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)
FALLBACK_TOKEN_VARIABLE = "NPM_TOKEN"


def fail(message: str) -> NoReturn:
    print(f"npm publish validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


class ValidationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail(f"invalid arguments: {message}")


def _within_any(path: Path, roots: Sequence[Path]) -> Path | None:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return root
    return None


def _root_list(roots: Sequence[Path]) -> str:
    return " or ".join(str(root) for root in roots)


def resolve_directory(raw_path: str, roots: Sequence[Path], label: str) -> Path:
    if not raw_path:
        fail(f"{label} must not be empty")
    if "\0" in raw_path:
        fail(f"{label} must not contain a null byte")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        # A relative input resolves against the first root (the workspace),
        # mirroring how GitHub resolves a relative action input.
        candidate = roots[0] / candidate

    lexical = Path(os.path.abspath(candidate))

    containing_root = _within_any(lexical, roots)
    if containing_root is None:
        fail(f"{label} must be inside {_root_list(roots)}: {candidate}")

    current = containing_root
    for part in lexical.relative_to(containing_root).parts:
        current /= part
        if current.is_symlink():
            fail(f"{label} must not contain a symbolic path component: {current}")

    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        fail(f"{label} does not exist: {candidate}")

    if not resolved.is_dir():
        fail(f"{label} is not a directory: {resolved}")

    if _within_any(resolved, roots) is None:
        fail(f"{label} must be inside {_root_list(roots)}: {resolved}")
    return resolved


def validate_project_type(project_type: str) -> None:
    if project_type not in VALID_PROJECT_TYPES:
        supported = ", ".join(sorted(VALID_PROJECT_TYPES))
        fail(f"project-type must be one of: {supported}")


def validate_dist_tag(dist_tag: str) -> None:
    if dist_tag not in VALID_DIST_TAGS:
        supported = ", ".join(sorted(VALID_DIST_TAGS))
        fail(f"dist-tag must be one of: {supported}")


def validate_publish_credentials(environment: Mapping[str, str]) -> None:
    oidc_available = all(
        environment.get(name) for name in OIDC_ENVIRONMENT_VARIABLES
    )
    token_available = bool(environment.get(FALLBACK_TOKEN_VARIABLE))
    if not oidc_available and not token_available:
        missing = ", ".join(OIDC_ENVIRONMENT_VARIABLES)
        fail(
            "no publish credential is available: npm trusted publishing needs job "
            f"permission id-token: write (missing {missing}) and no "
            f"{FALLBACK_TOKEN_VARIABLE} fallback is set"
        )


def validate_tarballs(directory: Path, project_type: str) -> list[Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        fail(f"cannot read artifact-directory: {directory}")
    if not entries:
        fail(f"artifact-directory is empty: {directory}")

    tarballs: list[Path] = []
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
        if not entry.name.endswith(TARBALL_SUFFIX):
            fail(
                f"unsupported artifact {entry.name!r}; "
                f"expected a pre-built {TARBALL_SUFFIX} tarball"
            )
        tarballs.append(entry)

    if project_type == "single" and len(tarballs) != 1:
        fail(
            "single project-type must publish exactly one tarball; "
            f"found {len(tarballs)}"
        )
    return tarballs


def validate(
    working_directory: str,
    project_type: str,
    artifact_directory: str,
    dist_tag: str,
    *,
    workspace: Path,
    artifact_roots: Sequence[Path],
    environment: Mapping[str, str],
) -> None:
    validate_project_type(project_type)
    validate_dist_tag(dist_tag)
    validate_publish_credentials(environment)
    resolve_directory(working_directory, [workspace], "working-directory")
    resolved_artifacts = resolve_directory(
        artifact_directory, artifact_roots, "artifact-directory"
    )
    tarballs = validate_tarballs(resolved_artifacts, project_type)
    print(f"Validated {len(tarballs)} pre-built tarball(s) in {resolved_artifacts}")


def resolve_root(name: str, *, required: bool) -> Path | None:
    value = os.environ.get(name)
    if not value:
        if required:
            fail(f"{name} is required")
        return None
    try:
        resolved = Path(value).resolve(strict=True)
    except FileNotFoundError:
        fail(f"{name} does not exist: {value}")
    except (OSError, RuntimeError) as error:
        fail(f"{name} could not be resolved: {value}: {error}")
    if not resolved.is_dir():
        fail(f"{name} is not a directory: {resolved}")
    return resolved


def main(argv: list[str]) -> None:
    parser = ValidationArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--project-type", required=True)
    parser.add_argument("--artifact-directory", required=True)
    parser.add_argument("--dist-tag", default="latest")
    arguments = parser.parse_args(argv[1:])

    workspace = resolve_root("GITHUB_WORKSPACE", required=True)
    assert workspace is not None  # resolve_root exits when a required root is unset
    artifact_roots = [workspace]
    runner_temp = resolve_root("RUNNER_TEMP", required=False)
    if runner_temp is not None and runner_temp != workspace:
        artifact_roots.append(runner_temp)

    validate(
        arguments.working_directory,
        arguments.project_type,
        arguments.artifact_directory,
        arguments.dist_tag,
        workspace=workspace,
        artifact_roots=artifact_roots,
        environment=os.environ,
    )


if __name__ == "__main__":
    main(sys.argv)
