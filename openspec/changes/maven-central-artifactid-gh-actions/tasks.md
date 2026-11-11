# Tasks

## 1. Implementation

- [ ] 1.1 Resolve packages by pom artifactId with identity verification in `maven-central/scripts/validate_publish.py`. Done when: `python -m pytest tests/test_validate_publish.py` passes with flat, nested (aggregators and root included, only artifactId-resolved modules selected), mismatch, duplicate and unknown cases.
- [ ] 1.2 Run the contract tests and update `maven-central/README.md` and `TESTING.md`. Done when: `python -m pytest tests/test_maven_central_contract.py` passes and docs describe artifactId resolution.
- [ ] 1.3 Bump `.github/action-release.json` to v1.2.1. Done when: the release metadata test/validation in the repository passes.
- [ ] 1.4 [manual] Maintainers confirm the org variables, publish v1.2.1 and the protected Maven canary for that exact SHA. Done when: the canary run is green for the SHA.
