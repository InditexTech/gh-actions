"""Exercise the actual sync-to-develop shell blocks in isolated repositories."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest


SYSTEM_GIT = Path("/usr/bin/git")
GIT = str(SYSTEM_GIT) if SYSTEM_GIT.is_file() else shutil.which("git")
STEP_NAME = re.compile(r"^(?P<indent>\s*)-\s+name:\s*(?P<name>.+?)\s*$")
RUN_BLOCK = re.compile(r"^(?P<indent>\s*)run:\s*\|\s*$")
WORKFLOW_PATH: Path | None = None


class _RetryingTemporaryDirectory(tempfile.TemporaryDirectory[str]):
    """Clean up fixture repositories after Git's asynchronous housekeeping ends."""

    def cleanup(self) -> None:
        try:
            super().cleanup()
            return
        except OSError:
            pass
        for _ in range(10):
            time.sleep(0.1)
            try:
                shutil.rmtree(self.name)
                return
            except OSError:
                continue
        shutil.rmtree(self.name)


@dataclass(frozen=True)
class RepositoryFixture:
    """A bare origin and a writable seed checkout for one shell scenario."""

    origin: Path
    seed: Path
    base_branch: str
    develop_branch: str


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a host command while retaining diagnostics for failed assertions."""

    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _git(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run the real Git binary, never a fixture stub."""

    if GIT is None:
        raise RuntimeError("git is required to exercise sync-to-develop.yml")
    return _run([GIT, *arguments], cwd=cwd, check=check)


def _extract_run_block(workflow: str, step_name: str) -> str:
    """Extract one literal shell block from a named workflow step."""

    lines = workflow.splitlines()
    step_index: int | None = None
    step_indent = 0
    for index, line in enumerate(lines):
        match = STEP_NAME.match(line)
        if match and match.group("name").strip("\"'") == step_name:
            step_index = index
            step_indent = len(match.group("indent"))
            break
    if step_index is None:
        raise ValueError(f"workflow is missing step {step_name!r}")

    run_index: int | None = None
    run_indent = 0
    for index in range(step_index + 1, len(lines)):
        line = lines[index]
        step_match = STEP_NAME.match(line)
        if step_match and len(step_match.group("indent")) <= step_indent:
            break
        run_match = RUN_BLOCK.match(line)
        if run_match:
            run_index = index
            run_indent = len(run_match.group("indent"))
            break
    if run_index is None:
        raise ValueError(f"workflow step {step_name!r} does not contain a literal run block")

    script_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        script_lines.append(line)
    script = textwrap.dedent("\n".join(script_lines)).strip()
    if not script:
        raise ValueError(f"workflow step {step_name!r} has an empty run block")
    return f"{script}\n"


def _write(path: Path, content: str) -> None:
    """Write a fixture file with an explicit UTF-8 encoding."""

    path.write_text(content, encoding="utf-8")


def _commit(seed: Path, path: str, content: str, message: str) -> str:
    """Create one deterministic commit in the seed checkout."""

    target = seed / path
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, content)
    _git(["add", path], cwd=seed)
    _git(["commit", "-m", message], cwd=seed)
    return _git(["rev-parse", "HEAD"], cwd=seed).stdout.strip()


def _push(seed: Path, branch: str, *, force: bool = False) -> None:
    """Push one branch to the bare origin."""

    arguments = ["push"]
    if force:
        arguments.append("--force")
    arguments.extend(["origin", f"HEAD:refs/heads/{branch}"])
    _git(arguments, cwd=seed)


def _setup_repository(
    root: Path,
    *,
    default_branch: str,
    base_branch: str,
    develop_branch: str,
    include_develop: bool = True,
    develop_contains_base: bool = False,
) -> RepositoryFixture:
    """Create a two-branch remote in the state expected by the workflow."""

    origin = root / "origin.git"
    seed = root / "seed"
    _git(["init", "--bare", str(origin)])
    _git(["--git-dir", str(origin), "config", "maintenance.auto", "false"])
    _git(["init", str(seed)])
    _git(["config", "user.name", "Sync fixture"], cwd=seed)
    _git(["config", "user.email", "sync-fixture@example.invalid"], cwd=seed)
    _git(["config", "maintenance.auto", "false"], cwd=seed)
    _git(["checkout", "-b", default_branch], cwd=seed)
    initial = _commit(seed, "README.md", "initial\n", "Initial fixture")
    _git(["remote", "add", "origin", str(origin)], cwd=seed)
    _push(seed, default_branch)

    if base_branch != default_branch:
        _git(["checkout", "-b", base_branch, initial], cwd=seed)
    _commit(seed, "base.txt", "base\n", "Advance base branch")
    _push(seed, base_branch)

    if include_develop:
        if develop_contains_base:
            _git(["checkout", "-B", develop_branch, base_branch], cwd=seed)
        else:
            _git(["checkout", "-B", develop_branch, initial], cwd=seed)
            _commit(seed, "develop.txt", "develop\n", "Advance develop branch")
        _push(seed, develop_branch, force=True)

    return RepositoryFixture(origin, seed, base_branch, develop_branch)


def _clone_base(root: Path, fixture: RepositoryFixture, name: str) -> Path:
    """Clone the exact base branch as Actions checkout does."""

    checkout = root / name
    _git(["clone", "--branch", fixture.base_branch, str(fixture.origin), str(checkout)])
    _git(["config", "maintenance.auto", "false"], cwd=checkout)
    return checkout


def _remote_head(fixture: RepositoryFixture, branch: str) -> str:
    """Return the current remote branch object ID."""

    return _git(
        ["--git-dir", str(fixture.origin), "rev-parse", f"refs/heads/{branch}"]
    ).stdout.strip()


def _advance_base(fixture: RepositoryFixture, path: str, content: str) -> str:
    """Advance the source branch after a sync branch was already created."""

    _git(["checkout", fixture.base_branch], cwd=fixture.seed)
    commit = _commit(fixture.seed, path, content, "Advance base branch again")
    _push(fixture.seed, fixture.base_branch)
    return commit


def _create_existing_sync(
    fixture: RepositoryFixture,
    sync_branch: str,
    *,
    merge_resolution: bool = False,
    conflicting_path: str | None = None,
) -> None:
    """Create a remote sync branch with either a merge or a normal commit."""

    _git(["checkout", "-B", sync_branch, fixture.base_branch], cwd=fixture.seed)
    if merge_resolution:
        resolution_branch = "fixture-resolution"
        _git(["checkout", "-b", resolution_branch], cwd=fixture.seed)
        _commit(
            fixture.seed,
            "resolution.txt",
            "resolution\n",
            "Create conflict resolution commit",
        )
        _git(["checkout", sync_branch], cwd=fixture.seed)
        _git(
            ["merge", "--no-ff", resolution_branch, "-m", "Preserve resolution merge"],
            cwd=fixture.seed,
        )
    else:
        _commit(
            fixture.seed,
            conflicting_path or "sync.txt",
            "sync\n",
            "Advance synchronization branch",
        )
    _push(fixture.seed, sync_branch)


def _write_fake_gh(stub_directory: Path) -> Path:
    """Install a deterministic GitHub CLI stub used only by shell fixtures."""

    executable = stub_directory / "gh"
    _write(
        executable,
        """#!/bin/sh
set -eu
first="${1:-}"
second="${2:-}"
printf '%s\n' "$*" >> "${GH_STUB_LOG:?}"
case "$first:$second" in
  auth:setup-git)
    exit 0
    ;;
  pr:list)
    printf '%s\n' "${FAKE_EXISTING_PR:-}"
    exit 0
    ;;
  label:list)
    printf '%s\n' "${FAKE_HAS_LABEL:-false}"
    exit 0
    ;;
  pr:create)
    [ "${FAKE_GH_FAILURE:-}" != "create" ] || exit 72
    exit 0
    ;;
  pr:edit)
    [ "${FAKE_GH_FAILURE:-}" != "edit" ] || exit 73
    exit 0
    ;;
  pr:comment)
    [ "${FAKE_GH_FAILURE:-}" != "comment" ] || exit 74
    exit 0
    ;;
  *)
    echo "unexpected gh command: $*" >&2
    exit 75
    ;;
esac
""",
    )
    executable.chmod(0o755)
    return executable


def _write_racing_git(
    stub_directory: Path,
    fixture: RepositoryFixture,
    sync_branch: str,
    replacement: str,
) -> None:
    """Move the remote branch immediately before force-with-lease is evaluated."""

    executable = stub_directory / "git"
    _write(
        executable,
        f"""#!/bin/sh
set -eu
if [ "${{1:-}}" = "push" ]; then
  "$REAL_GIT" --git-dir="{fixture.origin}" update-ref "refs/heads/{sync_branch}" "{replacement}"
fi
exec "$REAL_GIT" "$@"
""",
    )
    executable.chmod(0o755)


def _environment(
    root: Path,
    stubs: Path,
    *,
    base_branch: str,
    default_branch: str,
    output: Path,
    overrides: Mapping[str, str] = {},
) -> dict[str, str]:
    """Return a scrubbed environment with no Actions credential or workspace."""

    if GIT is None:
        raise RuntimeError("git is required to exercise sync-to-develop.yml")
    home = root / "home"
    home.mkdir(exist_ok=True)
    log = root / "gh.log"
    log.touch()
    environment = {
        "APP_SLUG": "governance-fixture",
        "BASE_BRANCH": base_branch,
        "DEFAULT_BRANCH": default_branch,
        "GH_TOKEN": "fixture-token",
        "GH_STUB_LOG": str(log),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "InditexTech/consumer",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_EDITOR": "true",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "PATH": f"{stubs}:{Path(GIT).parent}:{os.defpath}",
        "REAL_GIT": GIT,
        "SOURCE_PULL_REQUEST": "42",
    }
    environment.update(overrides)
    return environment


def _run_shell(
    root: Path,
    checkout: Path,
    block: str,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run one extracted block in an isolated checkout and environment."""

    script = root / "run.sh"
    _write(script, block)
    script.chmod(0o755)
    return _run(["/bin/bash", str(script)], cwd=checkout, environment=environment, check=False)


def _outputs(path: Path) -> dict[str, str]:
    """Parse the simple key-value writes used by the workflow."""

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


class SyncWorkflowBehaviorTests(unittest.TestCase):
    """Exercise branch, race, and GitHub CLI behavior from the actual YAML."""

    @classmethod
    def setUpClass(cls) -> None:
        if WORKFLOW_PATH is None:
            raise RuntimeError("workflow path was not configured")
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.prepare = _extract_run_block(workflow, "Prepare sync branch")
        cls.upsert = _extract_run_block(workflow, "Create or update sync pull request")
        cls.comment = _extract_run_block(
            workflow,
            "Comment on source pull request after failure",
        )

    def _prepare(
        self,
        fixture: RepositoryFixture,
        root: Path,
        *,
        default_branch: str,
        overrides: Mapping[str, str] = {},
        checkout_name: str = "checkout",
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        stubs = root / "stubs"
        stubs.mkdir(exist_ok=True)
        _write_fake_gh(stubs)
        output = root / "output"
        _write(output, "")
        checkout = _clone_base(root, fixture, checkout_name)
        environment = _environment(
            root,
            stubs,
            base_branch=fixture.base_branch,
            default_branch=default_branch,
            output=output,
            overrides=overrides,
        )
        completed = _run_shell(root, checkout, self.prepare, environment)
        return completed, _outputs(output)

    def _assert_success(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    def test_empty_suffix_is_skipped(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main-",
                develop_branch="develop-",
                include_develop=False,
            )
            completed, outputs = self._prepare(fixture, root, default_branch="main")
            self._assert_success(completed)
            self.assertEqual(outputs, {"should_sync": "false"})

    def test_missing_development_branch_is_skipped(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
                include_develop=False,
            )
            completed, outputs = self._prepare(fixture, root, default_branch="main")
            self._assert_success(completed)
            self.assertEqual(outputs, {"should_sync": "false"})

    def test_development_branch_already_contains_base_is_skipped(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
                develop_contains_base=True,
            )
            completed, outputs = self._prepare(fixture, root, default_branch="main")
            self._assert_success(completed)
            self.assertEqual(outputs, {"should_sync": "false"})

    def test_creates_sync_branch_from_base(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
            )
            completed, outputs = self._prepare(fixture, root, default_branch="main")
            self._assert_success(completed)
            sync_branch = "automated/sync-from-main-to-develop"
            self.assertEqual(outputs["should_sync"], "true")
            self.assertEqual(outputs["sync_branch"], sync_branch)
            self.assertEqual(
                _remote_head(fixture, sync_branch),
                _remote_head(fixture, fixture.base_branch),
            )

    def test_existing_sync_branch_rebases_and_preserves_merges(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
            )
            sync_branch = "automated/sync-from-main-to-develop"
            _create_existing_sync(fixture, sync_branch, merge_resolution=True)
            base_head = _advance_base(fixture, "next.txt", "next\n")
            completed, outputs = self._prepare(fixture, root, default_branch="main")
            self._assert_success(completed)
            self.assertEqual(outputs["should_sync"], "true")
            sync_head = _remote_head(fixture, sync_branch)
            self.assertEqual(
                _git(
                    [
                        "--git-dir",
                        str(fixture.origin),
                        "merge-base",
                        "--is-ancestor",
                        base_head,
                        sync_head,
                    ],
                    check=False,
                ).returncode,
                0,
            )
            merges = _git(
                ["--git-dir", str(fixture.origin), "rev-list", "--merges", sync_head]
            ).stdout.splitlines()
            self.assertTrue(merges)

    def test_rebase_conflict_does_not_push_sync_branch(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
            )
            sync_branch = "automated/sync-from-main-to-develop"
            _create_existing_sync(
                fixture,
                sync_branch,
                conflicting_path="shared.txt",
            )
            before = _remote_head(fixture, sync_branch)
            _advance_base(fixture, "shared.txt", "base change\n")
            completed, _ = self._prepare(fixture, root, default_branch="main")
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(_remote_head(fixture, sync_branch), before)

    def test_force_with_lease_rejects_a_concurrent_remote_update(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
            )
            sync_branch = "automated/sync-from-main-to-develop"
            _create_existing_sync(fixture, sync_branch)
            _advance_base(fixture, "next.txt", "next\n")
            _git(["checkout", "-B", "racer", fixture.base_branch], cwd=fixture.seed)
            racer = _commit(fixture.seed, "racer.txt", "racer\n", "Race update")
            _push(fixture.seed, "racer")

            stubs = root / "stubs"
            stubs.mkdir()
            _write_fake_gh(stubs)
            _write_racing_git(stubs, fixture, sync_branch, racer)
            output = root / "output"
            output.touch()
            checkout = _clone_base(root, fixture, "checkout")
            environment = _environment(
                root,
                stubs,
                base_branch=fixture.base_branch,
                default_branch="main",
                output=output,
            )
            completed = _run_shell(root, checkout, self.prepare, environment)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(_remote_head(fixture, sync_branch), racer)

    def test_repeated_sync_is_idempotent(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="main",
                base_branch="main",
                develop_branch="develop",
            )
            first, first_outputs = self._prepare(fixture, root, default_branch="main")
            self._assert_success(first)
            sync_branch = first_outputs["sync_branch"]
            before = _remote_head(fixture, sync_branch)
            second, second_outputs = self._prepare(
                fixture,
                root,
                default_branch="main",
                checkout_name="checkout-second",
            )
            self._assert_success(second)
            self.assertEqual(second_outputs["should_sync"], "true")
            self.assertEqual(_remote_head(fixture, sync_branch), before)

    def test_valid_suffix_with_slashes_and_dots_is_not_split(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _setup_repository(
                root,
                default_branch="trunk",
                base_branch="trunk-2026.08/rc.1",
                develop_branch="develop-2026.08/rc.1",
            )
            completed, outputs = self._prepare(fixture, root, default_branch="trunk")
            self._assert_success(completed)
            self.assertEqual(outputs["develop_branch"], "develop-2026.08/rc.1")
            self.assertEqual(
                outputs["sync_branch"],
                "automated/sync-from-trunk-2026.08/rc.1-to-develop-2026.08/rc.1",
            )

    def _run_upsert(
        self,
        root: Path,
        *,
        existing_pr: str,
        has_label: str,
        failure: str = "",
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        stubs = root / "stubs"
        stubs.mkdir()
        _write_fake_gh(stubs)
        output = root / "output"
        output.touch()
        environment = _environment(
            root,
            stubs,
            base_branch="main",
            default_branch="main",
            output=output,
            overrides={
                "DEVELOP_BRANCH": "develop",
                "FAKE_EXISTING_PR": existing_pr,
                "FAKE_GH_FAILURE": failure,
                "FAKE_HAS_LABEL": has_label,
                "SYNC_BRANCH": "automated/sync-from-main-to-develop",
            },
        )
        completed = _run_shell(root, root, self.upsert, environment)
        return completed, (root / "gh.log").read_text(encoding="utf-8")

    def test_existing_internal_sync_pull_request_is_updated_and_labeled(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            completed, log = self._run_upsert(
                Path(temporary),
                existing_pr="101",
                has_label="true",
            )
            self._assert_success(completed)
            self.assertIn("pr edit 101", log)
            self.assertIn("--add-label kind/internal", log)
            self.assertNotIn("pr create", log)

    def test_missing_or_cross_repository_sync_pull_request_is_created(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            completed, log = self._run_upsert(
                Path(temporary),
                existing_pr="",
                has_label="true",
            )
            self._assert_success(completed)
            self.assertIn("pr create", log)
            self.assertIn("--label kind/internal", log)

    def test_missing_internal_label_warns_without_blocking_pull_request_creation(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            completed, log = self._run_upsert(
                Path(temporary),
                existing_pr="",
                has_label="false",
            )
            self._assert_success(completed)
            self.assertIn("Missing label", completed.stdout)
            self.assertIn("pr create", log)
            self.assertNotIn("--label kind/internal", log)

    def test_github_cli_failures_propagate(self) -> None:
        for existing_pr, failure in (("", "create"), ("101", "edit")):
            with self.subTest(existing_pr=existing_pr, failure=failure):
                with _RetryingTemporaryDirectory() as temporary:
                    completed, _ = self._run_upsert(
                        Path(temporary),
                        existing_pr=existing_pr,
                        has_label="true",
                        failure=failure,
                    )
                    self.assertNotEqual(completed.returncode, 0)

    def test_failure_comment_errors_are_not_silenced(self) -> None:
        with _RetryingTemporaryDirectory() as temporary:
            root = Path(temporary)
            stubs = root / "stubs"
            stubs.mkdir()
            _write_fake_gh(stubs)
            output = root / "output"
            output.touch()
            environment = _environment(
                root,
                stubs,
                base_branch="main",
                default_branch="main",
                output=output,
                overrides={"FAKE_GH_FAILURE": "comment"},
            )
            completed = _run_shell(root, root, self.comment, environment)
            self.assertNotEqual(completed.returncode, 0)


def parse_args() -> argparse.Namespace:
    """Parse the candidate workflow path passed by the composite action."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Run the hermetic suite against the extracted candidate shell blocks."""

    global WORKFLOW_PATH
    arguments = parse_args()
    WORKFLOW_PATH = arguments.workflow.resolve()
    if not WORKFLOW_PATH.is_file():
        raise ValueError(f"workflow does not exist: {WORKFLOW_PATH}")
    program = unittest.main(module=__name__, argv=["verify_sync_to_develop.py"], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
