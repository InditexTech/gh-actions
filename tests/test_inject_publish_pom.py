# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the ephemeral Maven Central publish-plumbing injector."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path


INJECTOR = (
    Path(__file__).resolve().parents[1]
    / "maven-central"
    / "scripts"
    / "inject_publish_pom.py"
)
POM_NS = "http://maven.apache.org/POM/4.0.0"

NAMESPACED_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.inditextech</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.13.0</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

# An aggregator with neither <build> nor <plugins> yet -- the injector must
# create the whole chain.
BARE_PARENT_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.inditextech</groupId>
  <artifactId>parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>orders-api</module>
  </modules>
</project>
"""


def _q(local: str) -> str:
    return f"{{{POM_NS}}}{local}"


def _find_plugin(pom_text: str, artifact_id: str) -> ElementTree.Element:
    root = ElementTree.fromstring(pom_text)
    for plugin in root.iter(_q("plugin")):
        found = plugin.find(_q("artifactId"))
        if found is not None and found.text == artifact_id:
            return plugin
    raise AssertionError(f"plugin {artifact_id} not found in:\n{pom_text}")


def _text(element: ElementTree.Element, path: str) -> str | None:
    child = element.find("/".join(_q(part) for part in path.split("/")))
    return child.text if child is not None else None


class InjectPublishPomTests(unittest.TestCase):
    def run_injector(
        self,
        pom: Path,
        settings: Path,
        *,
        auto_publish: str = "true",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(INJECTOR),
                "--pom",
                str(pom),
                "--settings",
                str(settings),
                "--auto-publish",
                auto_publish,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_injects_governed_publish_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pom = root / "pom.xml"
            pom.write_text(NAMESPACED_POM, encoding="utf-8")
            settings = root / "settings.xml"

            result = self.run_injector(pom, settings)
            self.assertEqual(result.returncode, 0, result.stderr)
            pom_text = pom.read_text(encoding="utf-8")

        central = _find_plugin(pom_text, "central-publishing-maven-plugin")
        self.assertEqual(_text(central, "groupId"), "org.sonatype.central")
        self.assertEqual(_text(central, "version"), "0.5.0")
        self.assertEqual(_text(central, "extensions"), "true")
        self.assertEqual(_text(central, "configuration/publishingServerId"), "central")
        self.assertEqual(_text(central, "configuration/autoPublish"), "true")
        self.assertEqual(_text(central, "configuration/waitUntil"), "published")

        gpg = _find_plugin(pom_text, "maven-gpg-plugin")
        self.assertEqual(_text(gpg, "groupId"), "org.apache.maven.plugins")
        self.assertEqual(_text(gpg, "version"), "3.2.5")
        self.assertEqual(_text(gpg, "executions/execution/phase"), "verify")
        self.assertEqual(_text(gpg, "executions/execution/goals/goal"), "sign")
        args = [
            arg.text
            for arg in gpg.iter(_q("arg"))
        ]
        self.assertEqual(args, ["--pinentry-mode", "loopback"])

        # The original compiler plugin survives.
        self.assertIsNotNone(_find_plugin(pom_text, "maven-compiler-plugin"))

    def test_auto_publish_false_waits_only_for_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pom = root / "pom.xml"
            pom.write_text(NAMESPACED_POM, encoding="utf-8")
            settings = root / "settings.xml"

            result = self.run_injector(pom, settings, auto_publish="false")
            self.assertEqual(result.returncode, 0, result.stderr)
            central = _find_plugin(pom.read_text(encoding="utf-8"), "central-publishing-maven-plugin")

        self.assertEqual(_text(central, "configuration/autoPublish"), "false")
        self.assertEqual(_text(central, "configuration/waitUntil"), "validated")

    def test_creates_build_and_plugins_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pom = root / "pom.xml"
            pom.write_text(BARE_PARENT_POM, encoding="utf-8")
            settings = root / "settings.xml"

            result = self.run_injector(pom, settings)
            self.assertEqual(result.returncode, 0, result.stderr)
            pom_text = pom.read_text(encoding="utf-8")

        # Still valid XML with exactly one build/plugins carrying both plugins.
        root_element = ElementTree.fromstring(pom_text)
        builds = root_element.findall(_q("build"))
        self.assertEqual(len(builds), 1)
        self.assertIsNotNone(_find_plugin(pom_text, "central-publishing-maven-plugin"))
        self.assertIsNotNone(_find_plugin(pom_text, "maven-gpg-plugin"))
        # The pre-existing aggregation content is preserved.
        self.assertEqual(_text(root_element, "packaging"), "pom")

    def test_injection_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pom = root / "pom.xml"
            pom.write_text(NAMESPACED_POM, encoding="utf-8")
            settings = root / "settings.xml"

            first = self.run_injector(pom, settings)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self.run_injector(pom, settings)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already-injected", second.stdout)
            pom_text = pom.read_text(encoding="utf-8")

        root_element = ElementTree.fromstring(pom_text)
        central = [
            plugin
            for plugin in root_element.iter(_q("plugin"))
            if (plugin.find(_q("artifactId")) is not None)
            and plugin.find(_q("artifactId")).text == "central-publishing-maven-plugin"
        ]
        self.assertEqual(len(central), 1)

    def test_settings_reference_env_and_never_hold_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pom = root / "pom.xml"
            pom.write_text(NAMESPACED_POM, encoding="utf-8")
            settings = root / "settings.xml"

            result = self.run_injector(pom, settings)
            self.assertEqual(result.returncode, 0, result.stderr)
            settings_text = settings.read_text(encoding="utf-8")

        # Valid XML, references env interpolation, names the matching server id.
        parsed = ElementTree.fromstring(settings_text)
        self.assertTrue(parsed.tag.endswith("settings"))
        self.assertIn("${env.MAVEN_CENTRAL_USERNAME}", settings_text)
        self.assertIn("${env.MAVEN_CENTRAL_PASSWORD}", settings_text)
        self.assertIn("<id>central</id>", settings_text)
        # No credential value is ever written; only env references appear.
        self.assertNotIn("password>central-token", settings_text)

    def test_rejects_doctype_and_entities(self) -> None:
        bomb = (
            '<?xml version="1.0"?>\n'
            "<!DOCTYPE project [\n"
            '  <!ENTITY lol "lol">\n'
            "]>\n"
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <artifactId>&lol;</artifactId>\n"
            "</project>\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pom = root / "pom.xml"
            pom.write_text(bomb, encoding="utf-8")
            settings = root / "settings.xml"

            result = self.run_injector(pom, settings)

        self.assertEqual(result.returncode, 1)
        self.assertIn("must not declare a DOCTYPE or entities", result.stderr)
        self.assertFalse(settings.exists())

    def test_missing_pom_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.run_injector(root / "absent.xml", root / "settings.xml")

        self.assertEqual(result.returncode, 1)
        self.assertTrue(
            result.stderr.startswith("Publish injection failed: "),
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
