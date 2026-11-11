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
  Maven modules inside the reactor by their artifactId, never an absolute path,
  a parent traversal, a symlink, or an ambiguous name. A name resolves to the
  unique module, at any depth, whose own ``pom.xml`` declares that artifactId,
  whatever its directory is called; only modules declared in the reactor's
  ``<modules>`` are candidates. Resolve-by-identity keeps the published descriptor
  artifactId-keyed while the boundary stays path-safe.
* The selection written for ``mvn -pl`` includes the reactor root (by
  ``:artifactId``) plus every intermediate ancestor of each released module, so
  the Central bundle carries each published POM's full parent chain. Maven
  Central resolves an uploaded POM's inherited metadata (url, license, scm,
  developers) purely from the POMs in the same deployment: without the root and
  the ancestor aggregators every released module reports missing inherited
  metadata and the deployment is rejected. An ancestor without a ``pom.xml``
  fails closed instead of producing a partial bundle.

Any violation exits ``1`` with the stable ``Publish validation failed:`` prefix
and an empty stdout, mirroring the PyPI boundary validator's contract.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Mapping, NoReturn

import re

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
PACKAGE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
RESOLVED_PATH_PATTERN = re.compile(r"[A-Za-z0-9._/-]+\Z")
_MODULE_SEPARATOR = ","


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


def _check_path_components(relative: Path, workspace: Path) -> None:
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            fail(f"symbolic path components are not supported: {current}")


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

    _check_path_components(relative, workspace)

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


def _validate_package_name(entry: str) -> None:
    if "\\" in entry or "/" in entry:
        fail(f"package must be a single reactor module directory: {entry!r}")
    if not PACKAGE_NAME_PATTERN.fullmatch(entry) or entry in {".", ".."}:
        fail(f"package must be a Maven artifactId: {entry!r}")


def _module_artifact_id(pom: Path) -> str | None:
    """Return the artifactId a module pom declares itself, never an inherited one."""

    try:
        root = ElementTree.parse(pom).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    for child in root:
        if child.tag.split("}", 1)[-1] == "artifactId":
            return (child.text or "").strip() or None
    return None


def _reactor_modules(reactor: Path) -> list[Path]:
    """List the module directories reachable from the root pom's ``<modules>``.

    Only declared reactor members are candidates, so fixture or example poms
    that merely sit under the tree can never create a false match.
    """

    root = reactor.resolve()
    found: list[Path] = []
    seen = {root}
    pending = [reactor]
    while pending:
        current = pending.pop()
        try:
            tree = ElementTree.parse(current / "pom.xml").getroot()
        except (ElementTree.ParseError, OSError):
            continue
        for modules in tree.iter():
            if modules.tag.split("}", 1)[-1] != "modules":
                continue
            for module in modules:
                name = (module.text or "").strip()
                if not name or module.tag.split("}", 1)[-1] != "module":
                    continue
                candidate = current / name
                if candidate.name == "pom.xml":
                    candidate = candidate.parent
                pom = candidate / "pom.xml"
                resolved = candidate.resolve()
                if (
                    resolved in seen
                    or not pom.is_file()
                    or pom.is_symlink()
                    or not resolved.is_relative_to(root)
                ):
                    continue
                seen.add(resolved)
                found.append(candidate)
                pending.append(candidate)
    return found


def _resolve_package_module(
    entry: str, reactor: Path, workspace: Path, working_directory: str
) -> Path:
    """Resolve one artifactId to the unique module whose own pom declares it.

    The descriptor keys packages by Maven artifactId, which need not equal the
    module directory name (``clients/`` may declare ``karatetools-clients``).
    Resolution walks the modules declared by the reactor, and requires exactly
    one whose own pom declares the entry as its artifactId. A directory that merely
    shares the entry's name is never accepted without that identity check.
    """

    relative_working = Path(working_directory)
    candidates = [
        module_dir
        for module_dir in _reactor_modules(reactor)
        if _module_artifact_id(module_dir / "pom.xml") == entry
    ]

    if not candidates:
        direct = reactor / entry
        pom = direct / "pom.xml"
        if direct.is_dir() and pom.is_symlink():
            fail(f"symbolic path components are not supported: {pom}")
        if direct.is_dir() and not pom.is_file():
            fail(f"package is not a Maven module: {entry!r}")
        if direct.is_dir():
            fail(
                f"package artifactId was not found in the reactor: {entry!r} "
                f"(directory {entry!r} declares artifactId {_module_artifact_id(pom)!r})"
            )
        fail(f"package artifactId was not found in the reactor: {entry!r}")
    if len(candidates) > 1:
        listed = ", ".join(
            (relative_working / c.relative_to(reactor)).as_posix()
            for c in sorted(candidates)
        )
        fail(f"package artifactId is ambiguous: {entry!r} matches {listed}")
    return resolve_within_workspace(
        f"{working_directory}/{candidates[0].relative_to(reactor).as_posix()}",
        workspace,
        label="package",
    )


def validate_packages(
    packages: str, reactor: Path, workspace: Path, *, project_type: str
) -> tuple[str, ...]:
    entries = [entry.strip() for entry in packages.split(",") if entry.strip()]
    if not entries:
        return ()
    if project_type != "monorepo":
        fail("packages may only be supplied for a monorepo release")
    working_directory = reactor.relative_to(workspace).as_posix()
    resolved: list[str] = [f":{_reactor_root_artifact_id(reactor)}"]
    for entry in entries:
        _validate_package_name(entry)
        module = _resolve_package_module(entry, reactor, workspace, working_directory)
        module_pom = module / "pom.xml"
        if module_pom.is_symlink() or not module_pom.is_file():
            fail(f"package is not a Maven module: {entry!r}")
        relative_parts = module.relative_to(reactor).parts
        for depth in range(1, len(relative_parts)):
            ancestor = Path(*relative_parts[:depth])
            ancestor_pom = reactor / ancestor / "pom.xml"
            if ancestor_pom.is_symlink() or not ancestor_pom.is_file():
                fail(
                    "released module has an ancestor outside the reactor: every "
                    f"intermediate ancestor needs a pom.xml, {ancestor.as_posix()} has none"
                )
            ancestor_path = ancestor.as_posix()
            if ancestor_path not in resolved:
                resolved.append(ancestor_path)
        resolved.append(Path(*relative_parts).as_posix())
    for path in resolved:
        if not RESOLVED_PATH_PATTERN.fullmatch(path.lstrip(":")):
            fail(
                "resolved module directory contains characters that cannot be "
                f"carried to the publish step: {path!r}"
            )
    return tuple(dict.fromkeys(resolved))


def _reactor_root_artifact_id(reactor: Path) -> str:
    pom = reactor / "pom.xml"
    try:
        root = ElementTree.parse(pom).getroot()
    except ElementTree.ParseError as error:
        fail(f"reactor pom.xml is not well-formed XML: {error}")
    artifact = next(
        (child.text for child in root if child.tag.split('}', 1)[-1] == "artifactId"),
        None,
    )
    if artifact is None or not artifact.strip():
        fail("reactor pom.xml does not declare an artifactId")
    artifact = artifact.strip()
    if not PACKAGE_NAME_PATTERN.fullmatch(artifact) or artifact in {".", ".."}:
        fail(
            "reactor artifactId cannot be referenced by the publish step: "
            f"{artifact!r}"
        )
    return artifact


def validate(
    working_directory: str,
    project_type: str,
    strategy: str,
    packages: str,
    auto_publish: str,
    workspace: Path,
    *,
    environment: Mapping[str, str],
    output_path: str | None = None,
) -> None:
    validate_credentials(environment)
    if project_type not in VALID_PROJECT_TYPES:
        supported = ", ".join(sorted(VALID_PROJECT_TYPES))
        fail(f"project-type must be one of: {supported}")
    validate_strategy(strategy)
    validate_boolean("auto-publish", auto_publish)
    reactor = validate_reactor(working_directory, workspace)
    resolved = validate_packages(packages, reactor, workspace, project_type=project_type)

    if output_path:
        _write_resolved_modules(output_path, reactor, resolved)

    scope = "the whole reactor" if not packages.strip() else packages.strip()
    print(
        f"Validated {project_type} publish boundary for {working_directory} "
        f"({scope}) via {strategy}"
    )


def _write_resolved_modules(output_path: str, reactor: Path, resolved: tuple[str, ...]) -> None:
    """Emit the reactor-relative module directory paths for the publish step.

    ``mvn -pl`` accepts relative module paths, and the paths are the validator's
    own resolution result, so Maven and the boundary validator share one module
    identity even when a reactor nests its members.
    """

    destination = Path(output_path)
    if destination.is_symlink() or not destination.parent.is_dir():
        fail(f"package output is not writable inside a real directory: {output_path}")
    destination.write_text(_MODULE_SEPARATOR.join(resolved) + "\n", encoding="utf-8")


def main(argv: list[str]) -> None:
    parser = ValidationArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--project-type", required=True)
    parser.add_argument("--strategy", default=IMPLEMENTED_STRATEGY)
    parser.add_argument("--packages", default="")
    parser.add_argument("--auto-publish", default="true")
    parser.add_argument("--output", default="")
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
        output_path=arguments.output or None,
    )


if __name__ == "__main__":
    main(sys.argv)
