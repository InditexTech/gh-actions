# Proposal

## Shared change

This change implements part of the shared OpenSpec change `maven-central-artifactid`, owned by the store `cac-inditextech` (`repos/cac-inditextech`).

- Role of this repository: **contract-owner**
- Shared spec: `maven-central-package-resolution` — read it with
  `openspec show maven-central-artifactid --type change --store cac-inditextech --json --deltas-only`
- Manifest: `repos/cac-inditextech/openspec/changes/maven-central-artifactid/multirepo.yml`

## Why

The `maven-central` action validates the publish boundary by directory name, so reactors whose directories differ from their artifactIds (karatetools-oss) fail before publishing.

## What changes here

- Resolve declared artifactIds to the module whose pom declares them, verifying identity of every candidate, keeping nested/ambiguity/ancestor semantics.
- Add tests (flat reactor, nested, mismatch, duplicate, unknown), update README/TESTING, bump `.github/action-release.json` to v1.2.1.

Out of scope: everything owned by another repository in the shared change.

## Capabilities

### New Capabilities
- `maven-central-publish-validation`: Define how the maven-central action resolves declared packages to reactor modules before publishing.

### Modified Capabilities

## Impact

`gh-actions` only.
