#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISENO TEXTIL S.A. (INDITEX S.A.)
# SPDX-License-Identifier: Apache-2.0
"""Materialize the governed Maven Central publish plumbing at deploy time.

Consumer POMs deliberately carry no publish plumbing: the governance model owns
signing and upload centrally, so ``distributionManagement`` and the
``central-publishing`` / ``maven-gpg`` plugins never live in a project's
``pom.xml``. This script injects them into the reactor POM **only for the
privileged deploy run**, on the ephemeral CI checkout, and writes an ephemeral
``settings.xml``. Nothing here is ever committed back to the consumer.

Two governed, gh-actions-owned pins are injected (mirroring how the PyPI action
pins its upstream publisher SHA locally rather than importing a control-plane
value):

* ``org.sonatype.central:central-publishing-maven-plugin`` as a build
  ``<extensions>`` so its publish goal binds to the ``deploy`` phase and uploads
  the reactor bundle to the Central Portal (``publishingServerId`` matches the
  ephemeral ``settings.xml`` server id);
* ``org.apache.maven.plugins:maven-gpg-plugin`` bound to ``verify`` so every
  attached artifact is signed before the bundle is assembled.

The ``settings.xml`` references ``${env.MAVEN_CENTRAL_USERNAME}`` /
``${env.MAVEN_CENTRAL_PASSWORD}`` -- Maven interpolates them at runtime, so the
credential **values** are never serialized to disk by this action. The GPG
passphrase is read by ``maven-gpg-plugin`` from ``MAVEN_GPG_PASSPHRASE`` in the
deploy step's environment and likewise never written here.

Injection is idempotent: re-running against an already-injected POM is a no-op.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import NoReturn

# gh-actions owns the runtime pins for the governed publish mechanism. These are
# the same versions the control-plane profile records for the consumer POM's
# plugin-management, kept here so the composite is self-contained.
CENTRAL_PUBLISHING_GROUP_ID = "org.sonatype.central"
CENTRAL_PUBLISHING_ARTIFACT_ID = "central-publishing-maven-plugin"
CENTRAL_PUBLISHING_VERSION = "0.5.0"
GPG_GROUP_ID = "org.apache.maven.plugins"
GPG_ARTIFACT_ID = "maven-gpg-plugin"
GPG_VERSION = "3.2.5"
PUBLISHING_SERVER_ID = "central"

BOOLEAN_INPUTS = frozenset({"true", "false"})

SETTINGS_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <servers>
    <server>
      <id>{server_id}</id>
      <username>${{env.MAVEN_CENTRAL_USERNAME}}</username>
      <password>${{env.MAVEN_CENTRAL_PASSWORD}}</password>
    </server>
  </servers>
</settings>
"""


def fail(message: str) -> NoReturn:
    print(f"Publish injection failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def _namespace(root: ElementTree.Element) -> str:
    match = re.match(r"\{(?P<uri>[^}]*)\}", root.tag)
    return match.group("uri") if match else ""


def _qualify(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}" if namespace else local


def _child_text(parent: ElementTree.Element, namespace: str, local: str) -> str | None:
    child = parent.find(_qualify(namespace, local))
    return child.text.strip() if child is not None and child.text else None


def _ensure_child(
    parent: ElementTree.Element, namespace: str, local: str
) -> ElementTree.Element:
    existing = parent.find(_qualify(namespace, local))
    if existing is not None:
        return existing
    return ElementTree.SubElement(parent, _qualify(namespace, local))


def _set(parent: ElementTree.Element, namespace: str, local: str, text: str) -> ElementTree.Element:
    element = ElementTree.SubElement(parent, _qualify(namespace, local))
    element.text = text
    return element


def _existing_plugin_ids(plugins: ElementTree.Element, namespace: str) -> set[str]:
    ids: set[str] = set()
    for plugin in plugins.findall(_qualify(namespace, "plugin")):
        artifact_id = _child_text(plugin, namespace, "artifactId")
        if artifact_id:
            ids.add(artifact_id)
    return ids


def _append_central_publishing(
    plugins: ElementTree.Element, namespace: str, *, auto_publish: str
) -> None:
    plugin = ElementTree.SubElement(plugins, _qualify(namespace, "plugin"))
    _set(plugin, namespace, "groupId", CENTRAL_PUBLISHING_GROUP_ID)
    _set(plugin, namespace, "artifactId", CENTRAL_PUBLISHING_ARTIFACT_ID)
    _set(plugin, namespace, "version", CENTRAL_PUBLISHING_VERSION)
    _set(plugin, namespace, "extensions", "true")
    configuration = ElementTree.SubElement(plugin, _qualify(namespace, "configuration"))
    _set(configuration, namespace, "publishingServerId", PUBLISHING_SERVER_ID)
    _set(configuration, namespace, "autoPublish", auto_publish)
    # Wait for the terminal state the caller asked for: a full publish when
    # auto-publishing, otherwise stop once the bundle is validated and awaits a
    # manual release.
    _set(
        configuration,
        namespace,
        "waitUntil",
        "published" if auto_publish == "true" else "validated",
    )


def _append_gpg(plugins: ElementTree.Element, namespace: str) -> None:
    plugin = ElementTree.SubElement(plugins, _qualify(namespace, "plugin"))
    _set(plugin, namespace, "groupId", GPG_GROUP_ID)
    _set(plugin, namespace, "artifactId", GPG_ARTIFACT_ID)
    _set(plugin, namespace, "version", GPG_VERSION)
    configuration = ElementTree.SubElement(plugin, _qualify(namespace, "configuration"))
    # Non-interactive signing on a CI runner: the passphrase arrives via
    # MAVEN_GPG_PASSPHRASE and gpg must not open a TTY.
    gpg_arguments = ElementTree.SubElement(configuration, _qualify(namespace, "gpgArguments"))
    _set(gpg_arguments, namespace, "arg", "--pinentry-mode")
    _set(gpg_arguments, namespace, "arg", "loopback")
    executions = ElementTree.SubElement(plugin, _qualify(namespace, "executions"))
    execution = ElementTree.SubElement(executions, _qualify(namespace, "execution"))
    _set(execution, namespace, "id", "sign-artifacts")
    _set(execution, namespace, "phase", "verify")
    goals = ElementTree.SubElement(execution, _qualify(namespace, "goals"))
    _set(goals, namespace, "goal", "sign")


def _reject_doctype(text: str, pom_path: Path) -> None:
    # A well-formed Maven POM never declares a DOCTYPE or entities. Refusing them
    # closes the XXE / entity-expansion ("billion laughs") class without pulling
    # in a third-party parser, keeping this action stdlib-only and dependency
    # free -- the parse below then runs on entity-free input.
    stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    if re.search(r"<!doctype", stripped, flags=re.IGNORECASE) or re.search(
        r"<!entity", stripped, flags=re.IGNORECASE
    ):
        fail(f"reactor pom.xml must not declare a DOCTYPE or entities: {pom_path}")


def inject_into_pom(pom_path: Path, *, auto_publish: str) -> bool:
    try:
        source = pom_path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read reactor pom.xml: {pom_path} ({error})")
    _reject_doctype(source, pom_path)
    try:
        tree = ElementTree.ElementTree(ElementTree.fromstring(source))
    except ElementTree.ParseError as error:
        fail(f"reactor pom.xml is not valid XML: {pom_path} ({error})")

    root = tree.getroot()
    namespace = _namespace(root)
    if namespace:
        ElementTree.register_namespace("", namespace)

    build = _ensure_child(root, namespace, "build")
    plugins = _ensure_child(build, namespace, "plugins")
    present = _existing_plugin_ids(plugins, namespace)

    changed = False
    if CENTRAL_PUBLISHING_ARTIFACT_ID not in present:
        _append_central_publishing(plugins, namespace, auto_publish=auto_publish)
        changed = True
    if GPG_ARTIFACT_ID not in present:
        _append_gpg(plugins, namespace)
        changed = True

    if changed:
        ElementTree.indent(tree, space="  ")
        tree.write(pom_path, encoding="unicode", xml_declaration=False)
    return changed


def write_settings(settings_path: Path) -> None:
    try:
        settings_path.write_text(
            SETTINGS_TEMPLATE.format(server_id=PUBLISHING_SERVER_ID),
            encoding="utf-8",
        )
    except OSError as error:
        fail(f"cannot write settings.xml: {settings_path} ({error})")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--pom", required=True, type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--auto-publish", default="true")
    try:
        arguments = parser.parse_args(argv[1:])
    except SystemExit:
        fail("invalid arguments")

    if arguments.auto_publish not in BOOLEAN_INPUTS:
        fail("auto-publish must be exactly 'true' or 'false'")
    if not arguments.pom.is_file():
        fail(f"reactor pom.xml does not exist: {arguments.pom}")

    changed = inject_into_pom(arguments.pom, auto_publish=arguments.auto_publish)
    write_settings(arguments.settings)
    action = "injected governed publish plugins into" if changed else "left already-injected"
    print(f"{action} {arguments.pom}; wrote publish settings to {arguments.settings}")


if __name__ == "__main__":
    main(sys.argv)
