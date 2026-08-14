# Maven Central action test coverage

The repository owns only tests for the isolated action implementation and its
public input contract. Protected signing, live Central Portal upload, registry
behavior, retries, and cross-repository consumers remain in the `internal-ops`
control plane.

| # | Area | Applicability and evidence |
| ---: | --- | --- |
| 1 | Responsibility and scope | **Covered.** `action.yml` validates, signs, and deploys a checked-out reactor only. The README excludes build, test, and toolchain setup. Contract tests fix the composite step order (validate → import key → publish). |
| 2 | Public contract | **Covered.** `action-validator` checks metadata syntax. `test_maven_central_contract.py` fixes the exact inputs, defaults, descriptions, README table, absence of outputs, and that credentials are not inputs. |
| 3 | Input validation | **Covered.** Subprocess tests in `test_validate_publish.py` exercise missing/empty credentials, the reserved `oidc` seam, unknown strategies, invalid `project-type`/`auto-publish`, missing `pom.xml`, absolute/traversal/symlink working directories, and `packages` misuse. |
| 4 | Functional correctness | **Locally covered; live gate required.** `test_inject_publish_pom.py` proves the injected plugins, versions, and phase bindings; the composite runs `mvn ... deploy`. The protected Maven canary in `internal-ops` proves a real signed upload from the exact commit. |
| 5 | Security | **Covered for the local boundary.** Inputs reach shell through environment variables; the boundary guard fails closed before signing; the injector rejects DOCTYPE/entity POMs (closing XXE/entity expansion stdlib-only); credential values never touch disk (settings reference `${env.*}`, the passphrase stays in `MAVEN_GPG_PASSPHRASE`); Zizmor audits the composite. |
| 6 | Permissions and credentials | **Covered.** The action takes no credential inputs, reads the four required secrets from the job environment, and never logs a credential value. The protected canary proves real org-secret provisioning. |
| 7 | Idempotency and side effects | **Contract covered; live gate required.** Injection is idempotent (re-running is a no-op) and asserted. `auto-publish: false` stops at a validated deployment; the protected canary exercises publish and re-publish. |
| 8 | Reliability and cleanup | **Not locally applicable.** Injection and settings are written under `RUNNER_TEMP` on the ephemeral checkout and never committed. The canary detects upload failures. |
| 9 | Portability | **Covered within the supported envelope.** Only GitHub-hosted GNU/Linux is supported. Tests cover absolute paths, traversal, symlinked components, and namespaced/bare POM shapes. |
| 10 | Determinism and dependencies | **Covered.** The governed publish plugins are pinned (`central-publishing-maven-plugin` 0.5.0, `maven-gpg-plugin` 3.2.5); the runtime scripts use only the Python standard library; all CI actions and `action-validator` use immutable SHAs/version. |
| 11 | Observability and errors | **Covered.** Failures use exit code 1 with the stable `Publish validation failed:` / `Publish injection failed:` prefixes, name the rejected boundary, keep stdout empty on failure, and never expose a credential value. |
| 12 | Performance | **No separate benchmark required.** Validation performs one bounded reactor scan with no network calls. Deploy duration is controlled by the pinned plugins and measured by the protected canary. |
| 13 | Maintainability, tests, and releases | **Covered.** Runtime logic is isolated in two typed stdlib modules, contract and adversarial tests are separate, Actionlint/Zizmor/action-validator are blocking, and consumers must use an immutable catalog commit. |

## Promotion gate

Local coverage proves the boundary guard, the ephemeral publish-plumbing
injection, and the deploy-phase wiring — but performs no live upload and imports
no GPG key. Because the signed Central Portal upload cannot be exercised without
governed credentials, a new `maven-central` action SHA must not be promoted to
consumers until the protected Maven canary in `internal-ops` publishes
successfully for that exact SHA.
