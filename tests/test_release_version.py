# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Behavior tests for the release-version computation against real git repositories."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release-version" / "scripts" / "release_version.py"

GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Release Version Test",
    "GIT_AUTHOR_EMAIL": "release-version@example.invalid",
    "GIT_COMMITTER_NAME": "Release Version Test",
    "GIT_COMMITTER_EMAIL": "release-version@example.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


def _environment(**extra: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key != "GITHUB_OUTPUT"
    }
    environment.update(GIT_ENVIRONMENT)
    environment.update(extra)
    return environment


class GitRepository:
    """A throwaway repository whose history and tags each test builds explicitly."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._commits = 0
        self.git("init", "--quiet", "--initial-branch=main")

    def git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.path,
            check=True,
            capture_output=True,
            text=True,
            env=_environment(),
        )
        return completed.stdout.strip()

    def commit(self) -> str:
        self._commits += 1
        self.git("commit", "--quiet", "--allow-empty", "-m", f"change {self._commits}")
        return self.git("rev-parse", "HEAD")

    def tag(self, *names: str, annotated: bool = False) -> None:
        for name in names:
            if annotated:
                self.git("tag", "--annotate", "--message", f"release {name}", name)
            else:
                self.git("tag", name)

    def branch(self, name: str) -> None:
        self.git("branch", name)

    def checkout(self, name: str) -> None:
        self.git("checkout", "--quiet", name)

    def merge(self, name: str) -> None:
        self.git("merge", "--quiet", "--no-ff", "-m", f"merge {name}", name)


def package(name: str = "demo", prefix: str = "", declared: str = "") -> dict[str, str]:
    return {"name": name, "tag-prefix": prefix, "declared-version": declared}


@dataclass(frozen=True)
class ActionResult:
    returncode: int
    stdout: str
    stderr: str
    outputs: dict[str, str]

    @property
    def releases(self) -> list[dict[str, object]]:
        return json.loads(self.outputs["releases"])

    def by_package(self) -> dict[str, dict[str, object]]:
        return {str(record["package"]): record for record in self.releases}


def _read_outputs(path: Path) -> dict[str, str]:
    """Parse a GITHUB_OUTPUT file in either the `name=value` or the heredoc form."""
    outputs: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        heredoc = line.find("<<")
        equals = line.find("=")
        if heredoc != -1 and (equals == -1 or heredoc < equals):
            name, delimiter = line.split("<<", 1)
            value: list[str] = []
            while index < len(lines) and lines[index] != delimiter:
                value.append(lines[index])
                index += 1
            index += 1
            outputs[name] = "\n".join(value)
        elif equals != -1:
            name, value_text = line.split("=", 1)
            outputs[name] = value_text
    return outputs


class ReleaseVersionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        repository_path = self.workspace / "repository"
        repository_path.mkdir()
        self.repo = GitRepository(repository_path)
        self.repo.commit()

    def run_action(
        self,
        *,
        release_type: str,
        tag_format: str,
        packages: list[dict[str, str]],
        strategy: str = "single",
        dev_suffix: str = "-SNAPSHOT",
    ) -> ActionResult:
        self.assertTrue(
            SCRIPT.is_file(),
            f"missing implementation: {SCRIPT.relative_to(ROOT)} does not exist",
        )
        output_file = self.workspace / "github-output"
        output_file.write_text("", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                f"--release-type={release_type}",
                f"--tag-format={tag_format}",
                f"--strategy={strategy}",
                f"--packages={json.dumps(packages)}",
                f"--dev-suffix={dev_suffix}",
            ],
            cwd=self.repo.path,
            check=False,
            capture_output=True,
            text=True,
            env=_environment(GITHUB_OUTPUT=str(output_file)),
        )
        return ActionResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
            _read_outputs(output_file),
        )

    def single(self, result: ActionResult) -> dict[str, object]:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        releases = result.releases
        self.assertEqual(len(releases), 1, releases)
        record = releases[0]
        self.assertEqual(result.outputs.get("version"), record["version"])
        self.assertEqual(result.outputs.get("tag"), record["tag"])
        return record

    def assertRelease(
        self,
        record: dict[str, object],
        *,
        version: str,
        tag: str,
        next_dev: str | None = None,
        base: str | None = None,
        first_release: bool | None = None,
        declared_ahead: bool | None = None,
    ) -> None:
        self.assertEqual(record["version"], version, record)
        self.assertEqual(record["tag"], tag, record)
        if next_dev is not None:
            self.assertEqual(record["next_dev"], next_dev, record)
        if base is not None:
            self.assertEqual(record["base"], base, record)
        if first_release is not None:
            self.assertIs(record["first_release"], first_release, record)
        if declared_ahead is not None:
            self.assertIs(record["declared_ahead"], declared_ahead, record)


class TagDerivedVersionTests(ReleaseVersionTestCase):
    def test_patch_minor_and_major_from_a_bare_0_2_0_tag(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        for release_type, version in (("patch", "0.2.1"), ("minor", "0.3.0"), ("major", "1.0.0")):
            with self.subTest(release_type=release_type):
                record = self.single(
                    self.run_action(
                        release_type=release_type,
                        tag_format="bare",
                        packages=[package(declared="0.2.1-SNAPSHOT")],
                    )
                )
                self.assertRelease(
                    record, version=version, tag=version, base="0.2.0", first_release=False
                )

    def test_patch_minor_and_major_from_a_v0_2_0_tag(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        for release_type, version in (("patch", "0.2.1"), ("minor", "0.3.0"), ("major", "1.0.0")):
            with self.subTest(release_type=release_type):
                record = self.single(
                    self.run_action(
                        release_type=release_type,
                        tag_format="v",
                        packages=[package()],
                        dev_suffix="",
                    )
                )
                self.assertRelease(
                    record,
                    version=version,
                    tag=f"v{version}",
                    base="0.2.0",
                    first_release=False,
                )

    def test_hotfix_and_multi_hotfix_mean_patch(self) -> None:
        self.repo.tag("v0.2.0", "0.2.0")
        self.repo.commit()
        for release_type in ("hotfix", "multi-hotfix"):
            for tag_format, tag in (("v", "v0.2.1"), ("bare", "0.2.1")):
                with self.subTest(release_type=release_type, tag_format=tag_format):
                    record = self.single(
                        self.run_action(
                            release_type=release_type,
                            tag_format=tag_format,
                            packages=[package()],
                        )
                    )
                    self.assertRelease(record, version="0.2.1", tag=tag, base="0.2.0")

    def test_declared_snapshot_version_is_ignored_once_a_tag_is_reachable(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="bare",
                packages=[package(declared="0.9.0-SNAPSHOT")],
            )
        )
        self.assertRelease(record, version="0.3.0", tag="0.3.0", first_release=False)

    def test_declared_dev_version_is_ignored_once_a_tag_is_reachable(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="v",
                packages=[package(declared="0.9.0.dev0")],
                dev_suffix=".dev0",
            )
        )
        self.assertRelease(record, version="0.3.0", tag="v0.3.0", first_release=False)

    def test_stripped_snapshot_is_no_longer_the_release_version(self) -> None:
        self.repo.tag("0.1.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="major",
                tag_format="bare",
                packages=[package(declared="0.2.0-SNAPSHOT")],
            )
        )
        self.assertRelease(record, version="1.0.0", tag="1.0.0", base="0.1.0")

    def test_highest_tag_is_chosen_by_numeric_comparison(self) -> None:
        self.repo.tag("v0.10.0")
        self.repo.commit()
        self.repo.tag("v0.9.0", "v0.9.12")
        self.repo.commit()
        record = self.single(
            self.run_action(release_type="patch", tag_format="v", packages=[package()])
        )
        self.assertRelease(record, version="0.10.1", tag="v0.10.1", base="0.10.0")

    def test_annotated_and_lightweight_tags_both_count(self) -> None:
        self.repo.tag("1.1.0")
        self.repo.commit()
        self.repo.tag("1.2.0", annotated=True)
        self.repo.commit()
        record = self.single(
            self.run_action(release_type="patch", tag_format="bare", packages=[package()])
        )
        self.assertRelease(record, version="1.2.1", tag="1.2.1", base="1.2.0")


class ReachabilityTests(ReleaseVersionTestCase):
    def _maintenance_history(self) -> None:
        self.repo.tag("v1.4.2")
        self.repo.branch("main-1.x")
        self.repo.commit()
        self.repo.tag("v2.0.0")
        self.repo.checkout("main-1.x")
        self.repo.commit()

    def test_maintenance_line_ignores_a_higher_tag_on_main(self) -> None:
        self._maintenance_history()
        record = self.single(
            self.run_action(release_type="multi-hotfix", tag_format="v", packages=[package()])
        )
        self.assertRelease(record, version="1.4.3", tag="v1.4.3", base="1.4.2")

    def test_main_still_bumps_from_its_own_highest_tag(self) -> None:
        self._maintenance_history()
        self.repo.checkout("main")
        record = self.single(
            self.run_action(release_type="patch", tag_format="v", packages=[package()])
        )
        self.assertRelease(record, version="2.0.1", tag="v2.0.1", base="2.0.0")

    def test_tag_on_an_unmerged_branch_is_ignored(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.branch("feature")
        self.repo.checkout("feature")
        self.repo.commit()
        self.repo.tag("0.9.0")
        self.repo.checkout("main")
        self.repo.commit()
        record = self.single(
            self.run_action(release_type="patch", tag_format="bare", packages=[package()])
        )
        self.assertRelease(record, version="0.2.1", tag="0.2.1", base="0.2.0")

    def test_tag_on_a_merged_line_counts(self) -> None:
        self.repo.tag("v1.0.0")
        self.repo.branch("line")
        self.repo.commit()
        self.repo.checkout("line")
        self.repo.commit()
        self.repo.tag("v1.1.0")
        self.repo.checkout("main")
        self.repo.merge("line")
        record = self.single(
            self.run_action(release_type="minor", tag_format="v", packages=[package()])
        )
        self.assertRelease(record, version="1.2.0", tag="v1.2.0", base="1.1.0")


class StrictReleaseTagTests(ReleaseVersionTestCase):
    def test_release_candidate_tag_is_ignored(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        self.repo.tag("v0.3.0-rc1")
        self.repo.commit()
        record = self.single(
            self.run_action(release_type="patch", tag_format="v", packages=[package()])
        )
        self.assertRelease(record, version="0.2.1", tag="v0.2.1", base="0.2.0")

    def test_pre_release_foreign_and_non_semver_tags_are_ignored_for_the_v_format(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        self.repo.tag(
            "v9.9.9-rc1",
            "v9.9.9-SNAPSHOT",
            "v9.9.9+build.1",
            "v9",
            "v9.9",
            "v9.9.9.9",
            "vv9.9.9",
            "V9.9.9",
            "foo-v9.9.9",
            "9.9.9",
            "latest",
        )
        self.repo.commit()
        record = self.single(
            self.run_action(release_type="patch", tag_format="v", packages=[package()])
        )
        self.assertRelease(record, version="0.2.1", tag="v0.2.1", base="0.2.0")

    def test_pre_release_foreign_and_non_semver_tags_are_ignored_for_the_bare_format(
        self,
    ) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        self.repo.tag(
            "9.9.9-SNAPSHOT",
            "9.9.9-rc.1",
            "9.9.9+build.1",
            "9.9",
            "9.9.9.9",
            "v9.9.9",
            "release-9.9.9",
            "latest",
        )
        self.repo.commit()
        record = self.single(
            self.run_action(release_type="patch", tag_format="bare", packages=[package()])
        )
        self.assertRelease(record, version="0.2.1", tag="0.2.1", base="0.2.0")

    def test_each_format_reads_only_its_own_tags(self) -> None:
        self.repo.tag("0.5.0", "v0.2.0")
        self.repo.commit()
        for tag_format, version, tag in (("v", "0.2.1", "v0.2.1"), ("bare", "0.5.1", "0.5.1")):
            with self.subTest(tag_format=tag_format):
                record = self.single(
                    self.run_action(
                        release_type="patch", tag_format=tag_format, packages=[package()]
                    )
                )
                self.assertRelease(record, version=version, tag=tag)

    def test_only_pre_release_tags_means_a_first_release(self) -> None:
        self.repo.tag("v0.3.0-rc1", "v0.3.0.dev1")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="v",
                packages=[package(declared="0.1.0.dev0")],
                dev_suffix=".dev0",
            )
        )
        self.assertRelease(record, version="0.1.0", tag="v0.1.0", first_release=True)


class FirstReleaseTests(ReleaseVersionTestCase):
    def test_declared_snapshot_is_released_whatever_the_release_type(self) -> None:
        for release_type in ("patch", "minor", "major", "hotfix", "multi-hotfix"):
            with self.subTest(release_type=release_type):
                record = self.single(
                    self.run_action(
                        release_type=release_type,
                        tag_format="bare",
                        packages=[package(declared="0.1.0-SNAPSHOT")],
                    )
                )
                self.assertRelease(
                    record,
                    version="0.1.0",
                    tag="0.1.0",
                    next_dev="0.1.1-SNAPSHOT",
                    first_release=True,
                )

    def test_declared_dev_version_is_released_whatever_the_release_type(self) -> None:
        for declared in ("0.1.0.dev0", "0.1.0.dev7"):
            for release_type in ("patch", "minor", "major"):
                with self.subTest(declared=declared, release_type=release_type):
                    record = self.single(
                        self.run_action(
                            release_type=release_type,
                            tag_format="v",
                            packages=[package(declared=declared)],
                            dev_suffix=".dev0",
                        )
                    )
                    self.assertRelease(
                        record,
                        version="0.1.0",
                        tag="v0.1.0",
                        next_dev="0.1.1.dev0",
                        first_release=True,
                    )

    def test_declared_plain_version_is_released(self) -> None:
        record = self.single(
            self.run_action(
                release_type="major",
                tag_format="v",
                packages=[package(declared="0.4.0")],
                dev_suffix=".dev0",
            )
        )
        self.assertRelease(record, version="0.4.0", tag="v0.4.0", first_release=True)

    def test_go_module_with_no_declared_version_bumps_from_0_0_0(self) -> None:
        for release_type, version in (
            ("patch", "0.0.1"),
            ("minor", "0.1.0"),
            ("major", "1.0.0"),
            ("multi-hotfix", "0.0.1"),
        ):
            with self.subTest(release_type=release_type):
                record = self.single(
                    self.run_action(
                        release_type=release_type,
                        tag_format="v",
                        packages=[package()],
                        dev_suffix="",
                    )
                )
                self.assertRelease(
                    record, version=version, tag=f"v{version}", first_release=True
                )

    def test_invalid_declared_version_bumps_from_0_0_0(self) -> None:
        for declared in (
            "banana",
            "1.0",
            "1.0-SNAPSHOT",
            "1.0.0-rc.1",
            "1.0.0-rc.1-SNAPSHOT",
            "v1.0.0",
        ):
            with self.subTest(declared=declared):
                record = self.single(
                    self.run_action(
                        release_type="patch",
                        tag_format="bare",
                        packages=[package(declared=declared)],
                    )
                )
                self.assertRelease(
                    record,
                    version="0.0.1",
                    tag="0.0.1",
                    next_dev="0.0.2-SNAPSHOT",
                    first_release=True,
                    declared_ahead=False,
                )


class NextDevelopmentVersionTests(ReleaseVersionTestCase):
    def test_next_dev_is_the_next_patch_whatever_the_release_type(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        for release_type, next_dev in (
            ("patch", "0.2.2-SNAPSHOT"),
            ("minor", "0.3.1-SNAPSHOT"),
            ("major", "1.0.1-SNAPSHOT"),
            ("hotfix", "0.2.2-SNAPSHOT"),
        ):
            with self.subTest(release_type=release_type):
                record = self.single(
                    self.run_action(
                        release_type=release_type,
                        tag_format="bare",
                        packages=[package(declared="0.2.1-SNAPSHOT")],
                    )
                )
                self.assertEqual(record["next_dev"], next_dev, record)

    def test_next_dev_after_a_major_release_with_the_snapshot_suffix(self) -> None:
        self.repo.tag("0.4.2")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="major",
                tag_format="bare",
                packages=[package(declared="0.4.3-SNAPSHOT")],
            )
        )
        self.assertRelease(record, version="1.0.0", tag="1.0.0", next_dev="1.0.1-SNAPSHOT")

    def test_next_dev_with_the_python_dev_suffix(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="v",
                packages=[package(declared="0.2.1.dev0")],
                dev_suffix=".dev0",
            )
        )
        self.assertRelease(record, version="0.3.0", tag="v0.3.0", next_dev="0.3.1.dev0")

    def test_next_dev_without_a_suffix(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor", tag_format="v", packages=[package()], dev_suffix=""
            )
        )
        self.assertRelease(record, version="0.3.0", tag="v0.3.0", next_dev="0.3.1")


class MonorepoStrategyTests(ReleaseVersionTestCase):
    def test_locked_step_uses_the_shared_bare_tag_and_ignores_package_tags(self) -> None:
        self.repo.tag("1.4.0", "core-9.0.0", "cli-8.0.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="bare",
                strategy="locked-step",
                packages=[package(name="workspace", declared="1.4.1-SNAPSHOT")],
            )
        )
        self.assertRelease(
            record, version="1.5.0", tag="1.5.0", next_dev="1.5.1-SNAPSHOT", base="1.4.0"
        )

    def test_locked_step_uses_the_shared_v_tag_and_ignores_package_tags(self) -> None:
        self.repo.tag("v1.4.0", "core-v9.0.0", "cli-v8.0.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="patch",
                tag_format="v",
                strategy="locked-step",
                packages=[package(name="workspace", declared="1.4.1.dev0")],
                dev_suffix=".dev0",
            )
        )
        self.assertRelease(
            record, version="1.4.1", tag="v1.4.1", next_dev="1.4.2.dev0", base="1.4.0"
        )

    def test_independent_packages_bump_from_their_own_bare_tags(self) -> None:
        self.repo.tag("core-1.4.0", "cli-0.9.2")
        self.repo.commit()
        self.repo.tag("2.0.0", "core-v5.0.0", "core-utils-7.0.0", "cli-0.9.3-SNAPSHOT")
        self.repo.commit()
        result = self.run_action(
            release_type="minor",
            tag_format="bare",
            strategy="independent",
            packages=[
                package(name="core", prefix="core-", declared="1.4.1-SNAPSHOT"),
                package(name="cli", prefix="cli-", declared="0.9.3-SNAPSHOT"),
            ],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = result.by_package()
        self.assertEqual(set(records), {"core", "cli"})
        self.assertRelease(
            records["core"],
            version="1.5.0",
            tag="core-1.5.0",
            next_dev="1.5.1-SNAPSHOT",
            base="1.4.0",
            first_release=False,
        )
        self.assertRelease(
            records["cli"],
            version="0.10.0",
            tag="cli-0.10.0",
            next_dev="0.10.1-SNAPSHOT",
            base="0.9.2",
            first_release=False,
        )

    def test_independent_python_packages_bump_from_their_own_v_tags(self) -> None:
        self.repo.tag("core-v1.4.0", "cli-v0.9.2", "v2.0.0")
        self.repo.commit()
        result = self.run_action(
            release_type="patch",
            tag_format="v",
            strategy="independent",
            packages=[
                package(name="core", prefix="core-v", declared="1.4.1.dev0"),
                package(name="cli", prefix="cli-v", declared="0.9.3.dev0"),
            ],
            dev_suffix=".dev0",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = result.by_package()
        self.assertEqual(set(records), {"core", "cli"})
        self.assertRelease(
            records["core"],
            version="1.4.1",
            tag="core-v1.4.1",
            next_dev="1.4.2.dev0",
            base="1.4.0",
        )
        self.assertRelease(
            records["cli"],
            version="0.9.3",
            tag="cli-v0.9.3",
            next_dev="0.9.4.dev0",
            base="0.9.2",
        )

    def test_independent_package_without_a_tag_is_a_first_release(self) -> None:
        self.repo.tag("core-1.4.0")
        self.repo.commit()
        result = self.run_action(
            release_type="minor",
            tag_format="bare",
            strategy="independent",
            packages=[
                package(name="core", prefix="core-", declared="1.4.1-SNAPSHOT"),
                package(name="cli", prefix="cli-", declared="0.1.0-SNAPSHOT"),
                package(name="docs", prefix="docs-", declared="not-a-version"),
            ],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = result.by_package()
        self.assertEqual(set(records), {"core", "cli", "docs"})
        self.assertRelease(
            records["core"], version="1.5.0", tag="core-1.5.0", first_release=False
        )
        self.assertRelease(
            records["cli"],
            version="0.1.0",
            tag="cli-0.1.0",
            next_dev="0.1.1-SNAPSHOT",
            first_release=True,
        )
        self.assertRelease(
            records["docs"],
            version="0.1.0",
            tag="docs-0.1.0",
            next_dev="0.1.1-SNAPSHOT",
            first_release=True,
        )

    def test_independent_package_tag_on_another_line_is_ignored(self) -> None:
        self.repo.tag("core-1.4.0")
        self.repo.branch("other")
        self.repo.checkout("other")
        self.repo.commit()
        self.repo.tag("core-3.0.0")
        self.repo.checkout("main")
        self.repo.commit()
        result = self.run_action(
            release_type="patch",
            tag_format="bare",
            strategy="independent",
            packages=[package(name="core", prefix="core-", declared="1.4.1-SNAPSHOT")],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRelease(result.by_package()["core"], version="1.4.1", tag="core-1.4.1")


class DeclaredAheadTests(ReleaseVersionTestCase):
    def test_declared_version_ahead_of_the_computed_release_is_flagged(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="bare",
                packages=[package(declared="1.0.0-SNAPSHOT")],
            )
        )
        self.assertRelease(record, version="0.3.0", tag="0.3.0", declared_ahead=True)

    def test_declared_dev_version_ahead_of_the_computed_release_is_flagged(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="v",
                packages=[package(declared="1.0.0.dev0")],
                dev_suffix=".dev0",
            )
        )
        self.assertRelease(record, version="0.3.0", tag="v0.3.0", declared_ahead=True)

    def test_declared_version_equal_to_or_below_the_release_is_not_flagged(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        for declared in ("0.3.0-SNAPSHOT", "0.2.1-SNAPSHOT", "0.2.0", "0.1.0-SNAPSHOT"):
            with self.subTest(declared=declared):
                record = self.single(
                    self.run_action(
                        release_type="minor",
                        tag_format="bare",
                        packages=[package(declared=declared)],
                    )
                )
                self.assertRelease(
                    record, version="0.3.0", tag="0.3.0", declared_ahead=False
                )

    def test_invalid_or_empty_declared_version_is_not_flagged(self) -> None:
        self.repo.tag("v0.2.0")
        self.repo.commit()
        for declared in ("", "banana", "9.0", "9.0.0-rc.1"):
            with self.subTest(declared=declared):
                record = self.single(
                    self.run_action(
                        release_type="patch",
                        tag_format="v",
                        packages=[package(declared=declared)],
                        dev_suffix="",
                    )
                )
                self.assertRelease(
                    record, version="0.2.1", tag="v0.2.1", declared_ahead=False
                )

    def test_first_release_of_the_declared_version_is_not_flagged(self) -> None:
        record = self.single(
            self.run_action(
                release_type="minor",
                tag_format="bare",
                packages=[package(declared="0.5.0-SNAPSHOT")],
            )
        )
        self.assertRelease(
            record, version="0.5.0", tag="0.5.0", first_release=True, declared_ahead=False
        )

    def test_declared_ahead_is_computed_per_independent_package(self) -> None:
        self.repo.tag("core-1.4.0", "cli-0.9.2")
        self.repo.commit()
        result = self.run_action(
            release_type="patch",
            tag_format="bare",
            strategy="independent",
            packages=[
                package(name="core", prefix="core-", declared="3.0.0-SNAPSHOT"),
                package(name="cli", prefix="cli-", declared="0.9.3-SNAPSHOT"),
            ],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = result.by_package()
        self.assertRelease(
            records["core"], version="1.4.1", tag="core-1.4.1", declared_ahead=True
        )
        self.assertRelease(
            records["cli"], version="0.9.3", tag="cli-0.9.3", declared_ahead=False
        )


class ReleaseTypeTests(ReleaseVersionTestCase):
    def test_unknown_release_type_fails_without_outputs(self) -> None:
        self.repo.tag("0.2.0")
        self.repo.commit()
        for release_type in ("huge", "release-type/minor", "prerelease"):
            with self.subTest(release_type=release_type):
                result = self.run_action(
                    release_type=release_type,
                    tag_format="bare",
                    packages=[package(declared="0.2.1-SNAPSHOT")],
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("::error", result.stdout + result.stderr)
                self.assertNotIn("releases", result.outputs)
                self.assertNotIn("version", result.outputs)
                self.assertNotIn("tag", result.outputs)


if __name__ == "__main__":
    unittest.main()
