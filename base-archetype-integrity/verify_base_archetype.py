"""Validate a base-archetype checkout without executing any candidate content."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Mapping, Sequence


SHA_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*([^\s#]+)", re.MULTILINE)
CHECKOUT_V7_REFERENCE = (
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
)
CHECKOUT_USES_LINE = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(actions/checkout@[^\s#]+)"
)
STEP_START = re.compile(r"^\s*-\s+")
PERSIST_CREDENTIALS_FALSE = re.compile(
    r"^\s*persist-credentials\s*:\s*(?:false|['\"]false['\"])\s*(?:#.*)?$"
)
CANONICAL_INTEGRITY_WORKFLOW = re.compile(
    r"^InditexTech/gh-actions/\.github/workflows/"
    r"verify-base-archetype\.yml@[0-9a-f]{40}$"
)
COPYRIGHT_YEAR = re.compile(r"(?i)copyright[^\r\n]*\b(?:19|20)\d{2}\b")
REUSE_PACKAGE_METADATA = re.compile(
    r"(?im)^\s*(?:name|description|authors|repository|homepage)\s*="
    r"|^\s*\[\s*package\s*\]"
)


def collect_files(source_root: Path) -> dict[str, bytes]:
    """Return regular candidate files keyed by normalized relative path.

    Symlinks are rejected so validation cannot read data outside the checkout.
    Candidate files are only read as bytes and are never executed or imported.
    """

    root = source_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {source_root}")

    files: dict[str, bytes] = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directories):
            if name == ".git":
                continue
            entry = directory_path / name
            if entry.is_symlink():
                raise ValueError(
                    f"candidate contains a symlink: {entry.relative_to(root)}"
                )
            retained_directories.append(name)
        directories[:] = retained_directories
        for name in sorted(names):
            entry = directory_path / name
            mode = entry.lstat().st_mode
            relative = entry.relative_to(root).as_posix()
            if stat.S_ISLNK(mode):
                raise ValueError(f"candidate contains a symlink: {relative}")
            if not stat.S_ISREG(mode):
                continue
            files[relative] = entry.read_bytes()
    return files


def development_branch(default_branch: str, base_branch: str) -> str | None:
    """Map a pull request base branch to its development branch, if applicable."""

    if base_branch == default_branch:
        return "develop"
    prefix = f"{default_branch}-"
    if base_branch.startswith(prefix):
        suffix = base_branch.removeprefix(prefix)
        if suffix:
            return f"develop-{suffix}"
    return None


def validate_branch_mapping(contract: Mapping[str, object]) -> list[str]:
    """Validate development-branch examples kept in the JSON contract."""

    errors: list[str] = []
    cases = contract.get("branch_mapping_cases")
    if not isinstance(cases, list) or not cases:
        return ["contract branch_mapping_cases must be a non-empty list"]
    visibilities: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append(f"branch_mapping_cases[{index}] must be an object")
            continue
        visibility = case.get("visibility")
        default_branch = case.get("default_branch")
        base_branch = case.get("base_branch")
        expected_branch = case.get("expected_development_branch")
        if not all(
            isinstance(value, str) and value
            for value in (visibility, default_branch, base_branch)
        ):
            errors.append(f"branch_mapping_cases[{index}] has invalid values")
            continue
        if visibility not in {"public", "private"}:
            errors.append(f"branch_mapping_cases[{index}] has invalid visibility")
            continue
        if expected_branch is not None and (
            not isinstance(expected_branch, str) or not expected_branch
        ):
            errors.append(
                f"branch_mapping_cases[{index}] has an invalid expected development branch"
            )
            continue
        visibilities.add(visibility)
        actual_branch = development_branch(default_branch, base_branch)
        if actual_branch != expected_branch:
            errors.append(
                f"branch_mapping_cases[{index}] expected {expected_branch!r}, "
                f"got {actual_branch!r}"
            )
    if visibilities != {"public", "private"}:
        errors.append("branch_mapping_cases must cover public and private repositories")
    return errors


def validate_files(
    files: Mapping[str, bytes],
    contract: Mapping[str, object],
    *,
    year: int,
) -> list[str]:
    """Return all policy violations for a collected candidate file mapping."""

    errors = _validate_contract_shape(contract)
    if errors:
        return errors

    required_groups = (
        "create_only_assets",
        "sync_governed_consumer_assets",
        "base_self_only_assets",
    )
    for group in required_groups:
        for path in _string_list(contract, group):
            if path not in files:
                errors.append(f"missing required {group} file: {path}")

    for path in _string_list(contract, "forbidden_base_paths"):
        if path in files:
            errors.append(f"deprecated base tooling must not exist: {path}")

    errors.extend(validate_branch_mapping(contract))
    errors.extend(_validate_workflows(files, contract))
    errors.extend(_validate_year_templates(files, contract, year))
    errors.extend(_validate_consumer_identity(files, contract))
    errors.extend(_validate_reuse_config(files))
    return errors


def _validate_contract_shape(contract: Mapping[str, object]) -> list[str]:
    if contract.get("schema_version") != 1:
        return ["contract schema_version must be 1"]
    errors: list[str] = []
    for name in (
        "create_only_assets",
        "sync_governed_consumer_assets",
        "base_self_only_assets",
        "forbidden_base_paths",
        "year_templated_assets",
    ):
        values = contract.get(name)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
            or len(values) != len(set(values))
        ):
            errors.append(f"contract {name} must be a unique non-empty string list")
    return errors


def _string_list(contract: Mapping[str, object], name: str) -> list[str]:
    values = contract[name]
    assert isinstance(values, list)
    assert all(isinstance(value, str) for value in values)
    return list(values)


def _validate_workflows(
    files: Mapping[str, bytes],
    contract: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    workflow_paths = sorted(
        path
        for path in files
        if path.startswith(".github/workflows/") and path.endswith(".yml")
    )
    for path in workflow_paths:
        text = _decode_text(path, files[path], errors)
        if text is None:
            continue
        for reference in USES_LINE.findall(text):
            normalized = reference.strip("\"'")
            if not normalized.startswith("./") and not SHA_PIN.fullmatch(normalized):
                errors.append(
                    f"{path}: external uses reference is not a 40-character SHA: "
                    f"{reference}"
                )
        errors.extend(_validate_checkout_hardening(path, text))

    for name in ("pr-verify.yml", "push-verify.yml"):
        path = f".github/workflows/{name}"
        if path not in files:
            continue
        text = _decode_text(path, files[path], errors)
        if text is not None and re.search(
            r"verify-archetype|archetype-integrity", text, flags=re.IGNORECASE
        ):
            errors.append(f"{path}: generic consumer workflow leaks base-only validation")

    sync_path = ".github/workflows/sync-to-develop.yml"
    if sync_path in files:
        text = _decode_text(sync_path, files[sync_path], errors)
        if text is not None:
            errors.extend(_validate_sync_workflow(text))

    integrity_path = ".github/workflows/archetype-integrity.yml"
    if integrity_path in files:
        text = _decode_text(integrity_path, files[integrity_path], errors)
        if text is not None:
            errors.extend(_validate_integrity_workflow(text))
    return errors


def _validate_checkout_hardening(path: str, text: str) -> list[str]:
    """Require the hardened checkout release and ephemeral credentials."""

    errors: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        reference = CHECKOUT_USES_LINE.match(line)
        if reference is None:
            continue
        if reference.group(1) != CHECKOUT_V7_REFERENCE:
            errors.append(f"{path}: checkout must use the approved v7 SHA pin")

        step_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            if STEP_START.match(candidate):
                break
            step_lines.append(candidate)
        if not any(PERSIST_CREDENTIALS_FALSE.match(item) for item in step_lines):
            errors.append(f"{path}: checkout must set persist-credentials: false")
    return errors


def _validate_integrity_workflow(text: str) -> list[str]:
    references = (reference.strip("\"'") for reference in USES_LINE.findall(text))
    if any(CANONICAL_INTEGRITY_WORKFLOW.fullmatch(reference) for reference in references):
        return []
    return [
        "archetype-integrity.yml must use the canonical SHA-pinned reusable workflow"
    ]


def _validate_sync_workflow(text: str) -> list[str]:
    errors: list[str] = []
    event_match = re.search(
        r"(?ms)^\s*pull_request_target\s*:(.*?)(?=^\S|\Z)", text
    )
    if event_match is None:
        errors.append("sync-to-develop.yml must use pull_request_target")
    else:
        event_body = event_match.group(1)
        if not re.search(
            r"(?im)^\s*-\s*closed\s*$|types\s*:\s*\[\s*closed\s*\]",
            event_body,
        ):
            errors.append("sync-to-develop.yml must run only for closed pull requests")
        if re.search(r"(?m)^\s*branches(?:-ignore)?\s*:", event_body):
            errors.append("sync-to-develop.yml must not statically filter branches")
    if not re.search(
        r"(?m)^\s*DEFAULT_BRANCH\s*:\s*\$\{\{\s*github\.event\.repository\.default_branch\s*\}\}",
        text,
    ):
        errors.append("sync-to-develop.yml must set DEFAULT_BRANCH from repository context")
    if not re.search(
        r"(?m)^\s*ref\s*:\s*\$\{\{\s*github\.event\.pull_request\.base\.ref\s*\}\}",
        text,
    ):
        errors.append(
            "sync-to-develop.yml must check out the pull request base branch"
        )
    required_conditions = {
        "sync-to-develop.yml must require a merged pull request": (
            r"github\.event\.pull_request\.merged"
        ),
        "sync-to-develop.yml must require the git-flow development flow": (
            r"vars\.DEVELOPMENT_FLOW\s*==\s*['\"]git-flow['\"]"
        ),
        "sync-to-develop.yml must compare the base branch to the default branch": (
            r"github\.event\.pull_request\.base\.ref\s*==\s*"
            r"github\.event\.repository\.default_branch"
        ),
        "sync-to-develop.yml must map default-suffixed base branches": (
            r"startsWith\(\s*github\.event\.pull_request\.base\.ref\s*,\s*"
            r"format\(\s*['\"]\{0\}-['\"]\s*,\s*"
            r"github\.event\.repository\.default_branch\s*\)\s*\)"
        ),
    }
    for message, condition in required_conditions.items():
        if re.search(condition, text) is None:
            errors.append(message)
    unsafe_target_patterns = {
        "sync-to-develop.yml must not reference pull request head data": (
            r"github\.event\.pull_request\.head\b"
        ),
        "sync-to-develop.yml must not use pull request refs": r"refs/pull/",
        "sync-to-develop.yml must not enable unsafe PR checkout": (
            r"allow-unsafe-pr-checkout"
        ),
        "sync-to-develop.yml must not use self-hosted runners": r"(?i)\bself-hosted\b",
    }
    for message, pattern in unsafe_target_patterns.items():
        if re.search(pattern, text):
            errors.append(message)
    if re.search(r"(?i)\bmain\b", text):
        errors.append("sync-to-develop.yml must not hardcode a main branch role")
    return errors


def _validate_year_templates(
    files: Mapping[str, bytes],
    contract: Mapping[str, object],
    year: int,
) -> list[str]:
    errors: list[str] = []
    token = "{{ CURRENT_YEAR }}"
    for path in _string_list(contract, "year_templated_assets"):
        if path not in files:
            continue
        text = _decode_text(path, files[path], errors)
        if text is None:
            continue
        if token not in text:
            errors.append(f"{path}: missing literal {token}")
            continue
        rendered = text.replace(token, str(year))
        if COPYRIGHT_YEAR.search(rendered) is None:
            errors.append(f"{path}: rendered template lacks a valid copyright year")
    return errors


def _validate_consumer_identity(
    files: Mapping[str, bytes],
    contract: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    for path in _string_list(contract, "sync_governed_consumer_assets"):
        if path not in files:
            continue
        text = _decode_text(path, files[path], errors)
        if text is not None and re.search(
            r"base-archetype|@InditexTech/base-archetype-maintainers",
            text,
            flags=re.IGNORECASE,
        ):
            errors.append(f"{path}: consumer asset mentions base-archetype identity")
    return errors


def _validate_reuse_config(files: Mapping[str, bytes]) -> list[str]:
    path = "REUSE.toml"
    if path not in files:
        return []
    errors: list[str] = []
    text = _decode_text(path, files[path], errors)
    if text is None:
        return errors
    if REUSE_PACKAGE_METADATA.search(text):
        errors.append("REUSE.toml must not contain package metadata")
    if "base-archetype" in text.casefold():
        errors.append("REUSE.toml must not contain base-archetype identity")
    return errors


def _decode_text(path: str, content: bytes, errors: list[str]) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"{path}: must be valid UTF-8 text")
        return None


def _load_contract(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON contract {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise ValueError("contract root must be an object")
    return value


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the composite action entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=".", type=Path)
    parser.add_argument(
        "--contract",
        default=Path(__file__).with_name("contract.json"),
        type=Path,
    )
    parser.add_argument("--year", default=datetime.now(timezone.utc).year, type=int)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate the candidate tree and print every violation to stderr."""

    args = parse_args(arguments)
    if not 1900 <= args.year <= 9999:
        print("--year must be a four-digit calendar year", file=sys.stderr)
        return 2
    try:
        contract = _load_contract(args.contract)
        files = collect_files(args.source_root)
    except (OSError, ValueError) as error:
        print(f"verify-base-archetype: {error}", file=sys.stderr)
        return 2
    errors = validate_files(files, contract, year=args.year)
    if errors:
        print(
            "\n".join(f"verify-base-archetype: {error}" for error in errors),
            file=sys.stderr,
        )
        return 1
    print("verify-base-archetype: source tree satisfies the contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
