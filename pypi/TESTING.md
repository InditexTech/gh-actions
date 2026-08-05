# PyPI action test coverage

The repository owns only tests for the isolated action implementation and its
public input contract. Protected OIDC publication, registry behavior, retries,
and cross-repository consumers remain in the `internal-ops` control plane.

| # | Area | Applicability and evidence |
| ---: | --- | --- |
| 1 | Responsibility and scope | **Covered.** `action.yml` validates and publishes pre-built distributions only. The README excludes build and test preparation. Contract tests require one public action and no outputs. |
| 2 | Public contract | **Covered.** `action-validator` checks metadata syntax. `test_action_contract.py` fixes the exact inputs, defaults, descriptions, forwarding, README table, and absence of outputs. |
| 3 | Input validation | **Covered.** Subprocess tests exercise missing paths, empty/nested directories, exact booleans, PyPI/TestPyPI URL allowlisting, traversal, symlinks, special files, spaces, and unsupported artifacts. |
| 4 | Functional correctness | **Locally covered; live gate required.** CI invokes `uses: ./pypi` and proves the action fails before publication without OIDC. The protected TestPyPI canary in `internal-ops` proves the successful path from the exact commit. |
| 5 | Security | **Covered for the local boundary.** Inputs reach shell through environment variables, boolean and URL allowlists reject injection/SSRF, lexical and resolved path checks prevent escape, `lstat` rejects symlinks and special files, and Zizmor audits the composite. There is no dependency manifest for dependency audit. |
| 6 | Permissions and credentials | **Covered.** The action accepts no password or token input, checks the runner-provided OIDC environment, never logs its request token, and documents job-scoped `id-token: write`. The protected canary proves real minimal-permission OIDC. |
| 7 | Idempotency and side effects | **Contract covered; live gate required.** `skip-existing` is an exact boolean forwarded to PyPA. The protected canary publishes once and retries from a separate job with `skip-existing: true`. |
| 8 | Reliability and cleanup | **Not locally applicable.** The wrapper creates no temporary files, locks, child processes, `pre`, or `post` lifecycle. PyPA owns its generated container action cleanup; the canary detects publication failures. |
| 9 | Portability | **Covered within the supported envelope.** PyPA is Docker-based, so only GitHub-hosted GNU/Linux is supported. Tests cover absolute paths, spaces, read-only files, symlinks, and POSIX special files; macOS/Windows execution is intentionally unsupported. |
| 10 | Determinism and dependencies | **Covered.** PyPA and all CI actions use immutable SHAs. The runtime validator uses only the Python standard library. `action-validator` is versioned and downloaded with a fixed SHA-256. |
| 11 | Observability and errors | **Covered.** Failures use exit code 1 and the stable `Distribution validation failed:` prefix, explain the rejected boundary, keep stdout empty, and do not expose OIDC request credentials. |
| 12 | Performance | **No separate benchmark required.** Validation performs one sorted, linear directory scan with no network or API calls. Publication duration is controlled by the pinned upstream action and measured by the protected canary. |
| 13 | Maintainability, tests, and releases | **Covered.** Runtime validation is isolated in one typed stdlib module, contract and adversarial tests are separate, Actionlint/Zizmor/action-validator are blocking, and consumers must use an immutable catalog commit. |

## Promotion gate

The Node OIDC POC proved that an external composite preserves the consumer
workflow's `job_workflow_ref`. It did not exercise PyPA's generated nested
action. Because PyPA does not support composite wrapping as part of its public
compatibility contract, a new `pypi` action SHA must not be promoted until the
protected TestPyPI workflow in `internal-ops` succeeds for that exact SHA.
