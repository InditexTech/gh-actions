# Shared GitHub Actions

This internal catalog contains the reusable runtime actions for publishing
governed build artifacts to their language registries.

## Available actions

- `pypi/` publishes pre-built Python distributions to PyPI or TestPyPI with
  SHA-pinned upstream dependencies and local distribution validation.
  Evidence: [`pypi/TESTING.md`](pypi/TESTING.md).
- `maven-central/` signs and publishes a checked-out Maven reactor to the
  Central Portal with governed, pinned publish plugins injected only for the
  deploy, so the consumer `pom.xml` carries no publish plumbing.
  Evidence: [`maven-central/TESTING.md`](maven-central/TESTING.md).
- `npm/` publishes pre-built npm `.tgz` tarballs through npm trusted publishing
  (OIDC), with an Environment-scoped `NPM_TOKEN` fallback only for a brand-new
  package and provenance enabled only when the repository is public.
  Evidence: [`npm/TESTING.md`](npm/TESTING.md).

The repository intentionally keeps only these actions, their runtime scripts,
and isolated local tests for the action contracts and boundary validators.
Cross-repository integration, acceptance, and protected governance flows
(including the TestPyPI and Maven canaries) live in `internal-ops`.

Consumers must pin every catalog reference to an immutable commit SHA.
The protected release workflow publishes reviewed catalog revisions as
immutable semantic tags and advances the matching mobile major tag only when
its tag ruleset is explicitly verified. Development `main` is never an update
candidate.
Promotion of a new `pypi` action commit also requires a green protected
TestPyPI canary because the pinned upstream PyPA publisher does not support
nested composite invocation as part of its public compatibility contract.
Promotion of a new `maven-central` action commit likewise requires a green
protected Maven canary, because the signed Central Portal upload cannot be
exercised locally without governed credentials.
Promotion of a new `npm` action commit likewise requires a green protected npm
canary, because trusted publishing to the registry cannot be exercised locally.
