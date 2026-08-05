# Shared GitHub Actions

This internal catalog contains the reusable runtime action for publishing
pre-built Python distributions through trusted publishing.

## Available action

- `pypi/` publishes pre-built Python distributions to PyPI or TestPyPI with
  SHA-pinned upstream dependencies and local distribution validation.

The repository intentionally keeps only the PyPI action, its runtime script,
and isolated local tests for the action contract and distribution validator.
Cross-repository integration, acceptance, and protected governance flows
(including TestPyPI smoke coverage) live in `internal-ops`.

Consumers must pin every catalog reference to an immutable commit SHA.
