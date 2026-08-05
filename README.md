# Shared GitHub Actions

This internal catalog contains the reusable runtime action for publishing
pre-built Python distributions through trusted publishing.

## Available action

- `pypi/` publishes pre-built Python distributions to PyPI or TestPyPI with
  SHA-pinned upstream dependencies and local distribution validation.

The action's applicable quality and security evidence is mapped in
[`pypi/TESTING.md`](pypi/TESTING.md).

The repository intentionally keeps only the PyPI action, its runtime script,
and isolated local tests for the action contract and distribution validator.
Cross-repository integration, acceptance, and protected governance flows
(including TestPyPI smoke coverage) live in `internal-ops`.

Consumers must pin every catalog reference to an immutable commit SHA.
Promotion of a new `pypi` action commit also requires a green protected
TestPyPI canary because the pinned upstream PyPA publisher does not support
nested composite invocation as part of its public compatibility contract.
