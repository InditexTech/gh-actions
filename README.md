# Shared GitHub Actions

This internal catalog contains versioned, nonsecret GitHub Actions and
reusable workflows for InditexTech repositories.

- `pypi/` publishes pre-built Python distributions through trusted publishing.
- `base-archetype-integrity/` validates a base-archetype checkout without
  executing candidate code.

Privileged CI governance orchestration, App credentials, and live acceptance
pilots remain in `internal-ops`. Consumers must pin every catalog reference to
an immutable commit SHA.
