# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed validation for a tested shared-action release."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
from pathlib import Path
import re
import subprocess


COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SEMANTIC_VERSION = re.compile(r"^v([1-9][0-9]*)\.[0-9]+\.[0-9]+$")
LEGACY_V1_COMMIT = "789b0957f48f9b0923d64995a8dedc1a3cae60f2"
TRUSTED_MINIMUMS = frozenset(
    {
        "6f82ea4f4c8b5468e026dd51c8e115359fd3bc0c",
        "be83015434bd52adb00e93e36fc61b2deb4c185b",
    }
)


def validate_release_candidate(
    document: object,
    *,
    target_sha: str,
    checked_out_sha: str,
    clean: bool,
    workflow_conclusion: str,
    workflow_event: str,
    workflow_branch: str,
    current_actions: Sequence[str],
    is_ancestor: Callable[[str, str], bool],
) -> dict[str, str]:
    """Validate immutable release metadata and the exact successful main run."""

    if (
        COMMIT_SHA.fullmatch(target_sha) is None
        or checked_out_sha != target_sha
        or not clean
        or workflow_conclusion != "success"
        or workflow_event != "push"
        or workflow_branch != "main"
    ):
        raise ValueError(
            "release candidate is not the exact clean successful main revision"
        )
    if not isinstance(document, Mapping) or set(document) != {
        "schema_version",
        "version",
        "mobile_major",
        "legacy_v1_commit",
        "actions",
        "minimum_hardened_commits",
    }:
        raise ValueError("release metadata has an unsupported shape")
    if document["schema_version"] != 1:
        raise ValueError("release metadata schema is unsupported")
    if document["legacy_v1_commit"] != LEGACY_V1_COMMIT:
        raise ValueError("legacy v1 target is not the reviewed superseded commit")
    version = document["version"]
    mobile_major = document["mobile_major"]
    if not isinstance(version, str) or not isinstance(mobile_major, str):
        raise ValueError("release identities must be strings")
    match = SEMANTIC_VERSION.fullmatch(version)
    if match is None or mobile_major != f"v{match.group(1)}":
        raise ValueError("release version and mobile major are inconsistent")
    actions = document["actions"]
    if (
        not isinstance(actions, list)
        or actions != sorted(set(actions))
        or actions != sorted(current_actions)
    ):
        raise ValueError("release metadata does not match the action catalog")
    minimums = document["minimum_hardened_commits"]
    if (
        not isinstance(minimums, list)
        or any(
            not isinstance(item, str) or COMMIT_SHA.fullmatch(item) is None
            for item in minimums
        )
        or set(minimums) != TRUSTED_MINIMUMS
    ):
        raise ValueError("minimum hardened commits are invalid")
    if any(not is_ancestor(minimum, target_sha) for minimum in minimums):
        raise ValueError("release candidate predates a hardened action revision")
    if any(not is_ancestor(LEGACY_V1_COMMIT, minimum) for minimum in minimums):
        raise ValueError("legacy v1 does not predate every hardened action revision")
    return {
        "mobile_major": mobile_major,
        "target_sha": target_sha,
        "version": version,
    }


def _is_ancestor(minimum: str, target: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", minimum, target],
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise ValueError("cannot resolve hardened release ancestry")
    return result.returncode == 0


def _git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--workflow-conclusion", required=True)
    parser.add_argument("--workflow-event", required=True)
    parser.add_argument("--workflow-branch", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(arguments)
    document = json.loads(
        Path(".github/action-release.json").read_text(encoding="utf-8")
    )
    result = validate_release_candidate(
        document,
        target_sha=args.target_sha,
        checked_out_sha=_git_output("rev-parse", "HEAD"),
        clean=not _git_output("status", "--porcelain"),
        workflow_conclusion=args.workflow_conclusion,
        workflow_event=args.workflow_event,
        workflow_branch=args.workflow_branch,
        current_actions=sorted(
            path.parent.name for path in Path(".").glob("*/action.yml")
        ),
        is_ancestor=_is_ancestor,
    )
    with args.github_output.open("a", encoding="utf-8") as output:
        for name, value in result.items():
            output.write(f"{name}={value}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
