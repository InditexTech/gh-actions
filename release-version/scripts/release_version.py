#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Compute release versions from the release tags reachable from HEAD."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import NoReturn, Sequence, Tuple

ERROR_TITLE = "Release version"
BUMPS = {
    "major": "major",
    "minor": "minor",
    "patch": "patch",
    "hotfix": "patch",
    "multi-hotfix": "patch",
}
TAG_FORMAT_PREFIXES = {"v": "v", "bare": ""}
STRATEGIES = ("single", "locked-step", "independent")
DEV_SUFFIXES = ("-SNAPSHOT", ".dev0", "")
PACKAGE_KEYS = frozenset({"name", "tag-prefix", "declared-version"})
VERSION = r"([0-9]+)\.([0-9]+)\.([0-9]+)"
DECLARED_DEV_SUFFIX = re.compile(r"(?:-SNAPSHOT|\.dev[0-9]+)$")
UNSAFE_PREFIX = re.compile(r"[*?\[\]\\\s\x00-\x1f\x7f]")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

Version = Tuple[int, int, int]


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def fail(message: str) -> NoReturn:
    print(f"::error title={ERROR_TITLE}::{_escape_data(message)}")
    raise SystemExit(1)


class ReleaseVersionArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail(f"invalid arguments: {message}")


@dataclass(frozen=True)
class Package:
    name: str
    tag_prefix: str
    declared_version: str


def parse_version(text: str) -> Version | None:
    match = re.fullmatch(VERSION, text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


def bump(version: Version, release_type: str) -> Version:
    major, minor, patch = version
    kind = BUMPS[release_type]
    if kind == "major":
        return (major + 1, 0, 0)
    if kind == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def declared_release(declared_version: str) -> Version | None:
    """Return the declared version without its development suffix, if strict X.Y.Z."""
    return parse_version(DECLARED_DEV_SUFFIX.sub("", declared_version, count=1))


def reachable_tags(prefix: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "tag", "--merged", "HEAD", "--list", "--", f"{prefix}*"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        fail("git is not available on PATH")
    except subprocess.CalledProcessError as error:
        fail(f"git tag --merged HEAD failed: {error.stderr.strip()}")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def ensure_complete_history() -> None:
    """Fail closed in a shallow clone, whose missing tags would read as a first release."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        fail("git is not available on PATH")
    except subprocess.CalledProcessError as error:
        fail(f"git rev-parse --is-shallow-repository failed: {error.stderr.strip()}")
    answer = completed.stdout.strip()
    if answer == "true":
        fail(
            "the repository is a shallow clone, so release tags may be missing; "
            "check it out with fetch-depth: 0"
        )
    if answer != "false":
        fail(f"cannot tell whether the repository is a shallow clone: {answer!r}")


def highest_release_tag(prefix: str) -> Version | None:
    pattern = re.compile(re.escape(prefix) + VERSION)
    versions = []
    for tag in reachable_tags(prefix):
        match = pattern.fullmatch(tag)
        if match is not None:
            major, minor, patch = (int(part) for part in match.groups())
            versions.append((major, minor, patch))
    return max(versions, default=None)


def parse_packages(raw: str, strategy: str) -> list[Package]:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"packages is not valid JSON: {error}")
    if not isinstance(document, list) or not document:
        fail("packages must be a non-empty JSON list")

    packages = []
    for index, entry in enumerate(document):
        if not isinstance(entry, dict) or set(entry) != PACKAGE_KEYS:
            fail(
                f"packages[{index}] must be an object with exactly the keys "
                "name, tag-prefix and declared-version"
            )
        if not all(isinstance(value, str) for value in entry.values()):
            fail(f"packages[{index}] values must be strings")
        name = entry["name"].strip()
        prefix = entry["tag-prefix"]
        if not name:
            fail(f"packages[{index}].name must not be empty")
        if CONTROL_CHARACTERS.search(entry["name"]):
            fail(f"packages[{index}].name must not contain control characters")
        if UNSAFE_PREFIX.search(prefix) or prefix.startswith("-"):
            fail(f"packages[{index}].tag-prefix is not a literal tag prefix: {prefix!r}")
        packages.append(Package(name, prefix, entry["declared-version"].strip()))

    if strategy in ("single", "locked-step"):
        if len(packages) != 1 or packages[0].tag_prefix:
            fail(f"strategy {strategy} takes exactly one package with an empty tag-prefix")
    else:
        if any(not package.tag_prefix for package in packages):
            fail("strategy independent requires a non-empty tag-prefix for every package")
        if len({package.name for package in packages}) != len(packages):
            fail("package names must be unique")
        if len({package.tag_prefix for package in packages}) != len(packages):
            fail("package tag-prefix values must be unique")
    return packages


def compute_release(
    package: Package,
    *,
    release_type: str,
    format_prefix: str,
    dev_suffix: str,
) -> dict[str, object]:
    prefix = package.tag_prefix or format_prefix
    base = highest_release_tag(prefix)
    declared = declared_release(package.declared_version)
    if base is not None:
        version = bump(base, release_type)
    elif declared is not None:
        version = declared
    else:
        version = bump((0, 0, 0), release_type)
    major, minor, patch = version
    return {
        "package": package.name,
        "base": format_version(base) if base is not None else "",
        "version": format_version(version),
        "tag": f"{prefix}{format_version(version)}",
        "next_dev": f"{major}.{minor}.{patch + 1}{dev_suffix}",
        "first_release": base is None,
        "declared_ahead": declared is not None and declared > version,
    }


def write_outputs(outputs: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        fail("GITHUB_OUTPUT is not set")
    lines = []
    for name, value in outputs.items():
        if "\n" in value or "\r" in value:
            fail(f"output {name} must be a single line")
        lines.append(f"{name}={value}\n")
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.writelines(lines)


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = ReleaseVersionArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--release-type", required=True)
    parser.add_argument("--tag-format", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--packages", required=True)
    parser.add_argument("--dev-suffix", required=True)
    arguments = parser.parse_args(argv)
    if arguments.release_type not in BUMPS:
        fail(
            f"unknown release type {arguments.release_type!r}; "
            f"expected one of {', '.join(BUMPS)}"
        )
    if arguments.tag_format not in TAG_FORMAT_PREFIXES:
        fail(f"tag-format must be 'v' or 'bare', got {arguments.tag_format!r}")
    if arguments.strategy not in STRATEGIES:
        fail(
            f"unknown strategy {arguments.strategy!r}; "
            f"expected one of {', '.join(STRATEGIES)}"
        )
    if arguments.dev_suffix not in DEV_SUFFIXES:
        fail(f"dev-suffix must be '-SNAPSHOT', '.dev0' or empty, got {arguments.dev_suffix!r}")
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    packages = parse_packages(arguments.packages, arguments.strategy)
    releases = [
        compute_release(
            package,
            release_type=arguments.release_type,
            format_prefix=TAG_FORMAT_PREFIXES[arguments.tag_format],
            dev_suffix=arguments.dev_suffix,
        )
        for package in packages
    ]
    ensure_complete_history()
    for record in releases:
        print(
            f"Package {record['package']}: release {record['version']} as tag {record['tag']} "
            f"(base {record['base'] or 'none'}, next development {record['next_dev']})"
        )
    primary = releases[0]
    write_outputs(
        {
            "releases": json.dumps(releases, separators=(",", ":")),
            "version": str(primary["version"]),
            "tag": str(primary["tag"]),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
